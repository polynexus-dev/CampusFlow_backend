"""
NAAC SSR / AQAR document generator.

Compiles NAAC-tagged accreditation criteria (applied narrative(s) + evidence,
same source data SSRExportView already exposes as JSON+ZIP in
views/compliance.py) into a single submission-shaped .docx. Institution-wide,
not department/program-scoped — NAAC evaluates the institution as a whole,
unlike the NBA SAR (services/nba_sar_export.py), which is per-program.

Two modes, matching what an IQAC actually produces:
  - AQAR (financial_year given): one year's applied narrative + evidence per
    criterion — the annual incremental report.
  - SSR (financial_year omitted): every applied narrative across all years
    for each criterion, each labeled by year, plus the full multi-year
    evidence list. This is a deliberate improvement over SSRExportView's
    JSON, which drops narratives entirely when no year is given (narratives
    are year-scoped, so it only attaches one when the export itself is
    year-scoped) — for an actual SSR document that's too little to compile
    from, so here every already-applied narrative is surfaced instead,
    labeled by year, for IQAC to assemble the final SSR prose from. Nothing
    new is generated; only already-reviewed content is compiled.

Never generates new "official" content — a criterion/year with no applied
narrative renders an explicit placeholder, same boundary
AccreditationNarrativeDraft's own docstring describes.
"""
import io
from datetime import date

from django.db import connection

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

from ..models.compliance import AccreditationCriterion
from ..models.department import Department
from ..models.academics import Program
from ..models.profile import (
    AdministratorProfile, DepartmentHeadProfile, ManagementProfile,
    NonTeachingStaffProfile, StudentProfile, TeachingStaffProfile,
)

NOT_REVIEWED_PLACEHOLDER = (
    "No IQAC-approved narrative has been applied for this criterion/year yet. "
    "Add evidence and request/apply an AI narrative draft before final submission."
)

NAAC_TOP_LEVEL_TITLES = {
    "1": "Curricular Aspects",
    "2": "Teaching-Learning and Evaluation",
    "3": "Research, Innovations and Extension",
    "4": "Infrastructure and Learning Resources",
    "5": "Student Support and Progression",
    "6": "Governance, Leadership and Management",
    "7": "Institutional Values and Best Practices",
}


def _add_table(document, header, rows):
    table = document.add_table(rows=1, cols=len(header))
    table.style = "Light Grid Accent 1"
    for cell, text in zip(table.rows[0].cells, header):
        cell.text = ""
        run = cell.paragraphs[0].add_run(text)
        run.bold = True
    for row in rows:
        cells = table.add_row().cells
        for cell, value in zip(cells, row):
            cell.text = "" if value is None else str(value)
    return table


def _title_page(document, financial_year):
    tenant_name = getattr(connection.tenant, "name", "") or connection.schema_name

    title = document.add_paragraph()
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = title.add_run(tenant_name)
    run.bold = True
    run.font.size = Pt(20)

    subtitle = document.add_paragraph()
    subtitle.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if financial_year:
        run = subtitle.add_run(f"NAAC AQAR — Annual Quality Assurance Report ({financial_year.label})")
    else:
        run = subtitle.add_run("NAAC SSR — Self Study Report (all years, cumulative)")
    run.bold = True
    run.font.size = Pt(16)

    generated_line = document.add_paragraph()
    generated_line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    generated_line.add_run(f"Generated on {date.today().isoformat()} via CampusNexus")

    document.add_page_break()


def _extended_profile_section(document):
    document.add_heading("Institution Extended Profile", level=1)

    programs_by_level = list(
        Program.objects.filter(is_active=True).values_list("level", flat=True)
    )
    level_counts = {}
    for level in programs_by_level:
        level_counts[level] = level_counts.get(level, 0) + 1

    _add_table(
        document,
        ["Metric", "Value"],
        [
            ["Departments", Department.objects.count()],
            ["Active Programs", Program.objects.filter(is_active=True).count()],
            ["Total Students", StudentProfile.objects.count()],
            ["Students with Disability", StudentProfile.objects.filter(disability_status=True).count()],
            ["Teaching Staff", TeachingStaffProfile.objects.count()],
            ["Non-Teaching Staff", NonTeachingStaffProfile.objects.count()],
            ["Management Staff", ManagementProfile.objects.count()],
            ["Administrators", AdministratorProfile.objects.count()],
            ["Department Heads", DepartmentHeadProfile.objects.count()],
        ] + [[f"Programs — {level}", count] for level, count in sorted(level_counts.items())],
    )
    document.add_paragraph()


def _narrative_paragraphs_aqar(document, criterion, financial_year):
    narrative = criterion.narrative_drafts.filter(
        financial_year=financial_year, status="applied",
    ).order_by("-applied_at").first()
    document.add_paragraph(narrative.narrative_text if narrative else NOT_REVIEWED_PLACEHOLDER)


def _narrative_paragraphs_ssr(document, criterion):
    narratives = criterion.narrative_drafts.filter(status="applied").select_related(
        "financial_year",
    ).order_by("financial_year__start_date")
    if not narratives:
        document.add_paragraph(NOT_REVIEWED_PLACEHOLDER)
        return
    for narrative in narratives:
        p = document.add_paragraph()
        p.add_run(f"[{narrative.financial_year.label}] ").bold = True
        p.add_run(narrative.narrative_text)


def _criteria_section(document, financial_year):
    document.add_heading("Criterion-wise Narrative and Evidence", level=1)

    criteria = AccreditationCriterion.objects.filter(
        body=AccreditationCriterion.BODY_NAAC,
    ).order_by("code")

    current_group = None
    for criterion in criteria:
        group = criterion.code.split(".")[0]
        if group != current_group:
            current_group = group
            document.add_heading(
                f"Criterion {group}: {NAAC_TOP_LEVEL_TITLES.get(group, '')}", level=1,
            )

        document.add_heading(f"{criterion.code} — {criterion.title}", level=2)

        if financial_year:
            _narrative_paragraphs_aqar(document, criterion, financial_year)
        else:
            _narrative_paragraphs_ssr(document, criterion)

        evidence_qs = criterion.evidence.all()
        if financial_year:
            evidence_qs = evidence_qs.filter(financial_year=financial_year)
        evidence_items = list(evidence_qs.select_related("department", "financial_year", "linked_certificate").order_by("-created_at"))

        if not evidence_items:
            document.add_paragraph("No evidence recorded for this criterion/year yet.", style="Intense Quote")
            document.add_paragraph()
            continue

        header = ["Description", "Department", "Status"]
        if not financial_year:
            header.insert(1, "Year")

        rows = []
        for item in evidence_items:
            desc = item.description or (item.file.name.split("/")[-1] if item.file else "—")
            dept = item.department.name if item.department else "Institution-wide"
            row = [desc, dept, item.get_status_display()]
            if not financial_year:
                row.insert(1, item.financial_year.label)
            rows.append(row)

        _add_table(document, header, rows)
        document.add_paragraph()


def build_naac_document(financial_year=None):
    """Returns an io.BytesIO holding the finished .docx (AQAR if financial_year
    is given, otherwise the cumulative SSR)."""
    document = Document()

    _title_page(document, financial_year)
    _extended_profile_section(document)
    _criteria_section(document, financial_year)

    buffer = io.BytesIO()
    document.save(buffer)
    buffer.seek(0)
    return buffer

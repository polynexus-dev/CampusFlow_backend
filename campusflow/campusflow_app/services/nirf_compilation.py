"""
NIRF data compilation — assembles the raw figures NIRF's Data Capture System
asks for, under its five published parameter categories (TLR/RP/GO/OI/PR).

Deliberately produces no score or predicted rank (see models/nirf.py's
docstring) — this is a compiled data return, the same kind of thing
AISHEAnnualReturnView/AICTEDisclosureView already produce in
views/compliance.py, not a narrative submission. Returns the same
(heading, header, rows) "sections" shape _accreditation_xlsx_response
already consumes, so it's exported the same way.

Most figures are pulled from data already tracked for other purposes (see
the table in the NIRF plan): StudentProfile for strength/diversity,
TeachingStaffProfile for faculty, PlacementApplication/RecruitmentDrive for
graduation outcomes, StudentScholarshipRecord for economically/socially
challenged students. Only the figures with nowhere else to live (research
funding, patents, publications, library spend, higher-studies/govt-exam
counts) come from the manually-entered NIRFDataEntry row, and render an
explicit "not yet entered" placeholder when that row doesn't exist yet
rather than silently showing zero as if it were a real reported figure.
"""
from statistics import median

from django.db.models import Count, Sum

from ..models.fees import FeePayment
from ..models.profile import StudentProfile, TeachingStaffProfile
from ..models.scholarship import StudentScholarshipRecord
from ..models.tpo import PlacementApplication

NIRF_ENTRY_NOT_RECORDED = "Not yet entered — add a NIRFDataEntry for this financial year/category."


def _tlr_section(financial_year, nirf_entry):
    students = StudentProfile.objects.all()
    total_students = students.count()

    program_counts = list(
        students.exclude(program__isnull=True)
        .values("program__name").annotate(count=Count("id")).order_by("-count")
    )

    faculty = TeachingStaffProfile.objects.all()
    total_faculty = faculty.count()
    phd_faculty = faculty.filter(has_phd=True).count()
    phd_percent = round(phd_faculty / total_faculty * 100, 2) if total_faculty else None
    ratio = round(total_students / total_faculty, 2) if total_faculty else None

    fee_income_total = FeePayment.objects.filter(
        payment_date__gte=financial_year.start_date, payment_date__lte=financial_year.end_date,
    ).aggregate(total=Sum("amount_paid"))["total"] or 0

    rows = [
        ["Total Students", total_students],
        ["Total Teaching Faculty", total_faculty],
        ["Faculty with PhD", phd_faculty],
        ["Faculty with PhD (%)", phd_percent],
        ["Student : Faculty Ratio", f"{ratio}:1" if ratio else "—"],
        ["Total Fee Income, this FY (₹)", fee_income_total],
        [
            "Library Expenditure, this FY (₹ Lakhs)",
            nirf_entry.library_expenditure_lakhs if nirf_entry else NIRF_ENTRY_NOT_RECORDED,
        ],
    ] + [[f"Students — {r['program__name']}", r["count"]] for r in program_counts]

    return ("TLR — Teaching-Learning and Resources", ["Metric", "Value"], rows)


def _rp_section(nirf_entry):
    if not nirf_entry:
        rows = [["Publications, Patents, Research/Consultancy Income", NIRF_ENTRY_NOT_RECORDED]]
    else:
        rows = [
            ["Publications Count", nirf_entry.publications_count],
            ["Patents Filed", nirf_entry.patents_filed],
            ["Patents Granted", nirf_entry.patents_granted],
            ["Sponsored Research Funding (₹ Lakhs)", nirf_entry.sponsored_research_funding_lakhs],
            ["Consultancy Income (₹ Lakhs)", nirf_entry.consultancy_income_lakhs],
        ]
    return ("RP — Research and Professional Practice", ["Metric", "Value"], rows)


def _go_section(financial_year, nirf_entry):
    applications = PlacementApplication.objects.filter(
        drive__drive_date__gte=financial_year.start_date, drive__drive_date__lte=financial_year.end_date,
    )
    total_applied = applications.count()
    selected = applications.filter(status="Selected")
    total_selected = selected.count()
    placement_percent = round(total_selected / total_applied * 100, 2) if total_applied else None

    offered = [float(a.offered_ctc_lpa) for a in selected if a.offered_ctc_lpa is not None]
    median_ctc = round(median(offered), 2) if offered else None
    average_ctc = round(sum(offered) / len(offered), 2) if offered else None

    rows = [
        ["Students Applied (placement drives this FY)", total_applied],
        ["Students Selected", total_selected],
        ["Placement %", placement_percent],
        ["Median Offered CTC (₹ Lakhs, of records with a recorded offer)", median_ctc],
        ["Average Offered CTC (₹ Lakhs, of records with a recorded offer)", average_ctc],
        [
            "Students Admitted to Higher Studies",
            nirf_entry.students_admitted_higher_studies if nirf_entry else NIRF_ENTRY_NOT_RECORDED,
        ],
        [
            "Students Qualified in Government Exams",
            nirf_entry.students_qualified_govt_exams if nirf_entry else NIRF_ENTRY_NOT_RECORDED,
        ],
    ]
    return ("GO — Graduation Outcomes", ["Metric", "Value"], rows)


def _oi_section(financial_year):
    students = StudentProfile.objects.all()
    total_students = students.count()

    by_gender = list(students.values("gender").annotate(count=Count("id")).order_by("gender"))
    by_category = list(students.values("category").annotate(count=Count("id")).order_by("category"))
    by_state = list(
        students.exclude(permanent_state__isnull=True).exclude(permanent_state="")
        .values("permanent_state").annotate(count=Count("id")).order_by("-count")
    )
    disability_count = students.filter(disability_status=True).count()

    challenged_count = StudentScholarshipRecord.objects.filter(
        financial_year=financial_year,
    ).values("student").distinct().count()
    challenged_percent = round(challenged_count / total_students * 100, 2) if total_students else None

    summary_rows = [
        ["Total Students", total_students],
        ["Students with Disability", disability_count],
        [
            "Students with Government Scholarship (Economically/Socially Challenged) (%)",
            challenged_percent,
        ],
    ]
    summary_rows += [[f"Gender — {r['gender'] or 'Unspecified'}", r["count"]] for r in by_gender]
    summary_rows += [[f"Category — {r['category'] or 'Unspecified'}", r["count"]] for r in by_category]

    state_rows = [[r["permanent_state"], r["count"]] for r in by_state]

    return [
        ("OI — Outreach and Inclusivity (Summary)", ["Metric", "Value"], summary_rows),
        ("OI — Region Diversity (Students by Permanent State)", ["State", "Students"], state_rows),
    ]


def _pr_section():
    return (
        "PR — Perception",
        ["Note"],
        [["Perception is an external peer-survey parameter (academic peers, employers, public perception) "
          "administered directly by NIRF — it is not derivable from any internal system and is intentionally "
          "left blank here rather than estimated."]],
    )


def compile_nirf_report(financial_year, nirf_entry=None):
    """Returns the (heading, header, rows) sections list, ready for
    _accreditation_xlsx_response (see views/compliance.py)."""
    sections = [_tlr_section(financial_year, nirf_entry), _rp_section(nirf_entry), _go_section(financial_year, nirf_entry)]
    sections += _oi_section(financial_year)
    sections.append(_pr_section())
    return sections

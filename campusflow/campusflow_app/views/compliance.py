import io
import zipfile

from django.db.models import Count
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.compliance import (
    ComplianceCertificateType, ComplianceCertificate,
    AccreditationCriterion, EvidenceItem,
)
from ..models.department import Department
from ..models.profile import (
    StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile,
    ManagementProfile, AdministratorProfile, DepartmentHeadProfile,
)
from ..models.academics import Program
from ..serializers import (
    ComplianceCertificateTypeSerializer, ComplianceCertificateSerializer,
    AccreditationCriterionSerializer, EvidenceItemSerializer,
)
from ..permissions import IsSaaSOrCollegeAdmin, IsHMOrAbove


class ComplianceCertificateTypeViewSet(viewsets.ModelViewSet):
    """
    Catalog of certificate categories (UGC Recognition, Fire NOC, AICTE EOA Letter, etc.)
    that populates the upload form's category dropdown. Admin-managed.
    """
    queryset = ComplianceCertificateType.objects.all().order_by('name')
    serializer_class = ComplianceCertificateTypeSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]


class ComplianceCertificateViewSet(viewsets.ModelViewSet):
    """
    The certificate vault itself — the manual "upload document" surface for
    certificates/licenses that can only ever be supplied by the college, never
    generated from system data (UGC recognition, Trust registration, AICTE EOA
    letter, Fire Safety NOC, previous NAAC certificate, etc.).
    """
    queryset = ComplianceCertificate.objects.select_related('certificate_type', 'uploaded_by').all()
    serializer_class = ComplianceCertificateSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


# ─────────────────────────────────────────────
# P5 — Accreditation Reporting Quick Wins
# Pure reporting over data the system already has — no new fields required.
# ─────────────────────────────────────────────

def _accreditation_xlsx_response(filename, sheets):
    """sheets: list of (sheet_title, header, rows) — one tab per section, so a
    single download covers the whole regulatory return instead of one CSV per
    table. Local to this module rather than shared with audit_portal.py's
    export helpers since these reports have a genuinely different shape
    (multi-sheet vs. one flat table per report)."""
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    wb.remove(wb.active)
    for sheet_title, header, rows in sheets:
        ws = wb.create_sheet(title=sheet_title[:31])
        ws.append(header)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        for row in rows:
            ws.append([str(v) if not isinstance(v, (int, float, type(None))) else v for v in row])
        for column_cells in ws.columns:
            max_len = max((len(str(c.value)) for c in column_cells if c.value is not None), default=10)
            ws.column_dimensions[column_cells[0].column_letter].width = min(max_len + 2, 60)

    buffer = io.BytesIO()
    wb.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


class AISHEAnnualReturnView(APIView):
    """AISHE annual return: enrolment by category/gender/disability status,
    staff counts across all role types."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        students = StudentProfile.objects.all()
        by_category = list(students.values("category").annotate(count=Count("id")).order_by("category"))
        by_gender = list(students.values("gender").annotate(count=Count("id")).order_by("gender"))
        by_disability = list(students.values("disability_status").annotate(count=Count("id")).order_by("disability_status"))

        staff_counts = {
            "teaching": TeachingStaffProfile.objects.count(),
            "non_teaching": NonTeachingStaffProfile.objects.count(),
            "management": ManagementProfile.objects.count(),
            "administrator": AdministratorProfile.objects.count(),
            "department_head": DepartmentHeadProfile.objects.count(),
        }

        if (request.query_params.get("export") or "").lower() == "xlsx":
            return _accreditation_xlsx_response(
                "aishe_annual_return.xlsx",
                [
                    ("Enrolment by Category", ["Category", "Count"], [[r["category"], r["count"]] for r in by_category]),
                    ("Enrolment by Gender", ["Gender", "Count"], [[r["gender"], r["count"]] for r in by_gender]),
                    ("Enrolment by Disability", ["Disability Status", "Count"], [[r["disability_status"], r["count"]] for r in by_disability]),
                    ("Staff Counts", ["Role", "Count"], list(staff_counts.items())),
                ],
            )

        return Response({
            "total_students": students.count(),
            "enrolment_by_category": by_category,
            "enrolment_by_gender": by_gender,
            "enrolment_by_disability_status": by_disability,
            "staff_counts": staff_counts,
            "total_staff": sum(staff_counts.values()),
            "total_departments": Department.objects.count(),
        })


class AICTEDisclosureView(APIView):
    """AICTE Mandatory Disclosure + Faculty-Student Ratio report: faculty
    qualifications/experience/designation, formatted to the disclosure template."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        faculty = TeachingStaffProfile.objects.select_related("user", "department").all()
        faculty_rows = [
            {
                "employee_id": f.employee_id,
                "name": f.user.get_full_name() or f.user.username,
                "department": f.department.name if f.department else None,
                "designation": f.designation,
                "qualifications": f.qualifications,
                "experience_years": f.experience_years,
            }
            for f in faculty
        ]

        total_students = StudentProfile.objects.count()
        total_faculty = faculty.count()
        ratio = round(total_students / total_faculty, 2) if total_faculty else None

        programs = Program.objects.select_related("department").filter(is_active=True)
        program_rows = [
            {
                "code": p.code, "name": p.name, "level": p.level,
                "department": p.department.name, "aicte_program_code": p.aicte_program_code,
            }
            for p in programs
        ]

        if (request.query_params.get("export") or "").lower() == "xlsx":
            return _accreditation_xlsx_response(
                "aicte_mandatory_disclosure.xlsx",
                [
                    ("Faculty", ["Employee ID", "Name", "Department", "Designation", "Qualifications", "Experience (yrs)"],
                     [[f["employee_id"], f["name"], f["department"], f["designation"], f["qualifications"], f["experience_years"]] for f in faculty_rows]),
                    ("Programs", ["Code", "Name", "Level", "Department", "AICTE Program Code"],
                     [[p["code"], p["name"], p["level"], p["department"], p["aicte_program_code"]] for p in program_rows]),
                    ("Faculty-Student Ratio", ["Metric", "Value"],
                     [["Total Students", total_students], ["Total Faculty", total_faculty], ["Ratio (Students:Faculty)", ratio]]),
                ],
            )

        return Response({
            "faculty": faculty_rows,
            "total_students": total_students,
            "total_faculty": total_faculty,
            "student_faculty_ratio": ratio,
            "programs": program_rows,
        })


class NAACExtendedProfileView(APIView):
    """NAAC Extended Profile — institution-level counts feeding the IIQA submission."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        programs_by_level = list(Program.objects.filter(is_active=True).values("level").annotate(count=Count("id")))
        counts = {
            "departments": Department.objects.count(),
            "programs": Program.objects.filter(is_active=True).count(),
            "total_students": StudentProfile.objects.count(),
            "total_teaching_staff": TeachingStaffProfile.objects.count(),
            "total_non_teaching_staff": NonTeachingStaffProfile.objects.count(),
            "students_with_disability": StudentProfile.objects.filter(disability_status=True).count(),
        }

        if (request.query_params.get("export") or "").lower() == "xlsx":
            return _accreditation_xlsx_response(
                "naac_extended_profile.xlsx",
                [
                    ("Institution Counts", ["Metric", "Value"], list(counts.items())),
                    ("Programs by Level", ["Level", "Count"], [[r["level"], r["count"]] for r in programs_by_level]),
                ],
            )

        return Response({
            **counts,
            "programs_by_level": programs_by_level,
            "generated_at": timezone.now(),
        })


# ─────────────────────────────────────────────
# P6 — NAAC SSR/AQAR Evidence Workspace
# ─────────────────────────────────────────────

class AccreditationCriterionViewSet(viewsets.ModelViewSet):
    """The NAAC/NBA criteria catalog (Admin/IQAC managed)."""
    queryset = AccreditationCriterion.objects.all()
    serializer_class = AccreditationCriterionSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]


class EvidenceItemViewSet(viewsets.ModelViewSet):
    """
    Draft -> Submitted -> Signed Off workflow: Department Heads/Faculty attach
    evidence (a file, or a pointer at an existing record / Phase-1 certificate
    instead of re-uploading), an IQAC reviewer (Department Head or above)
    signs off per criterion.
    """
    queryset = EvidenceItem.objects.select_related(
        "criterion", "department", "financial_year", "uploaded_by", "signed_off_by", "linked_certificate",
    ).all()
    serializer_class = EvidenceItemSerializer
    permission_classes = [IsAuthenticated, IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        criterion = self.request.query_params.get("criterion")
        financial_year = self.request.query_params.get("financial_year")
        department = self.request.query_params.get("department")
        if criterion:
            qs = qs.filter(criterion_id=criterion)
        if financial_year:
            qs = qs.filter(financial_year_id=financial_year)
        if department:
            qs = qs.filter(department_id=department)
        return qs

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)


class SubmitEvidenceItemView(APIView):
    """POST /api/evidence-items/<int:pk>/submit/ — Draft -> Submitted."""
    permission_classes = [IsAuthenticated, IsNotDemoTenant]

    def post(self, request, pk):
        try:
            item = EvidenceItem.objects.get(pk=pk)
        except EvidenceItem.DoesNotExist:
            return Response({"error": "Evidence item not found."}, status=status.HTTP_404_NOT_FOUND)
        if item.status != EvidenceItem.STATUS_DRAFT:
            return Response({"error": f"Cannot submit an item that is already {item.status}."}, status=status.HTTP_400_BAD_REQUEST)
        item.submit()
        return Response({"message": "Evidence submitted for IQAC review.", "evidence": EvidenceItemSerializer(item).data})


class SignOffEvidenceItemView(APIView):
    """POST /api/evidence-items/<int:pk>/sign-off/ — Submitted -> Signed Off.
    Restricted to Department Head or above, the same bar as other HM-level
    re-approval actions in this codebase (see IsHMOrAbove)."""
    permission_classes = [IsAuthenticated, IsHMOrAbove, IsNotDemoTenant]

    def post(self, request, pk):
        try:
            item = EvidenceItem.objects.get(pk=pk)
        except EvidenceItem.DoesNotExist:
            return Response({"error": "Evidence item not found."}, status=status.HTTP_404_NOT_FOUND)
        if item.status != EvidenceItem.STATUS_SUBMITTED:
            return Response({"error": "Only submitted evidence can be signed off."}, status=status.HTTP_400_BAD_REQUEST)
        item.sign_off(request.user)
        return Response({"message": "Evidence signed off.", "evidence": EvidenceItemSerializer(item).data})


class SSRExportView(APIView):
    """
    Admin export of the full evidence tree as the SSR/AQAR submission package:
    a JSON tree (criterion -> evidence items) for the manifest, plus a ZIP of
    every evidence file, grouped by criterion code.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        financial_year = request.query_params.get("financial_year")
        criteria = AccreditationCriterion.objects.prefetch_related("evidence").all()

        tree = []
        for criterion in criteria:
            items = criterion.evidence.all()
            if financial_year:
                items = items.filter(financial_year_id=financial_year)
            tree.append({
                "criterion": AccreditationCriterionSerializer(criterion).data,
                "evidence": EvidenceItemSerializer(items, many=True).data,
            })

        if (request.query_params.get("export") or "").lower() == "zip":
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
                for criterion in criteria:
                    items = criterion.evidence.all()
                    if financial_year:
                        items = items.filter(financial_year_id=financial_year)
                    for item in items:
                        if item.file:
                            try:
                                zf.writestr(f"{criterion.code}/{item.id}_{item.file.name.split('/')[-1]}", item.file.read())
                            except Exception:
                                continue
            response = HttpResponse(buffer.getvalue(), content_type="application/zip")
            response["Content-Disposition"] = 'attachment; filename="ssr_aqar_evidence_package.zip"'
            return response

        return Response({"criteria": tree})

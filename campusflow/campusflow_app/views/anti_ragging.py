"""
Anti-Ragging undertaking capture (UGC Anti-Ragging Regulations 2009) and its
coverage-by-department report — closes the roadmap's #11 gap: a real
statutory undertaking, collected per student per academic session and
traceable by reference number, plus visibility into who hasn't signed yet
before it becomes an audit finding.

Not gated behind RequiresModule("compliance-center") on the capture side,
for the same reason StatutoryCommittee's complaint/meeting endpoints aren't
(see views/statutory_committee.py): this is a statutory obligation, not a
premium reporting feature. The coverage report *is* gated — like
CommitteeAnnualReportView, it's genuinely compliance-center admin tooling.
"""
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.academics import AcademicYear
from ..models.anti_ragging import AntiRaggingUndertaking
from ..models.profile import StudentProfile
from ..permissions import IsSaaSOrCollegeAdmin, RequiresModule
from ..serializers import AntiRaggingUndertakingSerializer
from ..services.anti_ragging import generate_undertaking_reference_number
# Reused rather than duplicated — same multi-sheet xlsx shape every other
# compliance-center report uses (see views/compliance.py's P5 section).
from .compliance import _accreditation_xlsx_response

COMPLIANCE_ADMIN_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("compliance-center")]


class AntiRaggingUndertakingViewSet(viewsets.ModelViewSet):
    """Admin-recorded: one row per student per academic year, filed at
    admission and again at the start of every session."""
    queryset = AntiRaggingUndertaking.objects.select_related(
        "student__user", "student__department", "academic_year",
    ).all()
    serializer_class = AntiRaggingUndertakingSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        academic_year = self.request.query_params.get("academic_year")
        student = self.request.query_params.get("student")
        department = self.request.query_params.get("department")
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        if student:
            qs = qs.filter(student_id=student)
        if department:
            qs = qs.filter(student__department_id=department)
        return qs

    def _timestamp_extra(self, validated_data, instance=None):
        """Auto-stamp the moment a signature flips to True, mirroring
        StudentConsentGrantView's granted_at handling — the client sends the
        fact, the server is the source of truth for when."""
        now = timezone.now()
        extra = {}
        if validated_data.get("student_acknowledged") and not (
            validated_data.get("student_acknowledged_at") or (instance and instance.student_acknowledged_at)
        ):
            extra["student_acknowledged_at"] = now
        if validated_data.get("parent_acknowledged") and not (
            validated_data.get("parent_acknowledged_at") or (instance and instance.parent_acknowledged_at)
        ):
            extra["parent_acknowledged_at"] = now
        return extra

    def perform_create(self, serializer):
        academic_year = serializer.validated_data.get("academic_year")
        extra = self._timestamp_extra(serializer.validated_data)
        extra["reference_number"] = generate_undertaking_reference_number(academic_year)
        extra["ip_address"] = self.request.META.get("REMOTE_ADDR")
        extra["user_agent"] = (self.request.META.get("HTTP_USER_AGENT") or "")[:500]
        serializer.save(**extra)

    def perform_update(self, serializer):
        extra = self._timestamp_extra(serializer.validated_data, instance=serializer.instance)
        serializer.save(**extra)


class AntiRaggingCoverageReportView(APIView):
    """
    GET /api/compliance-center/reports/anti-ragging-coverage/?academic_year=<id>&export=xlsx
    Per-department breakdown of undertaking status for one academic year:
    fully signed (student + parent), partially signed, and not collected at
    all — the gap this whole phase exists to make visible before an auditor
    finds it first.
    """
    permission_classes = COMPLIANCE_ADMIN_PERMS

    def get(self, request):
        academic_year_id = request.query_params.get("academic_year")
        if not academic_year_id:
            return Response(
                {"error": "academic_year query param is required."}, status=status.HTTP_400_BAD_REQUEST,
            )
        academic_year = AcademicYear.objects.filter(pk=academic_year_id).first()
        if not academic_year:
            return Response({"error": "Academic year not found."}, status=status.HTTP_404_NOT_FOUND)

        undertakings_by_student = {
            row["student_id"]: (row["student_acknowledged"], row["parent_acknowledged"])
            for row in AntiRaggingUndertaking.objects.filter(academic_year=academic_year).values(
                "student_id", "student_acknowledged", "parent_acknowledged",
            )
        }

        dept_stats = {}
        for student in StudentProfile.objects.select_related("department").all():
            dept_name = student.department.name if student.department else "Unassigned"
            stats = dept_stats.setdefault(dept_name, {"total": 0, "covered": 0, "partial": 0, "missing": 0})
            stats["total"] += 1
            record = undertakings_by_student.get(student.id)
            if record is None:
                stats["missing"] += 1
            elif record[0] and record[1]:
                stats["covered"] += 1
            else:
                stats["partial"] += 1

        department_rows = [
            {
                "department": name,
                "total_students": s["total"],
                "covered": s["covered"],
                "partial": s["partial"],
                "missing": s["missing"],
                "coverage_percent": round(100 * s["covered"] / s["total"], 1) if s["total"] else 0,
            }
            for name, s in sorted(dept_stats.items())
        ]

        overall = {
            "total_students": sum(r["total_students"] for r in department_rows),
            "covered": sum(r["covered"] for r in department_rows),
            "partial": sum(r["partial"] for r in department_rows),
            "missing": sum(r["missing"] for r in department_rows),
        }
        overall["coverage_percent"] = (
            round(100 * overall["covered"] / overall["total_students"], 1) if overall["total_students"] else 0
        )

        if (request.query_params.get("export") or "").lower() == "xlsx":
            return _accreditation_xlsx_response(
                "anti_ragging_coverage.xlsx",
                [
                    ("Coverage by Department",
                     ["Department", "Total Students", "Fully Signed", "Partially Signed", "Not Collected", "Coverage %"],
                     [[r["department"], r["total_students"], r["covered"], r["partial"], r["missing"], r["coverage_percent"]]
                      for r in department_rows]),
                    ("Overall", ["Metric", "Value"], list(overall.items())),
                ],
            )

        return Response({
            "academic_year": academic_year.name,
            "departments": department_rows,
            "overall": overall,
        })

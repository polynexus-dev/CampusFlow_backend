"""
University exam administration layer — closes roadmap gap #18.

AttendanceDetentionSettingsView is admin-configuration for the detention
rule; the detention flag itself is surfaced on the student exam list (see
views/exam.py's is_detained addition) rather than through its own endpoint,
mirroring is_clearance_blocked's existing shape exactly.

RevaluationRequest/MigrationRequest/ConvocationRequest each get the same
three-view shape ResultCorrectionRequest already uses (views/result_correction.py):
a create view open to the requesting student, a list view for reviewers, and
an approve/reject action view — duplicated per request type rather than
abstracted, matching that file's own precedent of one explicit view set per
workflow instead of a shared generic base.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.academics import AcademicYear
from ..models.clearance import ClearanceRequest
from ..models.exam_administration import ConvocationRequest, MigrationRequest, RevaluationRequest
from ..models.result import StudentExamResult
from ..permissions import IsHMOrAbove, IsSaaSOrCollegeAdmin, is_college_admin
from ..services.clearance import is_student_cleared
from ..services.detention import get_detention_settings


class AttendanceDetentionSettingsView(APIView):
    """GET/PATCH the tenant's minimum-attendance detention rule."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        settings_row = get_detention_settings()
        return Response({
            "is_enabled": settings_row.is_enabled,
            "minimum_attendance_percent": float(settings_row.minimum_attendance_percent),
            "updated_at": settings_row.updated_at,
        })

    def patch(self, request):
        settings_row = get_detention_settings()
        if "is_enabled" in request.data:
            settings_row.is_enabled = bool(request.data["is_enabled"])
        if "minimum_attendance_percent" in request.data:
            settings_row.minimum_attendance_percent = request.data["minimum_attendance_percent"]
        settings_row.save(update_fields=["is_enabled", "minimum_attendance_percent", "updated_at"])
        return Response({
            "is_enabled": settings_row.is_enabled,
            "minimum_attendance_percent": float(settings_row.minimum_attendance_percent),
            "updated_at": settings_row.updated_at,
        })


# ─────────────────────────────────────────────
# Revaluation
# ─────────────────────────────────────────────

def _serialize_revaluation(req):
    return {
        "id": req.id,
        "result_id": req.result_id,
        "student_name": req.result.student.user.get_full_name() or req.result.student.user.username,
        "exam_name": req.result.exam.name,
        "current_marks": float(req.result.marks_obtained),
        "reason": req.reason,
        "status": req.status,
        "revised_marks": float(req.revised_marks) if req.revised_marks is not None else None,
        "requested_by": req.requested_by.get_full_name() or req.requested_by.username,
        "requested_at": req.requested_at.isoformat(),
    }


class RevaluationRequestCreateView(APIView):
    """POST /api/exam-administration/revaluation-requests/ — {result_id, reason}"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        result_id = request.data.get("result_id")
        reason = (request.data.get("reason") or "").strip()
        if not result_id or not reason:
            return Response({"error": "result_id and reason are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = StudentExamResult.objects.select_related("exam", "student__user").get(id=result_id)
        except StudentExamResult.DoesNotExist:
            return Response({"error": "Result not found."}, status=status.HTTP_404_NOT_FOUND)

        if not result.exam.results_published:
            return Response({"error": "Results for this exam aren't published yet."}, status=status.HTTP_400_BAD_REQUEST)

        if RevaluationRequest.objects.filter(result=result, status=RevaluationRequest.STATUS_PENDING).exists():
            return Response({"error": "A pending revaluation request already exists for this result."}, status=status.HTTP_400_BAD_REQUEST)

        revaluation = RevaluationRequest.objects.create(result=result, requested_by=request.user, reason=reason)
        return Response(_serialize_revaluation(revaluation), status=status.HTTP_201_CREATED)


class RevaluationRequestListView(APIView):
    """GET /api/exam-administration/revaluation-requests/?exam_id= — pending requests,
    department-scoped for a Department Head, unscoped for College/SaaS Admin."""
    permission_classes = [IsAuthenticated, IsHMOrAbove]

    def get(self, request):
        qs = RevaluationRequest.objects.filter(status=RevaluationRequest.STATUS_PENDING).select_related(
            "result__student__user", "result__exam", "requested_by",
        )
        if not is_college_admin(request.user):
            departments = getattr(request.user, "departments_led", None)
            dept_ids = list(departments.values_list("id", flat=True)) if departments is not None else []
            qs = qs.filter(result__exam__department_id__in=dept_ids)

        exam_id = request.query_params.get("exam_id")
        if exam_id:
            qs = qs.filter(result__exam_id=exam_id)
        return Response({"results": [_serialize_revaluation(r) for r in qs.order_by("-requested_at")]})


class RevaluationRequestActionView(APIView):
    """POST /api/exam-administration/revaluation-requests/<id>/action/
    Payload: {action: "approve" | "reject", revised_marks?}
    revised_marks is required on approve — the reviewer's own re-checked mark."""
    permission_classes = [IsAuthenticated, IsHMOrAbove]

    def post(self, request, pk):
        try:
            revaluation = RevaluationRequest.objects.select_related("result__exam", "requested_by").get(pk=pk)
        except RevaluationRequest.DoesNotExist:
            return Response({"error": "Revaluation request not found."}, status=status.HTTP_404_NOT_FOUND)

        if revaluation.status != RevaluationRequest.STATUS_PENDING:
            return Response({"error": "This request has already been reviewed."}, status=status.HTTP_400_BAD_REQUEST)

        action = request.data.get("action")
        if action not in ("approve", "reject"):
            return Response({"error": "action must be 'approve' or 'reject'."}, status=status.HTTP_400_BAD_REQUEST)

        if action == "approve":
            revised_marks = request.data.get("revised_marks")
            if revised_marks is None:
                return Response({"error": "revised_marks is required to approve a revaluation."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                revised_marks = float(revised_marks)
            except (TypeError, ValueError):
                return Response({"error": "revised_marks must be a number."}, status=status.HTTP_400_BAD_REQUEST)

            result = revaluation.result
            result.marks_obtained = revised_marks
            result.save()  # recomputes grade/is_pass via StudentExamResult.save()
            revaluation.revised_marks = revised_marks
            revaluation.status = RevaluationRequest.STATUS_APPROVED
        else:
            revaluation.status = RevaluationRequest.STATUS_REJECTED

        revaluation.reviewed_by = request.user
        revaluation.reviewed_at = timezone.now()
        revaluation.save(update_fields=["status", "revised_marks", "reviewed_by", "reviewed_at"])
        return Response(_serialize_revaluation(revaluation))


# ─────────────────────────────────────────────
# Migration Certificate
# ─────────────────────────────────────────────

def _serialize_migration(req):
    return {
        "id": req.id,
        "student_id": req.student_id,
        "student_name": req.student.user.get_full_name() or req.student.user.username,
        "destination_institution": req.destination_institution,
        "reason": req.reason,
        "status": req.status,
        "certificate_number": req.certificate_number,
        "requested_at": req.requested_at.isoformat(),
    }


class MigrationRequestCreateView(APIView):
    """POST /api/exam-administration/migration-requests/ — {destination_institution, reason?}"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        student_profile = getattr(request.user, "student_profile", None)
        if not student_profile:
            return Response({"error": "Only students can request a migration certificate."}, status=status.HTTP_403_FORBIDDEN)

        destination = (request.data.get("destination_institution") or "").strip()
        if not destination:
            return Response({"error": "destination_institution is required."}, status=status.HTTP_400_BAD_REQUEST)

        migration = MigrationRequest.objects.create(
            student=student_profile, destination_institution=destination,
            reason=(request.data.get("reason") or "").strip(),
        )
        return Response(_serialize_migration(migration), status=status.HTTP_201_CREATED)


class MigrationRequestListView(APIView):
    """GET /api/exam-administration/migration-requests/?status= — Admin only."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        qs = MigrationRequest.objects.select_related("student__user").all()
        status_filter = request.query_params.get("status")
        if status_filter:
            qs = qs.filter(status=status_filter)
        return Response({"results": [_serialize_migration(r) for r in qs.order_by("-requested_at")]})


class MigrationRequestActionView(APIView):
    """
    POST /api/exam-administration/migration-requests/<id>/action/
    Payload: {action: "approve" | "reject", certificate_number?, override?}
    Approval is blocked unless the student is final-exit cleared (no
    outstanding library/hostel/fee dues) — same override escape hatch
    PromoteClassView already uses for the equivalent clearance gate.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def post(self, request, pk):
        try:
            migration = MigrationRequest.objects.select_related("student__user").get(pk=pk)
        except MigrationRequest.DoesNotExist:
            return Response({"error": "Migration request not found."}, status=status.HTTP_404_NOT_FOUND)

        if migration.status != MigrationRequest.STATUS_PENDING:
            return Response({"error": "This request has already been reviewed."}, status=status.HTTP_400_BAD_REQUEST)

        action = request.data.get("action")
        if action not in ("approve", "reject"):
            return Response({"error": "action must be 'approve' or 'reject'."}, status=status.HTTP_400_BAD_REQUEST)

        if action == "approve":
            is_cleared, _ = is_student_cleared(migration.student, cycle_type=ClearanceRequest.CYCLE_FINAL_EXIT)
            if not is_cleared and not request.data.get("override"):
                return Response(
                    {"error": "Student does not have a cleared final-exit clearance request. "
                              "Resend with override=true to approve anyway."},
                    status=status.HTTP_409_CONFLICT,
                )
            migration.certificate_number = (request.data.get("certificate_number") or "").strip()
            migration.status = MigrationRequest.STATUS_APPROVED
        else:
            migration.status = MigrationRequest.STATUS_REJECTED

        migration.reviewed_by = request.user
        migration.reviewed_at = timezone.now()
        migration.save(update_fields=["status", "certificate_number", "reviewed_by", "reviewed_at"])
        return Response(_serialize_migration(migration))


# ─────────────────────────────────────────────
# Convocation
# ─────────────────────────────────────────────

def _serialize_convocation(req):
    return {
        "id": req.id,
        "student_id": req.student_id,
        "student_name": req.student.user.get_full_name() or req.student.user.username,
        "academic_year_id": req.academic_year_id,
        "academic_year_name": req.academic_year.name,
        "remarks": req.remarks,
        "status": req.status,
        "requested_at": req.requested_at.isoformat(),
    }


class ConvocationRequestCreateView(APIView):
    """POST /api/exam-administration/convocation-requests/ — {academic_year_id, remarks?}"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        student_profile = getattr(request.user, "student_profile", None)
        if not student_profile:
            return Response({"error": "Only students can register for convocation."}, status=status.HTTP_403_FORBIDDEN)

        academic_year = AcademicYear.objects.filter(pk=request.data.get("academic_year_id")).first()
        if not academic_year:
            return Response({"error": "A valid academic_year_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        if ConvocationRequest.objects.filter(student=student_profile, academic_year=academic_year).exists():
            return Response({"error": "A convocation request already exists for this student/year."}, status=status.HTTP_400_BAD_REQUEST)

        convocation = ConvocationRequest.objects.create(
            student=student_profile, academic_year=academic_year,
            remarks=(request.data.get("remarks") or "").strip(),
        )
        return Response(_serialize_convocation(convocation), status=status.HTTP_201_CREATED)


class ConvocationRequestListView(APIView):
    """GET /api/exam-administration/convocation-requests/?status=&academic_year= — Admin only."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        qs = ConvocationRequest.objects.select_related("student__user", "academic_year").all()
        status_filter = request.query_params.get("status")
        academic_year_id = request.query_params.get("academic_year")
        if status_filter:
            qs = qs.filter(status=status_filter)
        if academic_year_id:
            qs = qs.filter(academic_year_id=academic_year_id)
        return Response({"results": [_serialize_convocation(r) for r in qs.order_by("-requested_at")]})


class ConvocationRequestActionView(APIView):
    """
    POST /api/exam-administration/convocation-requests/<id>/action/
    Payload: {action: "approve" | "reject", override?}
    Same final-exit clearance gate as MigrationRequestActionView.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def post(self, request, pk):
        try:
            convocation = ConvocationRequest.objects.select_related("student__user", "academic_year").get(pk=pk)
        except ConvocationRequest.DoesNotExist:
            return Response({"error": "Convocation request not found."}, status=status.HTTP_404_NOT_FOUND)

        if convocation.status != ConvocationRequest.STATUS_PENDING:
            return Response({"error": "This request has already been reviewed."}, status=status.HTTP_400_BAD_REQUEST)

        action = request.data.get("action")
        if action not in ("approve", "reject"):
            return Response({"error": "action must be 'approve' or 'reject'."}, status=status.HTTP_400_BAD_REQUEST)

        if action == "approve":
            is_cleared, _ = is_student_cleared(convocation.student, cycle_type=ClearanceRequest.CYCLE_FINAL_EXIT)
            if not is_cleared and not request.data.get("override"):
                return Response(
                    {"error": "Student does not have a cleared final-exit clearance request. "
                              "Resend with override=true to approve anyway."},
                    status=status.HTTP_409_CONFLICT,
                )
            convocation.status = ConvocationRequest.STATUS_APPROVED
        else:
            convocation.status = ConvocationRequest.STATUS_REJECTED

        convocation.reviewed_by = request.user
        convocation.reviewed_at = timezone.now()
        convocation.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        return Response(_serialize_convocation(convocation))

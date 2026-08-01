"""
Result Correction Requests
==========================
A TEACHER requesting to change a student's marks after the parent exam's
results have been published. Requires HM (Department Head or above)
approval — distinct from the pre-publish direct-edit path on
StudentExamResultViewSet.
"""

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import ResultCorrectionRequest, StudentExamResult
from ..permissions import IsFacultyOrAbove, IsHMOrAbove, is_college_admin
from ..services.notifications import notify_user, notify_guardians_of_student


def _serialize(req):
    return {
        "id": req.id,
        "result_id": req.result_id,
        "student_name": req.result.student.user.get_full_name() or req.result.student.user.username,
        "exam_name": req.result.exam.name,
        "current_marks": float(req.result.marks_obtained),
        "proposed_marks": float(req.proposed_marks),
        "reason": req.reason,
        "status": req.status,
        "requested_by": req.requested_by.get_full_name() or req.requested_by.username,
        "requested_at": req.requested_at.isoformat(),
    }


class ResultCorrectionRequestCreateView(APIView):
    """
    POST /api/results/corrections/
    Payload: {result_id, proposed_marks, reason}
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def post(self, request):
        result_id = request.data.get("result_id")
        proposed_marks = request.data.get("proposed_marks")
        reason = (request.data.get("reason") or "").strip()

        if not result_id or proposed_marks is None or not reason:
            return Response({"error": "result_id, proposed_marks, and reason are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = StudentExamResult.objects.select_related("exam", "student__user").get(id=result_id)
        except StudentExamResult.DoesNotExist:
            return Response({"error": "Result not found."}, status=status.HTTP_404_NOT_FOUND)

        if not result.exam.results_published:
            return Response({"error": "This exam's results aren't published yet — edit the result directly instead."}, status=status.HTTP_400_BAD_REQUEST)

        if ResultCorrectionRequest.objects.filter(result=result, status=ResultCorrectionRequest.STATUS_PENDING).exists():
            return Response({"error": "A pending correction request already exists for this result."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            proposed_marks = float(proposed_marks)
        except (TypeError, ValueError):
            return Response({"error": "proposed_marks must be a number."}, status=status.HTTP_400_BAD_REQUEST)

        correction = ResultCorrectionRequest.objects.create(
            result=result, requested_by=request.user, proposed_marks=proposed_marks, reason=reason,
        )
        return Response(_serialize(correction), status=status.HTTP_201_CREATED)


class HMCorrectionRequestListView(APIView):
    """
    GET /api/results/corrections/?exam_id=
    Pending correction requests, scoped to the HM's own department when
    they're a Department Head, or all for College Admin/SaaS Admin.
    """
    permission_classes = [IsAuthenticated, IsHMOrAbove]

    def get(self, request):
        qs = ResultCorrectionRequest.objects.filter(
            status=ResultCorrectionRequest.STATUS_PENDING
        ).select_related("result__student__user", "result__exam", "requested_by")

        if not is_college_admin(request.user):
            department = getattr(request.user, "departments_led", None)
            dept_ids = list(department.values_list("id", flat=True)) if department is not None else []
            qs = qs.filter(result__exam__department_id__in=dept_ids)

        exam_id = request.query_params.get("exam_id")
        if exam_id:
            qs = qs.filter(result__exam_id=exam_id)

        return Response({"results": [_serialize(r) for r in qs.order_by("-requested_at")]}, status=status.HTTP_200_OK)


class HMCorrectionRequestActionView(APIView):
    """
    POST /api/results/corrections/<id>/action/
    Payload: {action: "approve" | "reject"}
    """
    permission_classes = [IsAuthenticated, IsHMOrAbove]

    def post(self, request, pk):
        try:
            correction = ResultCorrectionRequest.objects.select_related(
                "result__student__user", "result__exam", "requested_by"
            ).get(pk=pk)
        except ResultCorrectionRequest.DoesNotExist:
            return Response({"error": "Correction request not found."}, status=status.HTTP_404_NOT_FOUND)

        if correction.status != ResultCorrectionRequest.STATUS_PENDING:
            return Response({"error": "This request has already been reviewed."}, status=status.HTTP_400_BAD_REQUEST)

        action = request.data.get("action")
        if action not in ("approve", "reject"):
            return Response({"error": "action must be 'approve' or 'reject'."}, status=status.HTTP_400_BAD_REQUEST)

        result = correction.result

        if action == "approve":
            result.marks_obtained = correction.proposed_marks
            result.save()  # recomputes grade/is_pass via StudentExamResult.save()
            correction.status = ResultCorrectionRequest.STATUS_APPROVED
            teacher_title = f"Marks correction approved: {result.exam.name}"
            teacher_body = f"{result.student.user.get_full_name()} · marks updated to {result.marks_obtained}"
            notify_guardians_of_student(
                result.student,
                title=f"Marks updated: {result.exam.name}",
                body=f"{result.exam.course.course_name} · {result.marks_obtained}/{result.exam.total_marks} · Grade {result.grade}",
                category="marks_corrected",
                data={"exam_id": result.exam_id, "result_id": result.id},
            )
        else:
            correction.status = ResultCorrectionRequest.STATUS_REJECTED
            teacher_title = f"Marks correction rejected: {result.exam.name}"
            teacher_body = f"{result.student.user.get_full_name()} · request rejected"

        correction.reviewed_by = request.user
        correction.reviewed_at = timezone.now()
        correction.save(update_fields=["status", "reviewed_by", "reviewed_at"])

        notify_user(
            correction.requested_by,
            title=teacher_title,
            body=teacher_body,
            category="marks_correction_review",
            data={"correction_request_id": correction.id, "status": correction.status},
        )

        return Response(_serialize(correction), status=status.HTTP_200_OK)

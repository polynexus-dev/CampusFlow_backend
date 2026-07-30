"""
Attendance Correction Requests
==============================
A GUARDIAN disputes a student's marked-absent lecture; a teacher/HM
approves it to Present, rejects it, or marks it Half Day. Distinct from
the student-initiated ManualAttendanceRequest (views/lecturer_attendance.py).
"""

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import (
    AttendanceCorrectionRequest, StudentProfile, Lecture, Attendance, FaceAttendanceLog,
)
from ..permissions import IsFacultyOrAbove, is_college_admin
from ..services.notifications import notify_user


def _serialize_request(req):
    log = FaceAttendanceLog.objects.filter(student=req.student, lecture=req.lecture).first()
    system_check = None
    if log:
        system_check = {
            "attempted": True,
            "verified": log.is_verified,
            "confidence_score": log.confidence_score,
            "timestamp": log.timestamp.isoformat(),
        }

    return {
        "id": req.id,
        "student_id": req.student_id,
        "student_name": req.student.user.get_full_name() or req.student.user.username,
        "lecture_id": req.lecture_id,
        "lecture_name": req.lecture.name,
        "lecture_date": req.lecture.start_time.date().isoformat(),
        "reason": req.reason,
        "status": req.status,
        "requested_at": req.requested_at.isoformat(),
        "system_check": system_check,
    }


class GuardianCreateCorrectionRequestView(APIView):
    """
    POST /api/attendance/corrections/
    Payload: {student_id, lecture_id, reason}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        guardian_profile = getattr(request.user, "guardian_profile", None)
        student_id = request.data.get("student_id")
        lecture_id = request.data.get("lecture_id")
        reason = (request.data.get("reason") or "").strip()

        if not guardian_profile or not guardian_profile.students.filter(id=student_id).exists():
            return Response({"error": "Access denied or student not linked to this guardian."}, status=status.HTTP_403_FORBIDDEN)

        if not lecture_id or not reason:
            return Response({"error": "lecture_id and reason are required."}, status=status.HTTP_400_BAD_REQUEST)

        student = StudentProfile.objects.get(id=student_id)

        try:
            lecture = Lecture.objects.get(id=lecture_id)
        except Lecture.DoesNotExist:
            return Response({"error": "Lecture not found."}, status=status.HTTP_404_NOT_FOUND)

        if Attendance.objects.filter(user=student.user, lecture=lecture).exists():
            return Response({"error": "This student is already marked present for this lecture."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            correction = AttendanceCorrectionRequest.objects.create(
                student=student, lecture=lecture, requested_by=request.user, reason=reason,
            )
        except IntegrityError:
            return Response({"error": "A correction request already exists for this student and lecture."}, status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_request(correction), status=status.HTTP_201_CREATED)


class TeacherCorrectionRequestListView(APIView):
    """
    GET /api/attendance/corrections/?lecture_id=
    Pending correction requests for lectures the requesting faculty teaches
    (or all, for College Admins), with a system_check cross-reference built
    from the FaceAttendanceLog for that (student, lecture).
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request):
        qs = AttendanceCorrectionRequest.objects.filter(
            status=AttendanceCorrectionRequest.STATUS_PENDING
        ).select_related("student__user", "lecture")

        if not is_college_admin(request.user):
            qs = qs.filter(lecture__faculty=request.user)

        lecture_id = request.query_params.get("lecture_id")
        if lecture_id:
            qs = qs.filter(lecture_id=lecture_id)

        return Response(
            {"results": [_serialize_request(r) for r in qs.order_by("-requested_at")]},
            status=status.HTTP_200_OK,
        )


class TeacherCorrectionRequestActionView(APIView):
    """
    POST /api/attendance/corrections/<id>/action/
    Payload: {action: "approve" | "reject" | "half_day"}
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def post(self, request, pk):
        try:
            correction = AttendanceCorrectionRequest.objects.select_related("student__user", "lecture").get(pk=pk)
        except AttendanceCorrectionRequest.DoesNotExist:
            return Response({"error": "Correction request not found."}, status=status.HTTP_404_NOT_FOUND)

        if correction.status != AttendanceCorrectionRequest.STATUS_PENDING:
            return Response({"error": "This request has already been reviewed."}, status=status.HTTP_400_BAD_REQUEST)

        if not is_college_admin(request.user) and correction.lecture.faculty_id != request.user.id:
            return Response({"error": "You are not the faculty for this lecture."}, status=status.HTTP_403_FORBIDDEN)

        action = request.data.get("action")
        if action not in ("approve", "reject", "half_day"):
            return Response({"error": "action must be 'approve', 'reject', or 'half_day'."}, status=status.HTTP_400_BAD_REQUEST)

        student_user = correction.student.user
        lecture = correction.lecture

        if action == "approve":
            Attendance.objects.get_or_create(
                user=student_user, lecture=lecture,
                defaults={"verification_method": "manual", "device_id": "Guardian Correction Approved"},
            )
            correction.status = AttendanceCorrectionRequest.STATUS_APPROVED
            notify_title = f"Attendance correction approved for {student_user.get_full_name() or student_user.username}"
            notify_body = f"{lecture.name} · marked Present"
        elif action == "half_day":
            Attendance.objects.get_or_create(
                user=student_user, lecture=lecture,
                defaults={"verification_method": "manual", "device_id": "Guardian Correction Approved (Half Day)", "is_half_day": True},
            )
            correction.status = AttendanceCorrectionRequest.STATUS_HALF_DAY
            notify_title = f"Attendance correction marked Half Day for {student_user.get_full_name() or student_user.username}"
            notify_body = f"{lecture.name} · marked Half Day"
        else:
            correction.status = AttendanceCorrectionRequest.STATUS_REJECTED
            notify_title = f"Attendance correction rejected for {student_user.get_full_name() or student_user.username}"
            notify_body = f"{lecture.name} · request rejected"

        correction.reviewed_by = request.user
        correction.reviewed_at = timezone.now()
        correction.save(update_fields=["status", "reviewed_by", "reviewed_at"])

        notify_user(
            correction.requested_by,
            title=notify_title,
            body=notify_body,
            category="attendance_correction",
            data={"correction_request_id": correction.id, "status": correction.status},
        )

        return Response(_serialize_request(correction), status=status.HTTP_200_OK)

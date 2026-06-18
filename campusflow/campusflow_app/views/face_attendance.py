import logging
import secrets
import numpy as np
from django.core.cache import cache
from django.db import transaction
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..face_utils import (
    basic_liveness_check,
    check_frame_motion,
    check_head_motion,
    compare_embeddings,
    extract_embedding,
    extract_embedding_with_pose,
)
from ..models.face_embedding import FaceEmbedding
from ..models.attendance_log import FaceAttendanceLog
from ..models.lecture import Lecture
from ..models.attendance import Attendance
from ..models.profile import StudentProfile
from ..serializers import (
    FaceRegistrationSerializer,
    MarkAttendanceSerializer,
    FaceAttendanceLogSerializer,
    AttendanceResultSerializer,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────────────────
# Permissions
# ──────────────────────────────────────────────────────────────────────────────
class IsStudent(permissions.BasePermission):
    """Allow access only to users with a student profile."""

    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and hasattr(request.user, "student_profile")
        )


# ──────────────────────────────────────────────────────────────────────────────
# Face Registration (3-Angle Upload)
# ──────────────────────────────────────────────────────────────────────────────
class FaceRegistrationView(APIView):
    """
    POST /api/register-face/

    Accept three face images (front, left, right), extract ArcFace
    embeddings, and store them in the database.
    """

    permission_classes = [IsStudent]

    @transaction.atomic
    def post(self, request):
        serializer = FaceRegistrationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            student = request.user.student_profile
        except StudentProfile.DoesNotExist:
            return Response(
                {"error": "Student profile not found. Please register profile first."},
                status=status.HTTP_404_NOT_FOUND,
            )

        angles = ["front", "left", "right"]
        results = {}
        errors = []

        for angle in angles:
            image_file = serializer.validated_data[angle]
            image_bytes = image_file.read()

            try:
                embedding, yaw, pitch, roll = extract_embedding_with_pose(image_bytes)
            except ValueError as e:
                errors.append({"angle": angle, "error": str(e)})
                continue

            if yaw is not None:
                logger.info(
                    "POSE LOG | angle=%-5s | yaw=%+6.1f° pitch=%+5.1f° roll=%+5.1f°",
                    angle, yaw, pitch or 0.0, roll or 0.0,
                )

            FaceEmbedding.objects.update_or_create(
                student=student,
                angle=angle,
                defaults={"embedding": embedding.tolist()},
            )
            results[angle] = "✓ Embedding stored"

        if errors:
            # transaction.atomic rolls back database updates if view returns error status
            transaction.set_rollback(True)
            return Response(
                {
                    "error": "Face registration partially failed.",
                    "details": errors,
                    "successful": results,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        student.is_face_registered = True
        student.save(update_fields=["is_face_registered"])

        logger.info(
            "Face registration complete for student %s (user_id=%d)",
            student.student_id,
            request.user.id,
        )

        return Response(
            {
                "message": "Face registration successful. All 3 angles stored.",
                "angles": results,
            },
            status=status.HTTP_201_CREATED,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Liveness Challenge
# ──────────────────────────────────────────────────────────────────────────────
_CHALLENGE_TYPES = ["blink", "nod", "turn_left", "turn_right"]
_CHALLENGE_TTL   = 300  # seconds (5 minutes)


class LivenessChallengeView(APIView):
    """
    GET /api/liveness-challenge/

    Issue a random, single-use liveness challenge for the upcoming attendance capture.
    """

    permission_classes = [IsStudent]

    def get(self, request):
        challenge_type = secrets.choice(_CHALLENGE_TYPES)
        challenge_id   = secrets.token_urlsafe(32)
        cache.set(f"liveness:{challenge_id}", challenge_type, timeout=_CHALLENGE_TTL)

        logger.info(
            "Liveness challenge issued — student=%s, type=%s, id=%s",
            request.user.student_profile.student_id,
            challenge_type,
            challenge_id,
        )
        return Response({"challenge_id": challenge_id, "challenge_type": challenge_type})


# ──────────────────────────────────────────────────────────────────────────────
# Attendance Verification
# ──────────────────────────────────────────────────────────────────────────────
class MarkAttendanceView(APIView):
    """
    POST /api/mark-attendance/

    Accept a live selfie photo and lecture ID. Extract the face embedding,
    run liveness checks, compare against stored embeddings, and record
    the attendance log.
    """

    permission_classes = [IsStudent]

    def post(self, request):
        serializer = MarkAttendanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        lecture_id        = serializer.validated_data["lecture_id"]
        photo             = serializer.validated_data["photo"]
        photo_bytes       = photo.read()
        photo_prev        = serializer.validated_data.get("photo_prev")
        photo_prev_bytes  = photo_prev.read() if photo_prev else None
        challenge_id      = serializer.validated_data["challenge_id"]

        # ── Validate student profile ──────────────────────────────────────
        try:
            student = request.user.student_profile
        except StudentProfile.DoesNotExist:
            return Response(
                {"error": "Student profile not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if not student.is_face_registered:
            return Response(
                {"error": "Face not registered. Please complete face registration first."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Validate lecture ──────────────────────────────────────────────
        try:
            lecture = Lecture.objects.get(id=lecture_id)
        except Lecture.DoesNotExist:
            return Response(
                {"error": "Lecture not found."},
                status=status.HTTP_404_NOT_FOUND,
            )

        # ── Check for duplicate attendance ─────────────────────────────────
        if Attendance.objects.filter(user=request.user, lecture=lecture).exists():
            return Response(
                {"error": "Attendance already marked for this lecture."},
                status=status.HTTP_409_CONFLICT,
            )

        # ── Step 1: Liveness check ────────────────────────────────────────
        liveness_passed, liveness_msg = basic_liveness_check(photo_bytes)

        if not liveness_passed:
            logger.warning(
                "Liveness FAILED — student=%s, lecture=%d, reason=%s",
                student.student_id, lecture.id, liveness_msg,
            )
            return Response(
                {
                    "success": False,
                    "is_verified": False,
                    "confidence_score": 0.0,
                    "liveness_passed": False,
                    "message": f"Liveness check failed: {liveness_msg}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Step 2: Validate challenge token (single-use) ────────────────
        challenge_type = cache.get(f"liveness:{challenge_id}")
        if not challenge_type:
            logger.warning(
                "CHALLENGE INVALID — student=%s, challenge_id=%s",
                student.student_id, challenge_id,
            )
            return Response(
                {
                    "success": False,
                    "is_verified": False,
                    "confidence_score": 0.0,
                    "liveness_passed": False,
                    "message": "Liveness challenge expired or already used. Please try again.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )
        cache.delete(f"liveness:{challenge_id}")

        # ── Step 3: Motion liveness (two-frame comparison) ───────────────
        if not photo_prev_bytes:
            logger.warning(
                "MOTION FAIL — no photo_prev received for student=%s.",
                student.student_id,
            )
            return Response(
                {
                    "success": False,
                    "is_verified": False,
                    "confidence_score": 0.0,
                    "liveness_passed": False,
                    "message": "Liveness check failed: Baseline photo is required for verification.",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            if challenge_type == "blink":
                motion_ok, motion_score, motion_msg = check_frame_motion(
                    photo_prev_bytes, photo_bytes
                )
            else:
                motion_ok, motion_score, motion_msg = check_head_motion(
                    photo_prev_bytes, photo_bytes, challenge_type,
                )
        except ValueError as e:
            motion_ok, motion_score, motion_msg = False, 0.0, str(e)

        if not motion_ok:
            logger.warning(
                "Motion liveness FAILED — student=%s, lecture=%d, reason=%s",
                student.student_id, lecture.id, motion_msg,
            )
            return Response(
                {
                    "success": False,
                    "is_verified": False,
                    "confidence_score": 0.0,
                    "liveness_passed": False,
                    "message": f"Liveness check failed: {motion_msg}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        logger.info(
            "Motion liveness OK — student=%s, challenge=%s, score=%.3f",
            student.student_id, challenge_type, motion_score,
        )

        # ── Step 4: Extract live embedding ────────────────────────────────
        try:
            live_embedding = extract_embedding(photo_bytes)
        except ValueError as e:
            return Response(
                {"error": str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Step 5: Retrieve stored embeddings ────────────────────────────
        stored_records = FaceEmbedding.objects.filter(student=student)
        stored_embeddings = [
            np.array(record.embedding, dtype=np.float32)
            for record in stored_records
        ]

        if not stored_embeddings:
            return Response(
                {"error": "No stored face embeddings found. Please re-register."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Step 6: Compare embeddings ────────────────────────────────────
        is_match, best_score = compare_embeddings(live_embedding, stored_embeddings)

        # ── Step 7: Record result ─────────────────────────────────────────
        is_verified = is_match and liveness_passed

        FaceAttendanceLog.objects.update_or_create(
            student=student,
            lecture=lecture,
            defaults={
                "confidence_score": best_score,
                "is_verified": is_verified,
                "liveness_passed": liveness_passed,
            },
        )

        if is_verified:
            # Also create standard attendance check-in record
            device_id = request.data.get("device_id") or "Face Verification"
            Attendance.objects.get_or_create(
                user=request.user,
                lecture=lecture,
                defaults={
                    "device_id": device_id,
                    "is_geofence_valid": True,
                    "attendance_type": "lecture_attendance"
                }
            )

            message = f"Attendance verified successfully (confidence: {best_score:.2%})."
            resp_status = status.HTTP_200_OK
        else:
            message = (
                f"Face verification failed (confidence: {best_score:.2%}). "
                "The photo does not match the registered face."
            )
            resp_status = status.HTTP_400_BAD_REQUEST

        logger.info(
            "Attendance attempt — student=%s, lecture=%d, verified=%s, score=%.4f",
            student.student_id,
            lecture.id,
            is_verified,
            best_score,
        )

        result = AttendanceResultSerializer(
            {
                "success": is_verified,
                "is_verified": is_verified,
                "confidence_score": best_score,
                "liveness_passed": liveness_passed,
                "message": message,
            }
        )
        return Response(result.data, status=resp_status)


# ──────────────────────────────────────────────────────────────────────────────
# Attendance History
# ──────────────────────────────────────────────────────────────────────────────
class AttendanceHistoryView(generics.ListAPIView):
    """
    GET /api/attendance-history/

    Return the authenticated student's attendance verification history logs.
    """

    serializer_class = FaceAttendanceLogSerializer
    permission_classes = [IsStudent]

    def get_queryset(self):
        student = self.request.user.student_profile
        return FaceAttendanceLog.objects.filter(student=student).select_related(
            "lecture", "student__user"
        )

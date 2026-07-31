import base64
import logging
import secrets
import numpy as np
from celery.exceptions import TimeoutError as CeleryTimeoutError
from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone
from django.shortcuts import get_object_or_404
from datetime import timedelta
from ..demo_guard import is_demo_tenant
from ..models.attendance_session import AttendanceSession
from ..models.manual_attendance_request import ManualAttendanceRequest
from rest_framework import generics, permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from django.conf import settings as django_settings

from ..face_utils import (
    blend_embedding,
    compare_embeddings,
    extract_embedding_with_pose,
)
from ..tasks import run_face_pipeline
from ..models.face_embedding import FaceEmbedding, FaceEmbeddingSample
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
        # ── Enforce Biometric Consent Check under DPDP Act ──
        consent_given = request.data.get("biometric_consent_given")
        if consent_given not in [True, "true", "True", 1, "1"]:
            return Response(
                {"error": "Biometric consent is required under the DPDP Act, 2023 to enroll and process face templates."},
                status=status.HTTP_400_BAD_REQUEST
            )

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

        # ── Log the explicit Biometric Consent event ──
        from ..models.face_embedding import BiometricConsentLog
        from ipware import get_client_ip
        ip_addr, _ = get_client_ip(request)
        BiometricConsentLog.objects.create(
            student=student,
            consent_given=True,
            consent_version="v1.0",
            ip_address=ip_addr,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500]
        )

        logger.info(
            "Face registration complete and consent logged for student %s (user_id=%d)",
            student.student_id,
            request.user.id,
        )

        return Response(
            {
                "message": "Face registration successful. All 3 angles stored and biometric consent logged.",
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

        # ── Validate active session window (Bypassed for Demo Tenant) ───────
        is_demo = is_demo_tenant() or connection.schema_name == 'demo'

        if not is_demo:
            session = AttendanceSession.objects.filter(lecture=lecture).first()
            if not session or not session.is_active:
                return Response(
                    {"error": "Attendance window is not active. Please wait for the lecturer to start the attendance period."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            elapsed = timezone.now() - session.started_at
            limit = timedelta(minutes=session.duration_minutes)
            if elapsed > limit:
                session.is_active = False
                session.save()
                return Response(
                    {"error": "Attendance window has expired. Please request manual attendance from the lecturer."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ── Check for duplicate attendance ─────────────────────────────────
        if Attendance.objects.filter(user=request.user, lecture=lecture).exists():
            return Response(
                {"error": "Attendance already marked for this lecture."},
                status=status.HTTP_409_CONFLICT,
            )

        # ── Step 1: Validate challenge token (single-use) ─────────────────
        # Consumed up front (before the CPU pipeline runs) so a single
        # challenge can't be replayed across retries — this already matched
        # the pre-existing behavior for motion-check failures, so client
        # retry flows already fetch a fresh challenge after any failed
        # attempt.
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

        # ── Step 2: Liveness + motion + embedding extraction ──────────────
        # Runs as one Celery task on a separate worker pool instead of
        # inline on this request thread — this is the CPU-bound (InsightFace
        # inference) part of the pipeline, and the thing most likely to back
        # up under a morning attendance-rush burst. The HTTP contract is
        # unchanged: we still block for the result, just off-process.
        photo_b64 = base64.b64encode(photo_bytes).decode("ascii")
        photo_prev_b64 = base64.b64encode(photo_prev_bytes).decode("ascii") if photo_prev_bytes else None
        try:
            pipeline_result = run_face_pipeline.delay(
                photo_b64, photo_prev_b64, challenge_type,
            ).get(timeout=django_settings.FACE_PIPELINE_TASK_TIMEOUT)
        except CeleryTimeoutError:
            logger.error(
                "Face pipeline task timed out — student=%s, lecture=%d",
                student.student_id, lecture.id,
            )
            return Response(
                {
                    "success": False,
                    "is_verified": False,
                    "confidence_score": 0.0,
                    "liveness_passed": False,
                    "message": (
                        "Attendance verification is taking longer than usual due to "
                        "high load. Please try again, or ask your lecturer to mark "
                        "you manually."
                    ),
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        if not pipeline_result["liveness_passed"]:
            logger.warning(
                "Liveness FAILED — student=%s, lecture=%d, reason=%s",
                student.student_id, lecture.id, pipeline_result["liveness_msg"],
            )
            return Response(
                {
                    "success": False,
                    "is_verified": False,
                    "confidence_score": 0.0,
                    "liveness_passed": False,
                    "message": f"Liveness check failed: {pipeline_result['liveness_msg']}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not pipeline_result["motion_ok"]:
            logger.warning(
                "Motion liveness FAILED — student=%s, lecture=%d, reason=%s",
                student.student_id, lecture.id, pipeline_result["motion_msg"],
            )
            return Response(
                {
                    "success": False,
                    "is_verified": False,
                    "confidence_score": 0.0,
                    "liveness_passed": False,
                    "message": f"Liveness check failed: {pipeline_result['motion_msg']}",
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        motion_score = pipeline_result.get("motion_score", 0.0)
        logger.info(
            "Motion liveness OK — student=%s, challenge=%s, score=%.3f",
            student.student_id, challenge_type, motion_score,
        )

        if pipeline_result["embedding_error"]:
            return Response(
                {"error": pipeline_result["embedding_error"]},
                status=status.HTTP_400_BAD_REQUEST,
            )

        live_embedding = np.array(pipeline_result["embedding"], dtype=np.float32)

        # ── Step 5: Retrieve stored embeddings ────────────────────────────
        stored_records = list(FaceEmbedding.objects.filter(student=student))
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
        is_match, best_score, best_index = compare_embeddings(live_embedding, stored_embeddings)

        # ── Step 7: Record result ─────────────────────────────────────────
        is_verified = is_match  # liveness/motion already confirmed above (else we'd have returned)

        # ── Step 7b: Adaptive template learning ───────────────────────────
        # Only very confident, already-verified matches are allowed to nudge
        # the stored template — this bounds how much any single capture can
        # move it and keeps a spoofed/borderline match from poisoning it.
        if is_verified and django_settings.FACE_ADAPTIVE_LEARNING_ENABLED:
            self._adapt_template(
                stored_records[best_index], live_embedding, best_score, student,
            )

        with transaction.atomic():
            FaceAttendanceLog.objects.update_or_create(
                student=student,
                lecture=lecture,
                defaults={
                    "confidence_score": best_score,
                    "is_verified": is_verified,
                    "liveness_passed": True,
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
                        "verification_method": "face_geofence"
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
                "liveness_passed": True,
                "message": message,
            }
        )
        return Response(result.data, status=resp_status)

    @staticmethod
    def _adapt_template(matched_record, live_embedding, confidence_score, student):
        """
        Real-time adaptive learning step, run after a verified, high-confidence
        attendance match.

        1. If confidence >= FACE_ADAPTIVE_LEARNING_THRESHOLD, nudge the matched
           FaceEmbedding via a small, bounded EMA blend (alpha shrinks as
           sample_count grows, so the template converges rather than drifting
           indefinitely toward whatever was captured most recently).
        2. Always persist a FaceEmbeddingSample for this capture so the monthly
           fine_tune_face_embeddings command has raw material for a more
           robust, outlier-rejecting consolidation later.
        """
        threshold = django_settings.FACE_ADAPTIVE_LEARNING_THRESHOLD
        if confidence_score < threshold:
            return

        try:
            max_alpha = django_settings.FACE_ADAPTIVE_LEARNING_MAX_ALPHA
            alpha = min(max_alpha, 1.0 / (matched_record.sample_count + 1))

            old_embedding = np.array(matched_record.embedding, dtype=np.float32)
            new_embedding = blend_embedding(old_embedding, live_embedding, alpha)

            matched_record.embedding = new_embedding.tolist()
            matched_record.sample_count += 1
            matched_record.save(update_fields=["embedding", "sample_count", "updated_at"])

            logger.info(
                "Adaptive template update — student=%s, angle=%s, alpha=%.3f, "
                "sample_count=%d, confidence=%.4f",
                student.student_id, matched_record.angle, alpha,
                matched_record.sample_count, confidence_score,
            )
        except Exception:
            # Adaptive learning is a best-effort enhancement — never fail
            # attendance marking because of it.
            logger.exception(
                "Adaptive template update failed — student=%s, angle=%s",
                student.student_id, matched_record.angle,
            )

        try:
            FaceEmbeddingSample.objects.create(
                student=student,
                angle=matched_record.angle,
                embedding=live_embedding.tolist(),
                confidence_score=confidence_score,
            )
        except Exception:
            logger.exception(
                "Failed to persist FaceEmbeddingSample — student=%s", student.student_id,
            )


# ──────────────────────────────────────────────────────────────────────────────
# Attendance History
# ──────────────────────────────────────────────────────────────────────────────
class AttendanceHistoryView(generics.ListAPIView):
    """
    GET /api/attendance-history/

    Return the student's attendance verification history logs.
    """

    serializer_class = FaceAttendanceLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user

        # Cap unbounded growth by default (mirrors AuditLogListView /
        # AllAttendanceView) — this table grows a row per verification
        # attempt per student per lecture, so returning it in full gets
        # linearly slower as history accumulates over semesters.
        limit = min(int(self.request.query_params.get('limit', 200)), 1000)

        # If student, restrict to own profile
        if user.groups.filter(name="student").exists():
            student = getattr(user, 'student_profile', None)
            return FaceAttendanceLog.objects.filter(student=student).select_related(
                "lecture", "student__user"
            ).order_by('-timestamp')[:limit]

        # Admin or Faculty can pass student_id query param
        student_id = self.request.query_params.get("student_id")
        if student_id:
            return FaceAttendanceLog.objects.filter(student_id=student_id).select_related(
                "lecture", "student__user"
            ).order_by('-timestamp')[:limit]

        return FaceAttendanceLog.objects.all().select_related(
            "lecture", "student__user"
        ).order_by('-timestamp')[:limit]


class StudentRequestManualAttendanceView(APIView):
    """
    POST /api/student/request-manual-attendance/
    Allows a student to request manual attendance review from the lecturer.
    """
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def post(self, request):
        lecture_id = request.data.get("lecture_id")
        reason = request.data.get("reason", "Missed/Failed biometric match").strip()

        if not lecture_id:
            return Response({"error": "lecture_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        lecture = get_object_or_404(Lecture, id=lecture_id)
        student = request.user.student_profile

        # Check if already marked present
        if Attendance.objects.filter(user=request.user, lecture=lecture).exists():
            return Response(
                {"error": "You are already marked present for this lecture."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Check for existing request
        existing_request = ManualAttendanceRequest.objects.filter(student=student, lecture=lecture).first()
        if existing_request:
            return Response(
                {"error": f"A request already exists with status: '{existing_request.status}'."},
                status=status.HTTP_400_BAD_REQUEST
            )

        ManualAttendanceRequest.objects.create(
            student=student,
            lecture=lecture,
            reason=reason,
            status='pending'
        )

        return Response(
            {"message": "Manual attendance request submitted to the lecturer."},
            status=status.HTTP_201_CREATED
        )


class StudentManualRequestStatusView(APIView):
    """
    GET /api/student/manual-request-status/?lecture_id=...
    Checks the status of the student's manual attendance request for a specific lecture.
    """
    permission_classes = [permissions.IsAuthenticated, IsStudent]

    def get(self, request):
        lecture_id = request.query_params.get("lecture_id")
        if not lecture_id:
            return Response({"error": "lecture_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        lecture = get_object_or_404(Lecture, id=lecture_id)
        student = request.user.student_profile

        req = ManualAttendanceRequest.objects.filter(student=student, lecture=lecture).first()
        if not req:
            return Response({"has_request": False, "status": None}, status=status.HTTP_200_OK)

        return Response({
            "has_request": True,
            "status": req.status,
            "reason": req.reason,
            "requested_at": req.requested_at
        }, status=status.HTTP_200_OK)

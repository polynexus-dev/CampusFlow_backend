"""
Face Registration Queue (Admin)
================================
An ADMIN operator capturing face angles on behalf of students in a class,
via a per-department queue with status tracking — distinct from
FaceRegistrationView (views/face_attendance.py), which is the STUDENT
self-service flow (all 3 angles in one request, own account only).

Consent is read from Workstream 5's StudentConsent(consent_type=face_recognition),
not BiometricConsentLog — that log remains the self-service pipeline's own
post-hoc consent record and isn't touched here.
"""

from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import StudentProfile, FaceEmbedding, StudentConsent, Department
from ..permissions import IsSaaSOrCollegeAdmin
from ..face_utils import extract_embedding_with_pose

ALL_ANGLES = ["front", "left", "right"]


def _consent_status(student):
    consent = StudentConsent.objects.filter(
        student=student, consent_type=StudentConsent.TYPE_FACE_RECOGNITION
    ).first()
    return bool(consent and consent.is_granted)


class FaceRegistrationQueueView(APIView):
    """
    GET /api/face-registration/queue/?department_id=
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        dept_id = request.query_params.get("department_id")
        if not dept_id:
            return Response({"error": "department_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            Department.objects.get(id=dept_id)
        except Department.DoesNotExist:
            return Response({"error": "Invalid department."}, status=status.HTTP_400_BAD_REQUEST)

        students = StudentProfile.objects.filter(department_id=dept_id).select_related("user")
        entries = []
        done_count = 0

        for student in students:
            entry = {
                "student_id": student.id,
                "name": student.user.get_full_name() or student.user.username,
                "admission_number": student.admission_number,
            }
            if not _consent_status(student):
                entry["status"] = "excluded"
                entry["reason"] = "No face consent"
                entries.append(entry)
                continue

            captured = set(FaceEmbedding.objects.filter(student=student).values_list("angle", flat=True))
            if len(captured) == 3:
                entry["status"] = "complete"
                done_count += 1
            elif captured:
                entry["status"] = "partial"
                entry["angles_captured"] = sorted(captured)
                entry["angles_missing"] = [a for a in ALL_ANGLES if a not in captured]
            else:
                entry["status"] = "queued"
            entries.append(entry)

        return Response({
            "department_id": int(dept_id),
            "total": students.count(),
            "done_count": done_count,
            "students": entries,
        }, status=status.HTTP_200_OK)


class FaceRegistrationCaptureView(APIView):
    """
    POST /api/face-registration/<student_id>/capture/
    Any subset of front/left/right image files in request.FILES.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, student_id):
        try:
            student = StudentProfile.objects.get(id=student_id)
        except StudentProfile.DoesNotExist:
            return Response({"error": "Student not found."}, status=status.HTTP_404_NOT_FOUND)

        if not _consent_status(student):
            return Response({"error": "This student has not consented to face recognition."}, status=status.HTTP_403_FORBIDDEN)

        angle_files = {a: request.FILES[a] for a in ALL_ANGLES if a in request.FILES}
        if not angle_files:
            return Response({"error": "At least one of front/left/right image files is required."}, status=status.HTTP_400_BAD_REQUEST)

        results = {}
        errors = []
        for angle, image_file in angle_files.items():
            image_bytes = image_file.read()
            try:
                embedding, yaw, pitch, roll = extract_embedding_with_pose(image_bytes)
            except ValueError as e:
                errors.append({"angle": angle, "error": str(e)})
                continue
            FaceEmbedding.objects.update_or_create(
                student=student, angle=angle, defaults={"embedding": embedding.tolist()},
            )
            results[angle] = "✓ Embedding stored"

        total_angles = FaceEmbedding.objects.filter(student=student).count()
        if total_angles == 3 and not student.is_face_registered:
            student.is_face_registered = True
            student.save(update_fields=["is_face_registered"])

        response_status = status.HTTP_200_OK if not errors else status.HTTP_207_MULTI_STATUS
        return Response({
            "student_id": student.id,
            "captured": results,
            "errors": errors,
            "angles_captured": total_angles,
            "is_face_registered": student.is_face_registered,
        }, status=response_status)


class FaceRegistrationRetakeView(APIView):
    """
    POST /api/face-registration/<student_id>/retake/<angle>/
    Deletes one angle's stored embedding so the queue shows it as partial again.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def post(self, request, student_id, angle):
        if angle not in ALL_ANGLES:
            return Response({"error": f"angle must be one of {ALL_ANGLES}."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            student = StudentProfile.objects.get(id=student_id)
        except StudentProfile.DoesNotExist:
            return Response({"error": "Student not found."}, status=status.HTTP_404_NOT_FOUND)

        deleted, _ = FaceEmbedding.objects.filter(student=student, angle=angle).delete()

        if deleted and student.is_face_registered:
            student.is_face_registered = False
            student.save(update_fields=["is_face_registered"])

        return Response({
            "student_id": student.id,
            "angle": angle,
            "removed": bool(deleted),
            "is_face_registered": student.is_face_registered,
        }, status=status.HTTP_200_OK)

"""
Admin Enrollment & Consent
==========================
Admin-initiated student enrollment (no such endpoint existed before —
StudentRegistrationView is public self-registration, StaffRegistrationView
explicitly excludes the 'student' role) plus the unified per-student
consent tracking (StudentConsent) that the enrollment screen shows.
"""

import uuid

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import StudentProfile, GuardianProfile, Department, StudentConsent
from ..permissions import IsSaaSOrCollegeAdmin
from ..services.enrollment import generate_admission_number, create_pending_user, send_invite_otp


def _get_or_create_guardian(email, name, phone):
    """Reuse an existing guardian User+GuardianProfile if the email is
    already registered; otherwise create a pending account and invite them.
    guardian_id follows the same 'GUA-XXXXXX' convention already used by
    UserRegistrationSerializer.create() (serializers.py:644) for consistency."""
    from django.contrib.auth.models import User

    existing_user = User.objects.filter(email=email).first()
    if existing_user:
        guardian_profile, _ = GuardianProfile.objects.get_or_create(
            user=existing_user,
            defaults={"guardian_id": f"GUA-{uuid.uuid4().hex[:6].upper()}", "contact_number": phone or ""},
        )
        return guardian_profile, "existing_account_linked"

    first_name, _, last_name = (name or "").partition(" ")
    guardian_user = create_pending_user(email, first_name=first_name, last_name=last_name, username_hint=email.split("@")[0])
    send_invite_otp(guardian_user, subject="You've been invited to CampusFlow",
                     message_prefix=f"{name or 'You'} have been added as a guardian on CampusFlow.")
    guardian_profile = GuardianProfile.objects.create(
        user=guardian_user,
        guardian_id=f"GUA-{uuid.uuid4().hex[:6].upper()}",
        contact_number=phone or "",
        status="active",
    )
    return guardian_profile, "invited"


class AdminEnrollStudentView(APIView):
    """
    POST /api/students/enroll/
    Payload: {
        first_name, last_name, email, date_of_birth,
        department_id, current_semester_year, section_division,
        guardian_name, guardian_email, guardian_phone,
        second_guardian_name, second_guardian_email, second_guardian_phone   # optional
    }
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    @transaction.atomic
    def post(self, request):
        data = request.data
        first_name = (data.get("first_name") or "").strip()
        last_name = (data.get("last_name") or "").strip()
        email = (data.get("email") or "").strip().lower()
        dept_id = data.get("department_id")
        guardian_email = (data.get("guardian_email") or "").strip().lower()
        guardian_name = (data.get("guardian_name") or "").strip()

        if not first_name or not email or not dept_id or not guardian_email:
            return Response(
                {"error": "first_name, email, department_id, and guardian_email are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            department = Department.objects.get(id=dept_id)
        except Department.DoesNotExist:
            return Response({"error": "Invalid department selection."}, status=status.HTTP_400_BAD_REQUEST)

        from django.contrib.auth.models import User
        if User.objects.filter(email=email).exists():
            return Response({"error": "A user with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

        student_user = create_pending_user(email, first_name=first_name, last_name=last_name, username_hint=email.split("@")[0])
        admission_number = generate_admission_number()
        student = StudentProfile.objects.create(
            user=student_user,
            student_id=admission_number,
            admission_number=admission_number,
            admission_date=timezone.localdate(),
            department=department,
            date_of_birth=data.get("date_of_birth") or None,
            current_semester_year=data.get("current_semester_year", ""),
            section_division=data.get("section_division", ""),
            parent_guardian_name=guardian_name,
            parent_guardian_email=guardian_email,
        )

        guardians_result = []
        primary_guardian, primary_status = _get_or_create_guardian(guardian_email, guardian_name, data.get("guardian_phone"))
        primary_guardian.students.add(student)
        guardians_result.append({"email": guardian_email, "status": primary_status})

        second_email = (data.get("second_guardian_email") or "").strip().lower()
        if second_email:
            second_guardian, second_status = _get_or_create_guardian(
                second_email, data.get("second_guardian_name"), data.get("second_guardian_phone")
            )
            second_guardian.students.add(student)
            guardians_result.append({"email": second_email, "status": second_status})

        for consent_type, requirement, auto_granted in [
            (StudentConsent.TYPE_APP_NOTIFICATIONS, StudentConsent.REQUIREMENT_REQUIRED, True),
            (StudentConsent.TYPE_BUS_GPS, StudentConsent.REQUIREMENT_OPT_IN, False),
            (StudentConsent.TYPE_FACE_RECOGNITION, StudentConsent.REQUIREMENT_OPT_IN, False),
        ]:
            StudentConsent.objects.create(
                student=student,
                consent_type=consent_type,
                requirement=requirement,
                is_granted=auto_granted,
                granted_at=timezone.now() if auto_granted else None,
            )

        return Response({
            "student_id": student.id,
            "admission_number": admission_number,
            "student_name": student_user.get_full_name() or student_user.username,
            "guardians": guardians_result,
        }, status=status.HTTP_201_CREATED)


class StudentConsentGrantView(APIView):
    """
    POST /api/consents/<id>/grant/
    Guardian-only — grants one of their linked student's opt-in consents.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        guardian_profile = getattr(request.user, "guardian_profile", None)
        if not guardian_profile:
            return Response({"error": "Only authenticated guardians can grant consent."}, status=status.HTTP_403_FORBIDDEN)

        try:
            consent = StudentConsent.objects.select_related("student").get(pk=pk)
        except StudentConsent.DoesNotExist:
            return Response({"error": "Consent record not found."}, status=status.HTTP_404_NOT_FOUND)

        if not guardian_profile.students.filter(id=consent.student_id).exists():
            return Response({"error": "This student is not linked to your account."}, status=status.HTTP_403_FORBIDDEN)

        if consent.requirement != StudentConsent.REQUIREMENT_OPT_IN:
            return Response({"error": "Only opt-in consents can be granted this way."}, status=status.HTTP_400_BAD_REQUEST)

        consent.is_granted = True
        consent.granted_at = timezone.now()
        consent.granted_by = request.user
        consent.save(update_fields=["is_granted", "granted_at", "granted_by"])

        return Response({
            "id": consent.id,
            "consent_type": consent.consent_type,
            "is_granted": consent.is_granted,
            "granted_at": consent.granted_at.isoformat(),
        }, status=status.HTTP_200_OK)


class EnrollmentStatsView(APIView):
    """
    GET /api/students/enrollment-stats/
    "This week" panel on the Admin enrollment screen.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        week_start = timezone.now() - timezone.timedelta(days=7)

        enrolled_this_week = StudentProfile.objects.filter(user__date_joined__gte=week_start).count()
        guardian_invites_accepted = GuardianProfile.objects.filter(
            user__date_joined__gte=week_start, user__is_active=True
        ).count()
        consent_pending = StudentConsent.objects.filter(
            requirement=StudentConsent.REQUIREMENT_OPT_IN,
            is_granted=False,
            student__user__date_joined__gte=week_start,
        ).count()

        return Response({
            "enrolled_this_week": enrolled_this_week,
            "guardian_invites_accepted_this_week": guardian_invites_accepted,
            "consent_pending_this_week": consent_pending,
        }, status=status.HTTP_200_OK)

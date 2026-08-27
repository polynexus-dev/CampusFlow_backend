"""
DTE/CET admissions — closes roadmap gap #10. See models/dte_cet_admissions.py
for why this is a distinct pipeline from Lead rather than an extension of it.

ConvertCAPAllotmentToStudentView mirrors LeadConvertToStudentView's exact
conversion mechanics (views/admissions.py) — same create_pending_user +
generate_admission_number + GuardianProfile + StudentConsent sequence —
rather than a second implementation of "how do we turn an admitted
candidate into a system account."
"""
from django.contrib.auth.models import User
from django.db import transaction
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models import StudentConsent, StudentProfile
from ..models.dte_cet_admissions import CAPAllotment, CAPApplicant, CAPRound, SeatMatrix
from ..permissions import IsSaaSOrCollegeAdmin, RequiresModule
from ..serializers import (
    CAPAllotmentSerializer, CAPApplicantSerializer, CAPRoundSerializer, SeatMatrixSerializer,
)
from ..services.enrollment import create_pending_user, generate_admission_number
from .enrollment import _get_or_create_guardian

ADMISSIONS_ADMIN_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("admissions")]


class SeatMatrixViewSet(viewsets.ModelViewSet):
    queryset = SeatMatrix.objects.select_related("program", "academic_year").all()
    serializer_class = SeatMatrixSerializer
    permission_classes = ADMISSIONS_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        program = self.request.query_params.get("program")
        academic_year = self.request.query_params.get("academic_year")
        if program:
            qs = qs.filter(program_id=program)
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        return qs


class CAPRoundViewSet(viewsets.ModelViewSet):
    queryset = CAPRound.objects.select_related("academic_year").all()
    serializer_class = CAPRoundSerializer
    permission_classes = ADMISSIONS_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        academic_year = self.request.query_params.get("academic_year")
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        return qs


class CAPApplicantViewSet(viewsets.ModelViewSet):
    queryset = CAPApplicant.objects.select_related("lead").all()
    serializer_class = CAPApplicantSerializer
    permission_classes = ADMISSIONS_ADMIN_PERMS + [IsNotDemoTenant]


class CAPAllotmentViewSet(viewsets.ModelViewSet):
    queryset = CAPAllotment.objects.select_related("applicant", "cap_round", "program").all()
    serializer_class = CAPAllotmentSerializer
    permission_classes = ADMISSIONS_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        cap_round = self.request.query_params.get("cap_round")
        program = self.request.query_params.get("program")
        status_filter = self.request.query_params.get("status")
        if cap_round:
            qs = qs.filter(cap_round_id=cap_round)
        if program:
            qs = qs.filter(program_id=program)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class ConfirmCAPAllotmentView(APIView):
    """POST /api/cap-allotments/<id>/confirm/ — Allotted -> Confirmed."""
    permission_classes = ADMISSIONS_ADMIN_PERMS

    def post(self, request, pk):
        allotment = CAPAllotment.objects.filter(pk=pk).first()
        if not allotment:
            return Response({"error": "Allotment not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            allotment.confirm()
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CAPAllotmentSerializer(allotment).data)


class CancelCAPAllotmentView(APIView):
    """POST /api/cap-allotments/<id>/cancel/ — {reason?}"""
    permission_classes = ADMISSIONS_ADMIN_PERMS

    def post(self, request, pk):
        allotment = CAPAllotment.objects.filter(pk=pk).first()
        if not allotment:
            return Response({"error": "Allotment not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            allotment.cancel(reason=(request.data.get("reason") or "").strip())
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(CAPAllotmentSerializer(allotment).data)


class ConvertCAPAllotmentToStudentView(APIView):
    """
    POST /api/cap-allotments/<id>/convert/
    Confirmed -> real enrolled student, mirroring LeadConvertToStudentView.
    """
    permission_classes = ADMISSIONS_ADMIN_PERMS

    @transaction.atomic
    def post(self, request, pk):
        try:
            allotment = CAPAllotment.objects.select_related("applicant", "program__department").get(pk=pk)
        except CAPAllotment.DoesNotExist:
            return Response({"error": "Allotment not found."}, status=status.HTTP_404_NOT_FOUND)

        if allotment.status != CAPAllotment.STATUS_CONFIRMED:
            return Response(
                {"error": f"Only a confirmed allotment can be converted (current status: '{allotment.status}')."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        applicant = allotment.applicant
        if not allotment.program.department_id:
            return Response(
                {"error": "This allotment's program has no department set — required to enroll."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not applicant.guardian_email:
            return Response(
                {"error": "This applicant has no guardian_email set — required to enroll."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if User.objects.filter(email=applicant.email).exists():
            return Response({"error": "A user with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

        student_user = create_pending_user(
            applicant.email, first_name=applicant.first_name, last_name=applicant.last_name,
            username_hint=applicant.email.split("@")[0],
        )
        admission_number = generate_admission_number()
        student = StudentProfile.objects.create(
            user=student_user,
            student_id=admission_number,
            admission_number=admission_number,
            admission_date=timezone.localdate(),
            department=allotment.program.department,
            parent_guardian_name=applicant.guardian_name,
            parent_guardian_email=applicant.guardian_email,
        )

        guardian, guardian_status = _get_or_create_guardian(
            applicant.guardian_email, applicant.guardian_name, applicant.guardian_phone,
        )
        guardian.students.add(student)

        for consent_type, requirement, auto_granted in [
            (StudentConsent.TYPE_APP_NOTIFICATIONS, StudentConsent.REQUIREMENT_REQUIRED, True),
            (StudentConsent.TYPE_BUS_GPS, StudentConsent.REQUIREMENT_OPT_IN, False),
            (StudentConsent.TYPE_FACE_RECOGNITION, StudentConsent.REQUIREMENT_OPT_IN, False),
        ]:
            StudentConsent.objects.create(
                student=student, consent_type=consent_type, requirement=requirement,
                is_granted=auto_granted, granted_at=timezone.now() if auto_granted else None,
            )

        allotment.converted_student = student
        allotment.save(update_fields=["converted_student"])

        return Response({
            "student_id": student.id,
            "admission_number": admission_number,
            "student_name": student_user.get_full_name() or student_user.username,
            "guardian": {"email": applicant.guardian_email, "status": guardian_status},
            "allotment": CAPAllotmentSerializer(allotment).data,
        }, status=status.HTTP_201_CREATED)

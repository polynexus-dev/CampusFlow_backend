"""
campusflow_app/views/admissions.py

The Lead pipeline API: CRUD + activity logging (both auto-recompute the
lead's rule-based priority score, see services/lead_scoring.py), one small
view per forward stage transition (mirroring
views/compliance.py's SubmitEvidenceItemView/SignOffEvidenceItemView
shape), a consolidated close (reject/withdraw) action, and the conversion
into a real enrolled student — which reuses the same primitives
views/enrollment.py's AdminEnrollStudentView already uses rather than
duplicating account-creation logic. See models/admissions.py's module
docstring and the plan's Context section for why conversion isn't just a
call into a shared "enroll" service function: AdminEnrollStudentView is
existing production code this plan deliberately doesn't touch.
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
from ..models.admissions import Lead, LeadActivity
from ..permissions import IsSaaSOrCollegeAdmin, RequiresModule

ADMISSIONS_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant, RequiresModule("admissions")]
from ..serializers import LeadActivitySerializer, LeadSerializer
from ..services.enrollment import create_pending_user, generate_admission_number
from .enrollment import _get_or_create_guardian


class LeadViewSet(viewsets.ModelViewSet):
    """
    CRUD for prospective-student leads, filterable by status/source/
    interested_department/assigned_to, default-ordered by priority (see
    Lead.Meta.ordering).
    """
    queryset = Lead.objects.select_related(
        "interested_department", "interested_program", "assigned_to", "created_by", "converted_student",
    ).all()
    serializer_class = LeadSerializer
    permission_classes = ADMISSIONS_PERMS

    def get_queryset(self):
        qs = super().get_queryset()
        for param, field in (
            ("status", "status"), ("source", "source"),
            ("interested_department", "interested_department_id"), ("assigned_to", "assigned_to_id"),
        ):
            value = self.request.query_params.get(param)
            if value:
                qs = qs.filter(**{field: value})
        return qs

    def perform_create(self, serializer):
        lead = serializer.save(created_by=self.request.user)
        lead.recompute_priority_score()


class LeadActivityViewSet(viewsets.ModelViewSet):
    """Interaction log — logging one auto-recomputes the parent lead's priority score."""
    queryset = LeadActivity.objects.select_related("lead", "created_by").all()
    serializer_class = LeadActivitySerializer
    permission_classes = ADMISSIONS_PERMS

    def get_queryset(self):
        qs = super().get_queryset()
        lead_id = self.request.query_params.get("lead")
        if lead_id:
            qs = qs.filter(lead_id=lead_id)
        return qs

    def perform_create(self, serializer):
        activity = serializer.save(created_by=self.request.user)
        activity.lead.recompute_priority_score()


class LeadMarkContactedView(APIView):
    """POST /leads/<int:pk>/mark-contacted/ — Inquiry -> Contacted."""
    permission_classes = ADMISSIONS_PERMS

    def post(self, request, pk):
        try:
            lead = Lead.objects.get(pk=pk)
        except Lead.DoesNotExist:
            return Response({"error": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            lead.mark_contacted()
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LeadSerializer(lead).data)


class LeadSubmitApplicationView(APIView):
    """POST /leads/<int:pk>/submit-application/ — Contacted -> Application Submitted."""
    permission_classes = ADMISSIONS_PERMS

    def post(self, request, pk):
        try:
            lead = Lead.objects.get(pk=pk)
        except Lead.DoesNotExist:
            return Response({"error": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            lead.submit_application()
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LeadSerializer(lead).data)


class LeadAdmitView(APIView):
    """POST /leads/<int:pk>/admit/ — Application Submitted -> Admitted."""
    permission_classes = ADMISSIONS_PERMS

    def post(self, request, pk):
        try:
            lead = Lead.objects.get(pk=pk)
        except Lead.DoesNotExist:
            return Response({"error": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            lead.admit()
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LeadSerializer(lead).data)


class LeadCloseView(APIView):
    """
    POST /leads/<int:pk>/close/ {"outcome": "rejected"|"withdrawn", "reason": "..."}
    Consolidated terminal-failure action instead of two near-identical views.
    """
    permission_classes = ADMISSIONS_PERMS

    def post(self, request, pk):
        try:
            lead = Lead.objects.get(pk=pk)
        except Lead.DoesNotExist:
            return Response({"error": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)

        outcome = request.data.get("outcome")
        if outcome not in (Lead.STATUS_REJECTED, Lead.STATUS_WITHDRAWN):
            return Response(
                {"error": "outcome must be 'rejected' or 'withdrawn'."}, status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            lead.close(outcome, reason=request.data.get("reason", ""))
        except ValueError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(LeadSerializer(lead).data)


class LeadConvertToStudentView(APIView):
    """
    POST /leads/<int:pk>/convert/
    Admitted -> Enrolled: creates the real User+StudentProfile+GuardianProfile
    +StudentConsent rows, exactly mirroring AdminEnrollStudentView's shape
    (views/enrollment.py:52-135) and reusing the same primitives, rather
    than a shared refactor — see this file's module docstring.
    """
    permission_classes = ADMISSIONS_PERMS

    @transaction.atomic
    def post(self, request, pk):
        try:
            lead = Lead.objects.select_related("interested_department").get(pk=pk)
        except Lead.DoesNotExist:
            return Response({"error": "Lead not found."}, status=status.HTTP_404_NOT_FOUND)

        if lead.status != Lead.STATUS_ADMITTED:
            return Response(
                {"error": f"Only an admitted lead can be converted (current status: '{lead.status}')."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not lead.interested_department_id:
            return Response(
                {"error": "This lead has no interested_department set — required to enroll."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not lead.guardian_email:
            return Response(
                {"error": "This lead has no guardian_email set — required to enroll."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if User.objects.filter(email=lead.email).exists():
            return Response({"error": "A user with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

        student_user = create_pending_user(
            lead.email, first_name=lead.first_name, last_name=lead.last_name,
            username_hint=lead.email.split("@")[0],
        )
        admission_number = generate_admission_number()
        student = StudentProfile.objects.create(
            user=student_user,
            student_id=admission_number,
            admission_number=admission_number,
            admission_date=timezone.localdate(),
            department=lead.interested_department,
            current_semester_year=request.data.get("current_semester_year", ""),
            section_division=request.data.get("section_division", ""),
            parent_guardian_name=lead.guardian_name,
            parent_guardian_email=lead.guardian_email,
        )

        guardian, guardian_status = _get_or_create_guardian(lead.guardian_email, lead.guardian_name, lead.guardian_phone)
        guardian.students.add(student)

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

        lead.converted_student = student
        lead.status = Lead.STATUS_ENROLLED
        lead.enrolled_at = timezone.now()
        lead.save(update_fields=["converted_student", "status", "enrolled_at", "updated_at"])

        return Response({
            "student_id": student.id,
            "admission_number": admission_number,
            "student_name": student_user.get_full_name() or student_user.username,
            "guardian": {"email": lead.guardian_email, "status": guardian_status},
            "lead": LeadSerializer(lead).data,
        }, status=status.HTTP_201_CREATED)

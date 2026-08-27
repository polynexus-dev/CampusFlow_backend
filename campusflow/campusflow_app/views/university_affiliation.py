"""
University affiliation & LIC — closes roadmap gap #4. Admin-managed, same
permission bar as AccreditationSubmissionViewSet/FeeRegulatingAuthoritySubmissionViewSet
(IsSaaSOrCollegeAdmin) — this is IQAC/College-Admin-level regulatory
tooling, not general faculty-facing data entry.
"""
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.university_affiliation import (
    AffiliationApplication, FacultyWorkloadStatement, ReservationRosterEntry, TeacherApprovalProposal,
)
from ..permissions import IsHMOrAbove, IsSaaSOrCollegeAdmin, RequiresModule
from ..serializers import (
    AffiliationApplicationSerializer, FacultyWorkloadStatementSerializer,
    ReservationRosterEntrySerializer, TeacherApprovalProposalSerializer,
)

AFFILIATION_ADMIN_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("compliance-center")]


class AffiliationApplicationViewSet(viewsets.ModelViewSet):
    queryset = AffiliationApplication.objects.select_related("program", "academic_year", "created_by").all()
    serializer_class = AffiliationApplicationSerializer
    permission_classes = AFFILIATION_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        program = self.request.query_params.get("program")
        academic_year = self.request.query_params.get("academic_year")
        if program:
            qs = qs.filter(program_id=program)
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class SubmitAffiliationApplicationView(APIView):
    """POST /api/affiliation-applications/<id>/submit/ — Draft -> Submitted."""
    permission_classes = AFFILIATION_ADMIN_PERMS

    def post(self, request, pk):
        application = AffiliationApplication.objects.filter(pk=pk).first()
        if not application:
            return Response({"error": "Affiliation application not found."}, status=status.HTTP_404_NOT_FOUND)
        if application.status != AffiliationApplication.STATUS_DRAFT:
            return Response(
                {"error": f"Cannot submit an item that is already {application.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        application.submit()
        return Response(AffiliationApplicationSerializer(application).data)


class RecordLICVisitView(APIView):
    """
    POST /api/affiliation-applications/<id>/record-lic-visit/
    Payload: {visit_date, committee_members?, observations?, compliance_status?}
    """
    permission_classes = AFFILIATION_ADMIN_PERMS

    def post(self, request, pk):
        application = AffiliationApplication.objects.filter(pk=pk).first()
        if not application:
            return Response({"error": "Affiliation application not found."}, status=status.HTTP_404_NOT_FOUND)
        if application.status != AffiliationApplication.STATUS_SUBMITTED:
            return Response(
                {"error": "An LIC visit can only be recorded for a submitted application."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        visit_date = request.data.get("visit_date")
        if not visit_date:
            return Response({"error": "visit_date is required."}, status=status.HTTP_400_BAD_REQUEST)

        application.record_lic_visit(
            visit_date=visit_date,
            committee_members=(request.data.get("committee_members") or "").strip(),
            observations=(request.data.get("observations") or "").strip(),
            compliance_status=request.data.get("compliance_status", ""),
        )
        return Response(AffiliationApplicationSerializer(application).data)


class RecordAffiliationDecisionView(APIView):
    """POST /api/affiliation-applications/<id>/record-decision/ — {decision: "approved"|"rejected", university_reference_number?, remarks?}"""
    permission_classes = AFFILIATION_ADMIN_PERMS

    def post(self, request, pk):
        application = AffiliationApplication.objects.filter(pk=pk).first()
        if not application:
            return Response({"error": "Affiliation application not found."}, status=status.HTTP_404_NOT_FOUND)
        if application.status != AffiliationApplication.STATUS_LIC_VISIT_SCHEDULED:
            return Response(
                {"error": "A decision can only be recorded after an LIC visit has been logged."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        decision = request.data.get("decision")
        if decision not in (AffiliationApplication.STATUS_APPROVED, AffiliationApplication.STATUS_REJECTED):
            return Response({"error": "decision must be 'approved' or 'rejected'."}, status=status.HTTP_400_BAD_REQUEST)

        application.record_decision(
            decision,
            university_reference_number=(request.data.get("university_reference_number") or "").strip(),
            remarks=(request.data.get("remarks") or "").strip(),
        )
        return Response(AffiliationApplicationSerializer(application).data)


class TeacherApprovalProposalViewSet(viewsets.ModelViewSet):
    queryset = TeacherApprovalProposal.objects.select_related("faculty__user", "academic_year", "program").all()
    serializer_class = TeacherApprovalProposalSerializer
    permission_classes = AFFILIATION_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        academic_year = self.request.query_params.get("academic_year")
        faculty = self.request.query_params.get("faculty")
        status_filter = self.request.query_params.get("status")
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        if faculty:
            qs = qs.filter(faculty_id=faculty)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs


class TeacherApprovalProposalDecisionView(APIView):
    """POST /api/teacher-approval-proposals/<id>/record-decision/ — {decision, university_approval_number?, remarks?}
    Same HM-or-above bar as SignOffEvidenceItemView — a teacher cannot approve their own university approval."""
    permission_classes = [IsAuthenticated, IsHMOrAbove, IsNotDemoTenant, RequiresModule("compliance-center")]

    def post(self, request, pk):
        proposal = TeacherApprovalProposal.objects.filter(pk=pk).first()
        if not proposal:
            return Response({"error": "Teacher approval proposal not found."}, status=status.HTTP_404_NOT_FOUND)
        if proposal.status != TeacherApprovalProposal.STATUS_PENDING:
            return Response({"error": "This proposal has already been reviewed."}, status=status.HTTP_400_BAD_REQUEST)

        decision = request.data.get("decision")
        if decision not in (TeacherApprovalProposal.STATUS_APPROVED, TeacherApprovalProposal.STATUS_REJECTED):
            return Response({"error": "decision must be 'approved' or 'rejected'."}, status=status.HTTP_400_BAD_REQUEST)

        proposal.record_decision(
            decision,
            university_approval_number=(request.data.get("university_approval_number") or "").strip(),
            remarks=(request.data.get("remarks") or "").strip(),
            by_user=request.user,
        )
        return Response(TeacherApprovalProposalSerializer(proposal).data)


class FacultyWorkloadStatementViewSet(viewsets.ModelViewSet):
    queryset = FacultyWorkloadStatement.objects.select_related("faculty__user", "academic_year").all()
    serializer_class = FacultyWorkloadStatementSerializer
    permission_classes = AFFILIATION_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        academic_year = self.request.query_params.get("academic_year")
        faculty = self.request.query_params.get("faculty")
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        if faculty:
            qs = qs.filter(faculty_id=faculty)
        return qs


class ReservationRosterEntryViewSet(viewsets.ModelViewSet):
    queryset = ReservationRosterEntry.objects.select_related("department", "filled_by__user").all()
    serializer_class = ReservationRosterEntrySerializer
    permission_classes = AFFILIATION_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        department = self.request.query_params.get("department")
        is_filled = self.request.query_params.get("is_filled")
        if department:
            qs = qs.filter(department_id=department)
        if is_filled is not None:
            qs = qs.filter(is_filled=is_filled.lower() == "true")
        return qs

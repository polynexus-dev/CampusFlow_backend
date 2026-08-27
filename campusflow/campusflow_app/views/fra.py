"""
Fee Regulating Authority (FRA) submissions — closes roadmap gap #9.
Admin-managed, same permission bar as views/fees.py's FEES_ADMIN_PERMS
(fee policy is a College Admin action, not a general "fees" module user
action).
"""
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.fra import FeeRegulatingAuthoritySubmission
from ..permissions import IsSaaSOrCollegeAdmin, RequiresModule
from ..serializers import FeeRegulatingAuthoritySubmissionSerializer

FRA_ADMIN_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("fees")]


class FeeRegulatingAuthoritySubmissionViewSet(viewsets.ModelViewSet):
    queryset = FeeRegulatingAuthoritySubmission.objects.select_related(
        "program", "academic_year", "fee_structure", "created_by",
    ).all()
    serializer_class = FeeRegulatingAuthoritySubmissionSerializer
    permission_classes = FRA_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        academic_year = self.request.query_params.get("academic_year")
        program = self.request.query_params.get("program")
        status_filter = self.request.query_params.get("status")
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        if program:
            qs = qs.filter(program_id=program)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class SubmitFRASubmissionView(APIView):
    """POST /api/fra-submissions/<id>/submit/ — Draft -> Submitted."""
    permission_classes = FRA_ADMIN_PERMS

    def post(self, request, pk):
        submission = FeeRegulatingAuthoritySubmission.objects.filter(pk=pk).first()
        if not submission:
            return Response({"error": "FRA submission not found."}, status=status.HTTP_404_NOT_FOUND)
        if submission.status != FeeRegulatingAuthoritySubmission.STATUS_DRAFT:
            return Response(
                {"error": f"Cannot submit an item that is already {submission.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        submission.submit()
        return Response(FeeRegulatingAuthoritySubmissionSerializer(submission).data)


class RecordFRADecisionView(APIView):
    """
    POST /api/fra-submissions/<id>/record-decision/
    Payload: {decision: "approved"|"rejected"|"revision_requested", sanctioned_fee_amount?, fra_order_number?, remarks?}
    """
    permission_classes = FRA_ADMIN_PERMS

    def post(self, request, pk):
        submission = FeeRegulatingAuthoritySubmission.objects.filter(pk=pk).first()
        if not submission:
            return Response({"error": "FRA submission not found."}, status=status.HTTP_404_NOT_FOUND)
        if submission.status != FeeRegulatingAuthoritySubmission.STATUS_SUBMITTED:
            return Response(
                {"error": "Only a submitted item can have a decision recorded."}, status=status.HTTP_400_BAD_REQUEST,
            )

        decision = request.data.get("decision")
        valid_decisions = (
            FeeRegulatingAuthoritySubmission.STATUS_APPROVED,
            FeeRegulatingAuthoritySubmission.STATUS_REJECTED,
            FeeRegulatingAuthoritySubmission.STATUS_REVISION_REQUESTED,
        )
        if decision not in valid_decisions:
            return Response(
                {"error": f"decision must be one of {list(valid_decisions)}."}, status=status.HTTP_400_BAD_REQUEST,
            )
        if decision == FeeRegulatingAuthoritySubmission.STATUS_APPROVED and request.data.get("sanctioned_fee_amount") is None:
            return Response(
                {"error": "sanctioned_fee_amount is required when approving."}, status=status.HTTP_400_BAD_REQUEST,
            )

        submission.record_decision(
            decision,
            sanctioned_fee_amount=request.data.get("sanctioned_fee_amount"),
            fra_order_number=(request.data.get("fra_order_number") or "").strip(),
            remarks=(request.data.get("remarks") or "").strip(),
        )
        return Response(FeeRegulatingAuthoritySubmissionSerializer(submission).data)

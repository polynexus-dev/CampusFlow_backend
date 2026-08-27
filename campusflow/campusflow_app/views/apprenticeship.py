"""
NATS apprenticeship layer — closes roadmap gap #15.

ApprenticeshipContractViewSet follows RecruitmentDriveViewSet/
PlacementApplicationViewSet's own bar exactly (views/tpo.py): any
authenticated user with the "tpo" module, no extra role split — this
module's existing views already draw that same line.

StipendClaim gets the pending -> approved/rejected + reviewed_by/
reviewed_at request/approval shape RevaluationRequest and
ResultCorrectionRequest already use, but — unlike those two — the approving
side genuinely cannot be "any tpo-module user": that would let an
apprentice approve their own stipend. IsTPOStaffOrAbove below is the one
new permission this phase needs, narrowing review to actual staff (Faculty+
or the Placement Officer role) while filing stays open to the apprentice.
"""
from rest_framework import status, viewsets
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.utils import timezone

from ..models.apprenticeship import ApprenticeshipContract, StipendClaim
from ..permissions import RequiresModule, get_user_group, is_faculty_or_above, is_saas_admin
from ..serializers import ApprenticeshipContractSerializer

TPO_PERMS = [IsAuthenticated, RequiresModule("tpo")]


class IsTPOStaffOrAbove(BasePermission):
    """Faculty-or-above, or the Placement Officer role — deliberately NOT
    satisfied by a plain student/apprentice, since this gates stipend-claim
    approval."""
    message = "Only TPO staff or College Admin can review stipend claims."

    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if is_saas_admin(user) or is_faculty_or_above(user):
            return True
        return get_user_group(user) == "Placement Officer"


class ApprenticeshipContractViewSet(viewsets.ModelViewSet):
    queryset = ApprenticeshipContract.objects.select_related(
        "placement_application__student__user", "placement_application__drive",
    ).all()
    serializer_class = ApprenticeshipContractSerializer
    permission_classes = TPO_PERMS

    def get_queryset(self):
        qs = super().get_queryset()
        student_id = self.request.query_params.get("student_id")
        if student_id:
            qs = qs.filter(placement_application__student_id=student_id)
        return qs


def _serialize_stipend_claim(claim):
    return {
        "id": claim.id,
        "contract_id": claim.contract_id,
        "student_name": claim.contract.placement_application.student.user.get_full_name()
                         or claim.contract.placement_application.student.user.username,
        "employer_name": claim.contract.employer_name,
        "month": claim.month,
        "year": claim.year,
        "claimed_amount": float(claim.claimed_amount),
        "attendance_percent": float(claim.attendance_percent) if claim.attendance_percent is not None else None,
        "status": claim.status,
        "requested_at": claim.requested_at.isoformat(),
    }


class StipendClaimCreateView(APIView):
    """
    POST /api/apprenticeship/stipend-claims/
    Payload: {contract_id, month, year, claimed_amount, attendance_percent?}
    Open to the apprentice filing a claim against their own contract.
    """
    permission_classes = TPO_PERMS

    def post(self, request):
        contract_id = request.data.get("contract_id")
        month = request.data.get("month")
        year = request.data.get("year")
        claimed_amount = request.data.get("claimed_amount")
        if not contract_id or not month or not year or claimed_amount is None:
            return Response(
                {"error": "contract_id, month, year, and claimed_amount are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        contract = ApprenticeshipContract.objects.select_related(
            "placement_application__student__user",
        ).filter(pk=contract_id).first()
        if not contract:
            return Response({"error": "Apprenticeship contract not found."}, status=status.HTTP_404_NOT_FOUND)

        student_profile = getattr(request.user, "student_profile", None)
        if not student_profile or contract.placement_application.student_id != student_profile.id:
            return Response(
                {"error": "You can only file stipend claims for your own apprenticeship contract."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            month = int(month)
            year = int(year)
        except (TypeError, ValueError):
            return Response({"error": "month and year must be integers."}, status=status.HTTP_400_BAD_REQUEST)
        if not (1 <= month <= 12):
            return Response({"error": "month must be between 1 and 12."}, status=status.HTTP_400_BAD_REQUEST)

        if StipendClaim.objects.filter(contract=contract, month=month, year=year).exists():
            return Response(
                {"error": "A stipend claim for this month already exists."}, status=status.HTTP_400_BAD_REQUEST,
            )

        claim = StipendClaim.objects.create(
            contract=contract, month=month, year=year, claimed_amount=claimed_amount,
            attendance_percent=request.data.get("attendance_percent"),
        )
        return Response(_serialize_stipend_claim(claim), status=status.HTTP_201_CREATED)


class StipendClaimListView(APIView):
    """GET /api/apprenticeship/stipend-claims/pending/?contract_id= — TPO staff+ only."""
    permission_classes = [IsAuthenticated, RequiresModule("tpo"), IsTPOStaffOrAbove]

    def get(self, request):
        qs = StipendClaim.objects.filter(status=StipendClaim.STATUS_PENDING).select_related(
            "contract__placement_application__student__user",
        )
        contract_id = request.query_params.get("contract_id")
        if contract_id:
            qs = qs.filter(contract_id=contract_id)
        return Response({"results": [_serialize_stipend_claim(c) for c in qs.order_by("-year", "-month")]})


class StipendClaimActionView(APIView):
    """POST /api/apprenticeship/stipend-claims/<id>/action/ — {action: "approve" | "reject"}"""
    permission_classes = [IsAuthenticated, RequiresModule("tpo"), IsTPOStaffOrAbove]

    def post(self, request, pk):
        claim = StipendClaim.objects.select_related(
            "contract__placement_application__student__user",
        ).filter(pk=pk).first()
        if not claim:
            return Response({"error": "Stipend claim not found."}, status=status.HTTP_404_NOT_FOUND)

        if claim.status != StipendClaim.STATUS_PENDING:
            return Response({"error": "This claim has already been reviewed."}, status=status.HTTP_400_BAD_REQUEST)

        action = request.data.get("action")
        if action not in ("approve", "reject"):
            return Response({"error": "action must be 'approve' or 'reject'."}, status=status.HTTP_400_BAD_REQUEST)

        claim.status = StipendClaim.STATUS_APPROVED if action == "approve" else StipendClaim.STATUS_REJECTED
        claim.reviewed_by = request.user
        claim.reviewed_at = timezone.now()
        claim.save(update_fields=["status", "reviewed_by", "reviewed_at"])
        return Response(_serialize_stipend_claim(claim))

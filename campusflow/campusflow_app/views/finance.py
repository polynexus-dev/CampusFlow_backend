from rest_framework import viewsets, status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from ..demo_guard import IsNotDemoTenant
from ..models.finance import (
    FinancialYear, IncomeCategory, IncomeEntry, ExpenseCategory, ExpenseEntry, FixedAsset,
)
from ..serializers import (
    FinancialYearSerializer, IncomeCategorySerializer, IncomeEntrySerializer,
    ExpenseCategorySerializer, ExpenseEntrySerializer, FixedAssetSerializer,
)
from ..permissions import IsSaaSOrCollegeAdmin, RequiresModule


class FinancialYearViewSet(viewsets.ModelViewSet):
    """
    Financial Year & Ledger Foundation — the anchor everything else in the
    ledger hangs off. Locking a year is a dedicated action (`close/`), not a
    plain field edit, so the carry-forward calculation always runs with it.
    """
    queryset = FinancialYear.objects.all()
    serializer_class = FinancialYearSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant, RequiresModule("ledger")]


class CloseFinancialYearView(APIView):
    """
    POST /api/financial-years/<int:pk>/close/  { "next_financial_year_id": <id> }
    Locks this FY (append-only from here on) and carries its closing cash+bank
    balance forward into next_financial_year's opening balance.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant, RequiresModule("ledger")]

    def post(self, request, pk):
        try:
            fy = FinancialYear.objects.get(pk=pk)
        except FinancialYear.DoesNotExist:
            return Response({"error": "Financial year not found."}, status=status.HTTP_404_NOT_FOUND)

        if fy.is_locked:
            return Response({"error": f"Financial year {fy.label} is already locked."}, status=status.HTTP_400_BAD_REQUEST)

        next_fy_id = request.data.get("next_financial_year_id")
        if not next_fy_id:
            return Response({"error": "next_financial_year_id is required so the closing balance has somewhere to carry forward to."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            next_fy = FinancialYear.objects.get(pk=next_fy_id)
        except FinancialYear.DoesNotExist:
            return Response({"error": "Target next financial year not found."}, status=status.HTTP_404_NOT_FOUND)

        fy.close_and_carry_forward(next_fy)
        fy.locked_by = request.user
        fy.save(update_fields=["locked_by"])

        return Response({
            "message": f"Financial year {fy.label} locked. Closing balance carried forward to {next_fy.label}.",
            "financial_year": FinancialYearSerializer(fy).data,
            "next_financial_year": FinancialYearSerializer(next_fy).data,
        })


class IncomeCategoryViewSet(viewsets.ModelViewSet):
    queryset = IncomeCategory.objects.all()
    serializer_class = IncomeCategorySerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant, RequiresModule("ledger")]


class IncomeEntryViewSet(viewsets.ModelViewSet):
    """The missing non-fee income side — donations, grants, interest, rental income."""
    queryset = IncomeEntry.objects.select_related('category', 'financial_year', 'recorded_by').all()
    serializer_class = IncomeEntrySerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant, RequiresModule("ledger")]

    def get_queryset(self):
        qs = super().get_queryset()
        fy = self.request.query_params.get('financial_year')
        if fy:
            qs = qs.filter(financial_year_id=fy)
        return qs

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class ExpenseCategoryViewSet(viewsets.ModelViewSet):
    queryset = ExpenseCategory.objects.all()
    serializer_class = ExpenseCategorySerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant, RequiresModule("ledger")]


class ExpenseEntryViewSet(viewsets.ModelViewSet):
    """The missing non-payroll expense side — rent, utilities, vendor payments, AMC/maintenance."""
    queryset = ExpenseEntry.objects.select_related('category', 'department', 'vendor', 'financial_year', 'recorded_by').all()
    serializer_class = ExpenseEntrySerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant, RequiresModule("ledger")]

    def get_queryset(self):
        qs = super().get_queryset()
        fy = self.request.query_params.get('financial_year')
        if fy:
            qs = qs.filter(financial_year_id=fy)
        return qs

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class FixedAssetViewSet(viewsets.ModelViewSet):
    """Distinct from InventoryItem — a Fixed Asset Register needs cost/depreciation, not stock quantity."""
    queryset = FixedAsset.objects.select_related('department', 'supplier').all()
    serializer_class = FixedAssetSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant, RequiresModule("ledger")]

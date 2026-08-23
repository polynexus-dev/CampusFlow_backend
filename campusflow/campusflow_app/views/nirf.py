from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.finance import FinancialYear
from ..models.nirf import NIRFDataEntry
from ..permissions import IsSaaSOrCollegeAdmin, RequiresModule
from ..serializers import NIRFDataEntrySerializer
from ..services.nirf_compilation import compile_nirf_report
# Reused rather than duplicated — same multi-sheet xlsx shape AISHE/AICTE/NAAC
# reports already use (see views/compliance.py's P5 section).
from .compliance import _accreditation_xlsx_response


class NIRFDataEntryViewSet(viewsets.ModelViewSet):
    """
    CRUD for the NIRF figures that have nowhere else to live (research
    funding, patents, publications, library spend, higher-studies/govt-exam
    counts) — everything else NIRF needs is computed live from existing data
    by NIRFReportView below. Same admin-only bar as the accreditation
    certificate/criterion catalogs this sits next to.
    """
    queryset = NIRFDataEntry.objects.select_related("financial_year", "recorded_by").all()
    serializer_class = NIRFDataEntrySerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant, RequiresModule("compliance-center")]

    def get_queryset(self):
        qs = super().get_queryset()
        financial_year = self.request.query_params.get("financial_year")
        if financial_year:
            qs = qs.filter(financial_year_id=financial_year)
        return qs

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)


class NIRFReportView(APIView):
    """
    GET /api/compliance-center/reports/nirf-data-compilation/?financial_year=<id>&nirf_category=<name>&export=xlsx
    Compiles the NIRF Data Capture System's raw input figures for one
    financial year — no score or predicted rank (see models/nirf.py).
    `nirf_category` is optional; when given and no matching NIRFDataEntry
    exists yet, the RP/library/higher-studies figures render as an explicit
    "not yet entered" placeholder instead of blocking the report.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("compliance-center")]

    def get(self, request):
        financial_year_id = request.query_params.get("financial_year")
        if not financial_year_id:
            return Response({"error": "financial_year query param is required."}, status=status.HTTP_400_BAD_REQUEST)
        financial_year = FinancialYear.objects.filter(pk=financial_year_id).first()
        if not financial_year:
            return Response({"error": "Financial year not found."}, status=status.HTTP_404_NOT_FOUND)

        nirf_category = request.query_params.get("nirf_category")
        nirf_entry = None
        if nirf_category:
            nirf_entry = NIRFDataEntry.objects.filter(
                financial_year=financial_year, nirf_category=nirf_category,
            ).first()
        else:
            nirf_entry = NIRFDataEntry.objects.filter(financial_year=financial_year).first()

        sections = compile_nirf_report(financial_year, nirf_entry)

        if (request.query_params.get("export") or "").lower() == "xlsx":
            return _accreditation_xlsx_response(f"nirf_data_compilation_{financial_year.label}.xlsx", sections)

        return Response({
            "financial_year": financial_year.label,
            "nirf_category": nirf_entry.nirf_category if nirf_entry else nirf_category,
            "sections": [{"heading": h, "header": header, "rows": rows} for h, header, rows in sections],
        })

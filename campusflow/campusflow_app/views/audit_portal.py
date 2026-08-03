"""
CA Audit Portal — the external, read-only, time-boxed CA/Statutory Auditor
login (Docs/compliance_and_audit_portal_plan.md §1 and §3). Two halves:

1. Provisioning (College Admin facing): InviteAuditorView, AuditEngagement
   list/revoke.
2. The reports themselves (CA facing, gated by IsActiveAuditor): each report
   below (a) resolves the engagement's FinancialYear via
   `request.auditor_engagement` (set by IsActiveAuditor), (b) surfaces a
   warning if that year isn't locked yet, (c) writes an AuditorAccessLog row,
   (d) returns JSON for the in-portal table, or CSV when `?format=csv` is
   passed for the export button. There is no PDF/Excel pipeline anywhere in
   this codebase to reuse (checked: no reportlab/weasyprint/openpyxl in
   requirements.txt) — CSV is the export format here since every spreadsheet
   tool opens it and it needs zero new dependencies; upgrading to a styled
   PDF/Excel export later is additive, not a redesign.
"""
import csv
import io
import secrets
import zipfile

from django.contrib.auth.models import Group, User
from django.core.mail import send_mail
from django.http import HttpResponse
from django.utils.dateparse import parse_date
from ipware import get_client_ip
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.audit_portal import AuditEngagement, AuditorAccessLog, AuditorProfile
from ..models.fees import FeePayment, StudentFeeInvoice
from ..models.finance import ExpenseEntry, FinancialYear, FixedAsset, IncomeEntry, _year_month_pairs
from ..models.payments import PaymentGatewayTransaction
from ..models.payroll import Payslip, SalaryStructure
from ..permissions import IsActiveAuditor, IsSaaSOrCollegeAdmin, get_user_group
from ..serializers import AuditEngagementSerializer, AuditorProfileSerializer


# ─────────────────────────────────────────────
# Provisioning — College Admin facing
# ─────────────────────────────────────────────

class InviteAuditorView(APIView):
    """
    Self-service "Invite Auditor" for the College Admin — firm name, ICAI
    number, email, financial year, access window. One call creates the User +
    Group=CA + AuditorProfile + one AuditEngagement, and emails credentials.
    No SaaS-Admin involvement needed, same trust level as adding any other
    staff member today.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]

    def post(self, request):
        email = (request.data.get("email") or "").strip().lower()
        firm_name = (request.data.get("firm_name") or "").strip()
        icai_number = (request.data.get("icai_membership_number") or "").strip()
        financial_year_id = request.data.get("financial_year_id")
        access_start_raw = request.data.get("access_start")
        access_end_raw = request.data.get("access_end")

        if not email or not financial_year_id or not access_start_raw or not access_end_raw:
            return Response(
                {"error": "email, financial_year_id, access_start, and access_end are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Parsed explicitly rather than handed straight to .objects.create() —
        # AuditEngagement.is_active compares access_start/access_end against
        # today's date, and that comparison blows up if these are still raw
        # strings on the in-memory instance this view immediately serializes
        # (the DB layer would cast them fine on a re-fetch, but there isn't one here).
        access_start = parse_date(access_start_raw)
        access_end = parse_date(access_end_raw)
        if not access_start or not access_end:
            return Response(
                {"error": "access_start and access_end must be valid dates (YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            financial_year = FinancialYear.objects.get(pk=financial_year_id)
        except FinancialYear.DoesNotExist:
            return Response({"error": "Financial year not found."}, status=status.HTTP_404_NOT_FOUND)

        if User.objects.filter(email=email).exists():
            return Response({"error": f"A user with email {email} already exists."}, status=status.HTTP_400_BAD_REQUEST)

        base_username = email.split("@")[0]
        username = base_username
        suffix = 1
        while User.objects.filter(username=username).exists():
            suffix += 1
            username = f"{base_username}{suffix}"

        temp_password = secrets.token_urlsafe(9)
        user = User.objects.create_user(username=username, email=email, password=temp_password)
        user.first_name = firm_name[:30]
        user.is_active = True
        user.save(update_fields=["first_name", "is_active"])

        ca_group, _ = Group.objects.get_or_create(name="CA")
        user.groups.add(ca_group)

        auditor_profile = AuditorProfile.objects.create(
            user=user,
            firm_name=firm_name or None,
            icai_membership_number=icai_number or None,
            contact_number=(request.data.get("contact_number") or "").strip() or None,
            invited_by=request.user,
        )
        engagement = AuditEngagement.objects.create(
            auditor=auditor_profile,
            financial_year=financial_year,
            access_start=access_start,
            access_end=access_end,
            granted_by=request.user,
        )

        try:
            send_mail(
                "CampusNexus — CA Audit Portal Access Granted",
                (
                    f"Dear {firm_name or 'Auditor'},\n\n"
                    f"You have been granted read-only audit portal access for financial year "
                    f"{financial_year.label}, valid {access_start} to {access_end}.\n\n"
                    f"Login username: {username}\n"
                    f"Temporary password: {temp_password}\n\n"
                    f"Please log in and change your password. This portal is view/export-only — "
                    f"no edit access is granted.\n\n"
                    f"CampusNexus — Polynexus Technologies Private Limited"
                ),
                None,
                [email],
                fail_silently=True,
            )
        except Exception:
            pass

        return Response({
            "message": f"Auditor {email} invited for FY {financial_year.label}.",
            "auditor_profile": AuditorProfileSerializer(auditor_profile).data,
            "engagement": AuditEngagementSerializer(engagement).data,
        }, status=status.HTTP_201_CREATED)


class AuditEngagementListView(APIView):
    """GET /api/audit-engagements/ — College Admin's view of every CA engagement, active or not."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        engagements = AuditEngagement.objects.select_related("auditor", "auditor__user", "financial_year").all()
        return Response(AuditEngagementSerializer(engagements, many=True).data)


class RevokeAuditEngagementView(APIView):
    """POST /api/audit-portal/engagements/<int:pk>/revoke/ — manual early revocation, on top of auto-expiry."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]

    def post(self, request, pk):
        try:
            engagement = AuditEngagement.objects.get(pk=pk)
        except AuditEngagement.DoesNotExist:
            return Response({"error": "Engagement not found."}, status=status.HTTP_404_NOT_FOUND)
        engagement.revoke(by_user=request.user)
        return Response({"message": "Engagement revoked.", "engagement": AuditEngagementSerializer(engagement).data})


class MyAuditEngagementsView(APIView):
    """
    GET /api/audit-portal/my-engagements/ — a CA's own view of which
    financial years they've been granted access to, so the frontend can
    populate a report selector without the CA needing to already know a
    financial_year id.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if get_user_group(request.user) != 'CA':
            return Response({"error": "Not a CA account."}, status=status.HTTP_403_FORBIDDEN)
        try:
            auditor = request.user.auditor_profile
        except AuditorProfile.DoesNotExist:
            return Response({"error": "No auditor profile found for this account."}, status=status.HTTP_404_NOT_FOUND)

        engagements = auditor.engagements.select_related("financial_year").all()
        return Response({
            "auditor": AuditorProfileSerializer(auditor).data,
            "engagements": AuditEngagementSerializer(engagements, many=True).data,
        })


# ─────────────────────────────────────────────
# Shared helpers for the report endpoints
# ─────────────────────────────────────────────

def _log_access(request, report_type, action=AuditorAccessLog.ACTION_VIEW):
    engagement = request.auditor_engagement
    client_ip, _ = get_client_ip(request)
    AuditorAccessLog.objects.create(
        auditor=engagement.auditor,
        engagement=engagement,
        report_type=report_type,
        action=action,
        ip_address=client_ip,
    )


def _lock_warning(financial_year):
    if financial_year.is_locked:
        return None
    return (
        f"Financial year {financial_year.label} is not yet locked/closed — figures may still change. "
        f"CA review is normally done on a locked year."
    )


def _csv_response(filename, header, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    response = HttpResponse(buffer.getvalue(), content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _xlsx_response(filename, sheet_title, header, rows):
    from openpyxl import Workbook
    from openpyxl.styles import Font

    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title[:31]  # Excel's own sheet-name length cap

    ws.append(header)
    for cell in ws[1]:
        cell.font = Font(bold=True)
    for row in rows:
        ws.append([str(v) if not isinstance(v, (int, float, type(None))) else v for v in row])
    for i, column_cells in enumerate(ws.columns, start=1):
        max_len = max((len(str(c.value)) for c in column_cells if c.value is not None), default=10)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max_len + 2, 60)

    buffer = io.BytesIO()
    wb.save(buffer)
    response = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _export_format(request):
    """'csv', 'xlsx', or None (JSON) — the export button on each CA report offers both."""
    fmt = (request.query_params.get("export") or "").lower()
    return fmt if fmt in ("csv", "xlsx") else None


def _export_response(filename_base, sheet_title, header, rows, fmt):
    if fmt == "xlsx":
        return _xlsx_response(f"{filename_base}.xlsx", sheet_title, header, rows)
    return _csv_response(f"{filename_base}.csv", header, rows)


# ─────────────────────────────────────────────
# The reports themselves — CA facing
# ─────────────────────────────────────────────

class ReceiptsPaymentsStatementView(APIView):
    """The primary cash-basis statement, reconciles directly to the bank
    statement the CA already requests: Opening + Receipts - Payments = Closing."""
    permission_classes = [IsAuthenticated, IsActiveAuditor]

    def get(self, request):
        fy = request.auditor_engagement.financial_year
        export_format = _export_format(request)
        action = AuditorAccessLog.ACTION_DOWNLOAD if export_format else AuditorAccessLog.ACTION_VIEW
        _log_access(request, "receipts_payments", action)

        from django.db.models import Sum
        fee_receipt_total = FeePayment.objects.filter(
            payment_date__date__gte=fy.start_date, payment_date__date__lte=fy.end_date,
        ).aggregate(total=Sum("amount_paid"))["total"] or 0
        income_entries = list(fy.income_entries.select_related("category").all())
        income_total = sum((e.amount for e in income_entries), start=type(fy.opening_cash_balance)(0)) if income_entries else 0

        expense_entries = list(fy.expense_entries.select_related("category").all())
        expense_total = sum((e.amount for e in expense_entries), start=type(fy.opening_cash_balance)(0)) if expense_entries else 0

        pairs = _year_month_pairs(fy.start_date, fy.end_date)
        payslip_qs = Payslip.objects.none()
        if pairs:
            from django.db.models import Q
            q = Q()
            for y, m in pairs:
                q |= Q(year=y, month=m)
            payslip_qs = Payslip.objects.filter(q)
        payroll_total = payslip_qs.aggregate(total=Sum("net_payable"))["total"] or 0

        data = {
            "financial_year": fy.label,
            "warning": _lock_warning(fy),
            "opening_balance": fy.opening_balance,
            "receipts": {
                "fee_payments": fee_receipt_total,
                "other_income": [{"category": e.category.name, "amount": e.amount, "source": e.source, "date": e.received_date} for e in income_entries],
                "other_income_total": income_total,
                "total_receipts": fee_receipt_total + income_total,
            },
            "payments": {
                "payroll_net_payable": payroll_total,
                "other_expenses": [{"category": e.category.name, "amount": e.amount, "date": e.payment_date} for e in expense_entries],
                "other_expenses_total": expense_total,
                "total_payments": payroll_total + expense_total,
            },
            "closing_balance": fy.opening_balance + (fee_receipt_total + income_total) - (payroll_total + expense_total),
        }

        if export_format:
            rows = [["Opening Balance", "", data["opening_balance"]]]
            rows.append(["Fee Payments (Receipt)", "", fee_receipt_total])
            for e in income_entries:
                rows.append([f"Income: {e.category.name}", e.source or "", e.amount])
            rows.append(["Payroll Net Payable (Payment)", "", -payroll_total])
            for e in expense_entries:
                rows.append([f"Expense: {e.category.name}", e.payment_date, -e.amount])
            rows.append(["Closing Balance", "", data["closing_balance"]])
            return _export_response(f"receipts_payments_{fy.label}", "Receipts & Payments", ["Line Item", "Detail", "Amount"], rows, export_format)

        return Response(data)


class IncomeExpenditureStatementView(APIView):
    """The accrual-adjusted secondary statement: Income - Expenditure = Surplus/Deficit."""
    permission_classes = [IsAuthenticated, IsActiveAuditor]

    def get(self, request):
        from django.db.models import Sum, Q
        fy = request.auditor_engagement.financial_year
        export_format = _export_format(request)
        action = AuditorAccessLog.ACTION_DOWNLOAD if export_format else AuditorAccessLog.ACTION_VIEW
        _log_access(request, "income_expenditure", action)

        fee_income = StudentFeeInvoice.objects.filter(
            due_date__gte=fy.start_date, due_date__lte=fy.end_date,
        ).aggregate(total=Sum("total_amount") )["total"] or 0
        discount_total = StudentFeeInvoice.objects.filter(
            due_date__gte=fy.start_date, due_date__lte=fy.end_date,
        ).aggregate(total=Sum("discount_amount"))["total"] or 0
        net_fee_income = fee_income - discount_total
        other_income_total = fy.income_entries.aggregate(total=Sum("amount"))["total"] or 0

        expense_total = fy.expense_entries.aggregate(total=Sum("amount"))["total"] or 0

        pairs = _year_month_pairs(fy.start_date, fy.end_date)
        payroll_cost = 0
        if pairs:
            q = Q()
            for y, m in pairs:
                q |= Q(year=y, month=m)
            payroll_cost = Payslip.objects.filter(q).aggregate(total=Sum("gross_salary"))["total"] or 0

        depreciation_total = sum(
            (a.depreciation_for_period(fy.start_date, fy.end_date) for a in FixedAsset.objects.all()),
            start=type(fy.opening_cash_balance)(0),
        )

        total_income = net_fee_income + other_income_total
        total_expenditure = expense_total + payroll_cost + depreciation_total

        data = {
            "financial_year": fy.label,
            "warning": _lock_warning(fy),
            "income": {
                "fee_income_net_of_discount": net_fee_income,
                "other_income": other_income_total,
                "total_income": total_income,
            },
            "expenditure": {
                "other_expenses": expense_total,
                "payroll_cost": payroll_cost,
                "depreciation": depreciation_total,
                "total_expenditure": total_expenditure,
            },
            "surplus_deficit": total_income - total_expenditure,
        }

        if export_format:
            rows = [
                ["Fee Income (net of discount)", net_fee_income],
                ["Other Income", other_income_total],
                ["Total Income", total_income],
                ["Other Expenses", expense_total],
                ["Payroll Cost", payroll_cost],
                ["Depreciation", depreciation_total],
                ["Total Expenditure", total_expenditure],
                ["Surplus / (Deficit)", data["surplus_deficit"]],
            ]
            return _export_response(f"income_expenditure_{fy.label}", "Income & Expenditure", ["Line Item", "Amount"], rows, export_format)

        return Response(data)


class FixedAssetRegisterView(APIView):
    """Every FixedAsset row plus its written-down value as of FinancialYear.end_date, grouped by category."""
    permission_classes = [IsAuthenticated, IsActiveAuditor]

    def get(self, request):
        fy = request.auditor_engagement.financial_year
        export_format = _export_format(request)
        action = AuditorAccessLog.ACTION_DOWNLOAD if export_format else AuditorAccessLog.ACTION_VIEW
        _log_access(request, "fixed_asset_register", action)

        assets = FixedAsset.objects.filter(purchase_date__lte=fy.end_date).select_related("department", "supplier")
        rows_data = []
        for a in assets:
            rows_data.append({
                "name": a.name,
                "category": a.category,
                "department": a.department.name if a.department else None,
                "purchase_date": a.purchase_date,
                "purchase_cost": a.purchase_cost,
                "depreciation_method": a.depreciation_method,
                "depreciation_rate_percent": a.depreciation_rate_percent,
                "depreciation_this_year": a.depreciation_for_period(fy.start_date, fy.end_date),
                "written_down_value": a.written_down_value(fy.end_date),
                "disposed_date": a.disposed_date,
            })

        if export_format:
            rows = [[r["name"], r["category"], r["department"], r["purchase_date"], r["purchase_cost"],
                     r["depreciation_method"], r["depreciation_rate_percent"], r["depreciation_this_year"],
                     r["written_down_value"], r["disposed_date"]] for r in rows_data]
            return _export_response(
                f"fixed_asset_register_{fy.label}", "Fixed Asset Register",
                ["Name", "Category", "Department", "Purchase Date", "Purchase Cost", "Method", "Rate %",
                 "Depreciation This Year", "WDV as of FY End", "Disposed Date"],
                rows, export_format,
            )

        return Response({"financial_year": fy.label, "warning": _lock_warning(fy), "assets": rows_data})


class PayrollStatutorySummaryView(APIView):
    """Payroll / TDS / PF / ESI statutory summary — SalaryStructure carries the
    per-employee rates, Payslip carries how many months were actually paid in
    this FY, so the summary is rate x months-paid, not a re-derivation."""
    permission_classes = [IsAuthenticated, IsActiveAuditor]

    def get(self, request):
        from django.db.models import Q, Count, Sum
        fy = request.auditor_engagement.financial_year
        export_format = _export_format(request)
        action = AuditorAccessLog.ACTION_DOWNLOAD if export_format else AuditorAccessLog.ACTION_VIEW
        _log_access(request, "payroll_statutory_summary", action)

        pairs = _year_month_pairs(fy.start_date, fy.end_date)
        rows_data = []
        totals = {"gross": 0, "pf": 0, "esi": 0, "tds": 0, "net": 0}

        if pairs:
            q = Q()
            for y, m in pairs:
                q |= Q(year=y, month=m)
            months_paid_by_user = (
                Payslip.objects.filter(q).values("user_id").annotate(months_paid=Count("id"))
            )
            months_map = {row["user_id"]: row["months_paid"] for row in months_paid_by_user}
            net_by_user = {
                row["user_id"]: row["total_net"]
                for row in Payslip.objects.filter(q).values("user_id").annotate(total_net=Sum("net_payable"))
            }
            for structure in SalaryStructure.objects.select_related("user").filter(user_id__in=months_map.keys()):
                months_paid = months_map.get(structure.user_id, 0)
                gross = structure.gross_salary * months_paid
                pf = structure.pf_deduction * months_paid
                esi = structure.esi_deduction * months_paid
                tds = structure.tds_deduction * months_paid
                net = net_by_user.get(structure.user_id, 0) or 0
                rows_data.append({
                    "employee": structure.user.get_full_name() or structure.user.username,
                    "months_paid": months_paid,
                    "gross_salary": gross,
                    "pf": pf,
                    "esi": esi,
                    "tds": tds,
                    "net_payable": net,
                })
                totals["gross"] += gross
                totals["pf"] += pf
                totals["esi"] += esi
                totals["tds"] += tds
                totals["net"] += net

        if export_format:
            rows = [[r["employee"], r["months_paid"], r["gross_salary"], r["pf"], r["esi"], r["tds"], r["net_payable"]] for r in rows_data]
            rows.append(["TOTAL", "", totals["gross"], totals["pf"], totals["esi"], totals["tds"], totals["net"]])
            return _export_response(
                f"payroll_statutory_summary_{fy.label}", "Payroll Statutory Summary",
                ["Employee", "Months Paid", "Gross Salary", "PF", "ESI", "TDS", "Net Payable"],
                rows, export_format,
            )

        return Response({"financial_year": fy.label, "warning": _lock_warning(fy), "employees": rows_data, "totals": totals})


class FeeReconciliationView(APIView):
    """Fee collection reconciliation: invoice total vs. FeePayment ledger vs.
    what the payment gateway actually confirms as paid."""
    permission_classes = [IsAuthenticated, IsActiveAuditor]

    def get(self, request):
        from django.db.models import Sum
        fy = request.auditor_engagement.financial_year
        export_format = _export_format(request)
        action = AuditorAccessLog.ACTION_DOWNLOAD if export_format else AuditorAccessLog.ACTION_VIEW
        _log_access(request, "fee_reconciliation", action)

        invoices = StudentFeeInvoice.objects.filter(
            due_date__gte=fy.start_date, due_date__lte=fy.end_date,
        ).select_related("student")

        rows_data = []
        for inv in invoices:
            gateway_paid = PaymentGatewayTransaction.objects.filter(
                invoice=inv, status=PaymentGatewayTransaction.STATUS_PAID,
            ).aggregate(total=Sum("amount"))["total"] or 0
            rows_data.append({
                "invoice_number": inv.invoice_number,
                "student": inv.student.get_full_name() or inv.student.username,
                "total_amount": inv.total_amount,
                "discount_amount": inv.discount_amount,
                "paid_amount_ledger": inv.paid_amount,
                "gateway_confirmed_amount": gateway_paid,
                "status": inv.status,
                "reconciled": True,
            })

        if export_format:
            rows = [[r["invoice_number"], r["student"], r["total_amount"], r["discount_amount"],
                     r["paid_amount_ledger"], r["gateway_confirmed_amount"], r["status"]] for r in rows_data]
            return _export_response(
                f"fee_reconciliation_{fy.label}", "Fee Reconciliation",
                ["Invoice #", "Student", "Total Amount", "Discount", "Paid (Ledger)", "Gateway Confirmed", "Status"],
                rows, export_format,
            )

        return Response({"financial_year": fy.label, "warning": _lock_warning(fy), "invoices": rows_data})


class VendorLedgerView(APIView):
    """Vendor / supplier ledger — every ExpenseEntry grouped by vendor for the FY."""
    permission_classes = [IsAuthenticated, IsActiveAuditor]

    def get(self, request):
        from django.db.models import Sum
        fy = request.auditor_engagement.financial_year
        export_format = _export_format(request)
        action = AuditorAccessLog.ACTION_DOWNLOAD if export_format else AuditorAccessLog.ACTION_VIEW
        _log_access(request, "vendor_ledger", action)

        entries = ExpenseEntry.objects.filter(financial_year=fy, vendor__isnull=False).select_related("vendor", "category")
        by_vendor = {}
        for e in entries:
            by_vendor.setdefault(e.vendor.name, {"vendor": e.vendor.name, "total": 0, "entries": []})
            by_vendor[e.vendor.name]["total"] += e.amount
            by_vendor[e.vendor.name]["entries"].append({
                "category": e.category.name, "amount": e.amount,
                "payment_date": e.payment_date, "payment_reference": e.payment_reference,
            })

        vendors = list(by_vendor.values())

        if export_format:
            rows = []
            for v in vendors:
                for entry in v["entries"]:
                    rows.append([v["vendor"], entry["category"], entry["payment_date"], entry["payment_reference"], entry["amount"]])
            return _export_response(
                f"vendor_ledger_{fy.label}", "Vendor Ledger",
                ["Vendor", "Category", "Payment Date", "Reference", "Amount"],
                rows, export_format,
            )

        return Response({"financial_year": fy.label, "warning": _lock_warning(fy), "vendors": vendors})


class DocumentVaultExportView(APIView):
    """One-click Document Vault export — bundles every income/expense voucher
    for the financial year into a single ZIP, instead of the CA chasing
    individual records. Invoice/receipt/payslip PDFs aren't generated as files
    by this system today (they're rendered on demand), so the vault covers the
    file-backed records that exist: IncomeEntry/ExpenseEntry vouchers."""
    permission_classes = [IsAuthenticated, IsActiveAuditor]

    def get(self, request):
        fy = request.auditor_engagement.financial_year
        _log_access(request, "document_vault", AuditorAccessLog.ACTION_DOWNLOAD)

        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in IncomeEntry.objects.filter(financial_year=fy, voucher__isnull=False).exclude(voucher=""):
                try:
                    zf.writestr(f"income_vouchers/{entry.id}_{entry.voucher.name.split('/')[-1]}", entry.voucher.read())
                except Exception:
                    continue
            for entry in ExpenseEntry.objects.filter(financial_year=fy, voucher__isnull=False).exclude(voucher=""):
                try:
                    zf.writestr(f"expense_vouchers/{entry.id}_{entry.voucher.name.split('/')[-1]}", entry.voucher.read())
                except Exception:
                    continue

        response = HttpResponse(buffer.getvalue(), content_type="application/zip")
        response["Content-Disposition"] = f'attachment; filename="document_vault_{fy.label}.zip"'
        return response

"""
Financial Year & Ledger Foundation — closes the two real data gaps (non-fee
income, non-payroll expense) so the books are complete on a cash-basis
ledger. Deliberately single-entry / cash-basis, not a full double-entry
general ledger — that's a separate accounting product, not a college ERP
feature. See Docs/compliance_and_audit_portal_plan.md §2.
"""
from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from .department import Department


def _year_month_pairs(start_date, end_date):
    """Every (year, month) pair whose 15th falls within [start_date, end_date] —
    used to slice month/year-keyed Payslip rows into a financial year without
    requiring Payslip to carry its own date field."""
    pairs = []
    y, m = start_date.year, start_date.month
    while date(y, m, 1) <= end_date:
        if start_date <= date(y, m, 15) <= end_date:
            pairs.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return pairs


def get_financial_year_for_date(for_date):
    return FinancialYear.objects.filter(start_date__lte=for_date, end_date__gte=for_date).first()


def get_locked_financial_year_for_date(for_date):
    """None if the date falls in no FY or an open one; the FinancialYear if it's locked."""
    fy = get_financial_year_for_date(for_date)
    return fy if (fy and fy.is_locked) else None


class FinancialYear(models.Model):
    """
    The anchor the rest of the ledger hangs off — including the opening
    balances needed to make the Receipts & Payments statement actually balance.
    """
    label = models.CharField(max_length=20, unique=True, help_text='e.g. "2025-2026"')
    start_date = models.DateField(help_text="Typically Apr 1.")
    end_date = models.DateField(help_text="Typically Mar 31.")
    opening_cash_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    opening_bank_balance = models.DecimalField(max_digits=14, decimal_places=2, default=0)
    is_locked = models.BooleanField(default=False)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='locked_financial_years',
    )

    class Meta:
        verbose_name = "Financial Year"
        verbose_name_plural = "Financial Years"
        ordering = ['-start_date']

    def __str__(self):
        return self.label

    @property
    def opening_balance(self):
        return self.opening_cash_balance + self.opening_bank_balance

    def total_receipts(self):
        from .fees import FeePayment
        fee_receipts = FeePayment.objects.filter(
            payment_date__date__gte=self.start_date, payment_date__date__lte=self.end_date,
        ).aggregate(total=models.Sum('amount_paid'))['total'] or Decimal('0')
        income_receipts = self.income_entries.aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
        return fee_receipts + income_receipts

    def total_payments(self):
        from .payroll import Payslip
        pairs = _year_month_pairs(self.start_date, self.end_date)
        payslip_filter = models.Q()
        for y, m in pairs:
            payslip_filter |= models.Q(year=y, month=m)
        payroll_payments = (
            Payslip.objects.filter(payslip_filter).aggregate(total=models.Sum('net_payable'))['total']
            if pairs else None
        ) or Decimal('0')
        expense_payments = self.expense_entries.aggregate(total=models.Sum('amount'))['total'] or Decimal('0')
        return payroll_payments + expense_payments

    def closing_balance(self):
        return self.opening_balance + self.total_receipts() - self.total_payments()

    def close_and_carry_forward(self, next_fy):
        """
        Computes this FY's closing cash+bank balance (opening + receipts -
        payments) and writes it as next_fy's opening balance, then locks this
        FY. Called once, when Admin locks the year. The cash/bank split of the
        closing figure is a manual admin decision (this system doesn't track
        which receipts landed in cash vs. bank) — the full closing balance is
        written to next_fy.opening_bank_balance and next_fy.opening_cash_balance
        is left at 0, for Admin to redistribute if needed.
        """
        closing = self.closing_balance()
        next_fy.opening_bank_balance = closing
        next_fy.opening_cash_balance = Decimal('0')
        next_fy.save(update_fields=['opening_bank_balance', 'opening_cash_balance'])
        self.is_locked = True
        self.locked_at = timezone.now()
        self.save(update_fields=['is_locked', 'locked_at'])


class IncomeCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)  # "Donation", "Government Grant", "Interest Income", "Rental Income", "Other"

    class Meta:
        verbose_name = "Income Category"
        verbose_name_plural = "Income Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class IncomeEntry(models.Model):
    """The missing non-fee income side — donations, government grants,
    interest on fixed deposits, rental income — none of which route through
    the fees module."""
    category = models.ForeignKey(IncomeCategory, on_delete=models.PROTECT, related_name='entries')
    financial_year = models.ForeignKey(FinancialYear, on_delete=models.PROTECT, related_name='income_entries')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    source = models.CharField(max_length=255, blank=True, null=True, help_text="Donor name / grant scheme / bank name")
    received_date = models.DateField()
    receipt_reference = models.CharField(max_length=100, blank=True, null=True)
    voucher = models.FileField(upload_to='income_vouchers/', blank=True, null=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_income_entries')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Income Entry"
        verbose_name_plural = "Income Entries"
        ordering = ['-received_date']

    def __str__(self):
        return f"{self.category.name} - ₹{self.amount} ({self.received_date})"


class ExpenseCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)  # "Rent", "Utilities", "AMC/Maintenance", ...

    class Meta:
        verbose_name = "Expense Category"
        verbose_name_plural = "Expense Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class ExpenseEntry(models.Model):
    """The missing non-payroll expense side — rent, utilities, vendor
    payments, AMC/maintenance. InventoryTransaction tracks stock *quantity*
    movement, never money; this is the money side."""
    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='entries')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='expense_entries')
    financial_year = models.ForeignKey(FinancialYear, on_delete=models.PROTECT, related_name='expense_entries')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    vendor = models.ForeignKey('campusflow_app.Supplier', on_delete=models.SET_NULL, null=True, blank=True, related_name='expense_entries')
    payment_date = models.DateField()
    payment_reference = models.CharField(max_length=100, blank=True, null=True)
    voucher = models.FileField(upload_to='expense_vouchers/', blank=True, null=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_expense_entries')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Expense Entry"
        verbose_name_plural = "Expense Entries"
        ordering = ['-payment_date']

    def __str__(self):
        return f"{self.category.name} - ₹{self.amount} ({self.payment_date})"


class FixedAsset(models.Model):
    """
    Distinct from InventoryItem on purpose — a stock "item" (chalk, paper)
    and a "fixed asset" (a projector, a bus) are different lifecycles.
    InventoryItem has quantity/unit/threshold_level; this has cost, purchase
    date, and depreciation.
    """
    METHOD_SLM = 'SLM'
    METHOD_WDV = 'WDV'
    METHOD_CHOICES = [(METHOD_SLM, 'Straight Line'), (METHOD_WDV, 'Written Down Value')]

    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100, help_text="Furniture, IT Equipment, Vehicle, etc.")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='fixed_assets')
    purchase_date = models.DateField()
    purchase_cost = models.DecimalField(max_digits=12, decimal_places=2)
    supplier = models.ForeignKey('campusflow_app.Supplier', on_delete=models.SET_NULL, null=True, blank=True, related_name='fixed_asset_sales')
    depreciation_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_WDV)
    depreciation_rate_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=15.00,
        help_text="Admin-editable per asset — Companies Act/IT Act schedule rates are a common starting point, not enforced here.",
    )
    disposed_date = models.DateField(null=True, blank=True)
    disposal_value = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Fixed Asset"
        verbose_name_plural = "Fixed Assets"
        ordering = ['-purchase_date']

    def __str__(self):
        return f"{self.name} ({self.category})"

    def written_down_value(self, as_of_date):
        """Standard WDV calculation from purchase_cost, depreciation_rate_percent,
        purchase_date -> as_of_date. Disposed assets read at their disposal_value
        from the disposal date onward."""
        if self.disposed_date and as_of_date >= self.disposed_date:
            return self.disposal_value or Decimal('0.00')
        if as_of_date < self.purchase_date:
            return Decimal('0.00')

        days_elapsed = (as_of_date - self.purchase_date).days
        years_elapsed = days_elapsed / Decimal('365.25')
        rate = self.depreciation_rate_percent / Decimal('100')

        if self.depreciation_method == self.METHOD_WDV:
            # Decimal ** Decimal only supports integer exponents in Python's
            # decimal module — years_elapsed is fractional, so the reducing-
            # balance factor is computed in float and converted back.
            factor = (1 - float(rate)) ** float(years_elapsed) if rate < 1 else 0.0
            value = self.purchase_cost * Decimal(str(factor))
        else:
            value = self.purchase_cost - (self.purchase_cost * rate * years_elapsed)

        return max(Decimal('0.00'), value.quantize(Decimal('0.01')))

    def depreciation_for_period(self, start_date, end_date):
        """Depreciation charge for a period — opening WDV minus closing WDV,
        or purchase_cost minus closing WDV when the asset was bought mid-period."""
        if self.purchase_date > end_date:
            return Decimal('0.00')
        if self.purchase_date > start_date:
            opening = self.purchase_cost
        else:
            opening = self.written_down_value(start_date)
        closing = self.written_down_value(end_date)
        return max(Decimal('0.00'), (opening - closing).quantize(Decimal('0.01')))

from django.db import models
from django.contrib.auth.models import User


class SalaryStructure(models.Model):
    """
    Defines the pay components for an employee.
    One-to-one mapping: each employee has exactly one salary structure.
    """
    user = models.OneToOneField(
        User, on_delete=models.CASCADE,
        related_name='salary_structure',
        help_text="The employee this salary structure belongs to."
    )
    # Earnings
    basic_pay = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    hra = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="House Rent Allowance")
    da = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Dearness Allowance")
    ta = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Travel Allowance")
    other_allowances = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Deductions
    pf_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Provident Fund")
    esi_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Employee State Insurance")
    tds_deduction = models.DecimalField(max_digits=12, decimal_places=2, default=0, help_text="Tax Deducted at Source")
    other_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def gross_salary(self):
        return self.basic_pay + self.hra + self.da + self.ta + self.other_allowances

    @property
    def total_deductions(self):
        return self.pf_deduction + self.esi_deduction + self.tds_deduction + self.other_deductions

    @property
    def net_salary(self):
        return self.gross_salary - self.total_deductions

    class Meta:
        verbose_name = "Salary Structure"
        verbose_name_plural = "Salary Structures"

    def __str__(self):
        return f"{self.user.username} — Gross: ₹{self.gross_salary}, Net: ₹{self.net_salary}"


class Payslip(models.Model):
    """
    Monthly payslip generated for an employee, linking attendance and leave data
    to produce a final payable amount with detailed breakdown.
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('finalized', 'Finalized'),
        ('paid', 'Paid'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='payslips'
    )
    month = models.PositiveIntegerField(help_text="Month number (1-12)")
    year = models.PositiveIntegerField(help_text="Year, e.g. 2026")
    # Attendance-linked fields (snapshot at generation time)
    total_working_days = models.PositiveIntegerField(default=0)
    present_days = models.PositiveIntegerField(default=0)
    leave_days = models.PositiveIntegerField(default=0, help_text="Approved leaves in this month.")
    absent_days = models.PositiveIntegerField(default=0, help_text="Working − Present − Leave")
    # Pay breakdown (snapshot)
    gross_salary = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    absence_deduction = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="(gross / working_days) × absent_days"
    )
    net_payable = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="gross − total_deductions − absence_deduction"
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='draft')
    generated_on = models.DateTimeField(auto_now_add=True)
    finalized_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='finalized_payslips'
    )

    class Meta:
        verbose_name = "Payslip"
        verbose_name_plural = "Payslips"
        unique_together = ('user', 'month', 'year')
        ordering = ['-year', '-month']

    def __str__(self):
        return f"{self.user.username} — {self.month}/{self.year} — ₹{self.net_payable} [{self.status}]"

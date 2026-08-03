"""
State government scholarship reconciliation — the biggest gap outside the
original compliance/CA-audit plan. `StudentProfile.scholarship_fee_concession_details`
is free text today; colleges that lean on state SC/ST/OBC/EBC scholarship
schemes (state post-matric portals, EBC reimbursement, minority scholarships)
currently reconcile sanctioned-vs-disbursed-vs-fee-waiver entirely by hand in
a spreadsheet. This is money, so it sits next to the Fees module and the
ledger (FinancialYear), not under accreditation.
"""
from django.contrib.auth.models import User
from django.db import models

from .finance import FinancialYear


class StateScholarshipScheme(models.Model):
    """A named state (or central) scholarship scheme a college's students
    draw on — e.g. "Maharashtra EBC Scholarship", "Karnataka Post-Matric
    Scholarship (SC/ST)", "Central Sector Scheme of Scholarship"."""
    name = models.CharField(max_length=200)
    state = models.CharField(max_length=100, blank=True, null=True, help_text="State administering the scheme, blank for a central scheme.")
    administering_department = models.CharField(max_length=200, blank=True, null=True, help_text="e.g. Social Welfare Dept, Directorate of Technical Education")
    eligible_categories = models.CharField(max_length=255, blank=True, null=True, help_text="e.g. SC, ST, OBC, EBC, Minority — free text, comma separated")
    portal_url = models.URLField(max_length=500, blank=True, null=True, help_text="e.g. the state's Mahadbt/e-Kalyan/NSP-style portal, for reference only")

    class Meta:
        verbose_name = "State Scholarship Scheme"
        verbose_name_plural = "State Scholarship Schemes"
        ordering = ['state', 'name']
        constraints = [
            models.UniqueConstraint(fields=['name', 'state'], name='uniq_scholarship_scheme_name_state'),
        ]

    def __str__(self):
        return f"{self.name} ({self.state or 'Central'})"


class StudentScholarshipRecord(models.Model):
    """One student's application/award under one scheme for one financial
    year — sanctioned amount, disbursed amount, and how much of it was
    actually applied as a fee waiver on their StudentFeeInvoice, so the gap
    between 'scholarship promised' and 'scholarship received' is visible
    instead of buried in a free-text field."""
    STATUS_APPLIED = 'applied'
    STATUS_SANCTIONED = 'sanctioned'
    STATUS_DISBURSED = 'disbursed'
    STATUS_REJECTED = 'rejected'
    STATUS_CHOICES = [
        (STATUS_APPLIED, 'Applied'),
        (STATUS_SANCTIONED, 'Sanctioned'),
        (STATUS_DISBURSED, 'Disbursed'),
        (STATUS_REJECTED, 'Rejected'),
    ]

    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scholarship_records')
    scheme = models.ForeignKey(StateScholarshipScheme, on_delete=models.PROTECT, related_name='records')
    financial_year = models.ForeignKey(FinancialYear, on_delete=models.PROTECT, related_name='scholarship_records')
    application_reference = models.CharField(max_length=100, blank=True, null=True)
    sanctioned_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    disbursed_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    disbursed_date = models.DateField(blank=True, null=True)
    fee_waiver_applied = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        help_text="How much of the disbursed/sanctioned amount was actually applied as a fee waiver "
                   "on the student's invoice — kept separate from disbursed_amount because the state "
                   "portal's payment timeline rarely matches the college's fee due dates.",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_APPLIED)
    remarks = models.TextField(blank=True, null=True)
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_scholarship_records')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Student Scholarship Record"
        verbose_name_plural = "Student Scholarship Records"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.student.get_full_name() or self.student.username} — {self.scheme.name} ({self.status})"

    @property
    def reconciliation_gap(self):
        """Sanctioned but not yet disbursed — the number colleges chase state portals for."""
        return max(0, self.sanctioned_amount - self.disbursed_amount)

"""
CA Role & Access Control — a separate, external CA login that is read-only
and time-boxed by construction, not by a permission toggle that could be
missed. See Docs/compliance_and_audit_portal_plan.md §1.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from .finance import FinancialYear


class AuditorProfile(models.Model):
    """
    CA users are external professionals, not institution staff — deliberately
    thin next to the 6 institution-staff profile models (no department, no
    designation progression, no biometric/DPDP consent block).
    """
    STATUS_ACTIVE = 'active'
    STATUS_REVOKED = 'revoked'
    STATUS_CHOICES = [(STATUS_ACTIVE, 'Active'), (STATUS_REVOKED, 'Revoked')]

    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='auditor_profile')
    firm_name = models.CharField(max_length=255, blank=True, null=True)
    icai_membership_number = models.CharField(
        max_length=20, blank=True, null=True,
        help_text="ICAI Membership No. — for engagement letters / audit trail",
    )
    contact_number = models.CharField(max_length=15, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    invited_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='auditors_invited',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Auditor Profile"
        verbose_name_plural = "Auditor Profiles"

    def __str__(self):
        return f"{self.firm_name or self.user.get_full_name()} ({self.icai_membership_number or 'no ICAI #'})"


class AuditEngagement(models.Model):
    """
    The actual access-control gate, separate from the profile. A CA only
    sees a given financial year's data for the window the college has
    actually engaged them, and access auto-expires without an admin needing
    to remember to revoke it.
    """
    auditor = models.ForeignKey(AuditorProfile, on_delete=models.CASCADE, related_name='engagements')
    financial_year = models.ForeignKey(FinancialYear, on_delete=models.CASCADE, related_name='engagements')
    access_start = models.DateField()
    access_end = models.DateField()
    granted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='engagements_granted',
    )
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='engagements_revoked',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Audit Engagement"
        verbose_name_plural = "Audit Engagements"
        ordering = ['-access_start']

    def __str__(self):
        return f"{self.auditor} — FY {self.financial_year.label} ({self.access_start} to {self.access_end})"

    @property
    def is_active(self):
        today = timezone.now().date()
        return self.revoked_at is None and self.access_start <= today <= self.access_end

    def revoke(self, by_user=None):
        self.revoked_at = timezone.now()
        self.revoked_by = by_user
        self.save(update_fields=['revoked_at', 'revoked_by'])


class AuditorAccessLog(models.Model):
    """
    The existing AuditLog (models/audit.py) is signal-driven off
    pre_save/post_save/post_delete — it only fires on mutations. A CA's
    entire interaction with the portal is reads and downloads, which those
    signals never see, so this is written explicitly from inside the
    audit-portal views instead.
    """
    ACTION_VIEW = 'VIEW'
    ACTION_DOWNLOAD = 'DOWNLOAD'
    ACTION_CHOICES = [(ACTION_VIEW, 'View'), (ACTION_DOWNLOAD, 'Download')]

    auditor = models.ForeignKey(AuditorProfile, on_delete=models.CASCADE, related_name='access_logs')
    engagement = models.ForeignKey(AuditEngagement, on_delete=models.CASCADE, related_name='access_logs')
    report_type = models.CharField(max_length=50, help_text="e.g. 'receipts_payments', 'fixed_asset_register'")
    action = models.CharField(max_length=10, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Auditor Access Log"
        verbose_name_plural = "Auditor Access Logs"
        ordering = ['-timestamp']

    def __str__(self):
        return f"{self.auditor} {self.action} {self.report_type} @ {self.timestamp}"

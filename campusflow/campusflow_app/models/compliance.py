from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class ComplianceCertificateType(models.Model):
    """
    Catalog of certificate/license categories a college must keep on file for
    regulatory bodies — e.g. "UGC 2(f) Recognition", "Fire Safety NOC",
    "AICTE EOA Letter", "Trust/Society Registration".
    """
    name = models.CharField(max_length=150, unique=True)
    issuing_authority = models.CharField(max_length=150, blank=True, null=True, help_text="e.g. UGC, AICTE, State Fire Department")
    renews_annually = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Compliance Certificate Type"
        verbose_name_plural = "Compliance Certificate Types"
        ordering = ['name']

    def __str__(self):
        return self.name


class ComplianceCertificate(models.Model):
    """
    A manually-uploaded certificate/license — UGC recognition, Trust/Society
    registration, AICTE EOA letter, Fire Safety NOC, affiliation certificate,
    a previous NAAC certificate, and similar. These are documents that can only
    ever be supplied by the college, never generated from system data.
    """
    STATUS_VALID = 'valid'
    STATUS_EXPIRING_SOON = 'expiring_soon'
    STATUS_EXPIRED = 'expired'

    certificate_type = models.ForeignKey(
        ComplianceCertificateType, on_delete=models.PROTECT, related_name='certificates'
    )
    file = models.FileField(upload_to='compliance_certificates/')
    certificate_number = models.CharField(max_length=100, blank=True, null=True)
    issued_date = models.DateField(blank=True, null=True)
    valid_until = models.DateField(
        blank=True, null=True,
        help_text="Set for anything with a renewal cycle — powers the expiry-reminder job."
    )
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='uploaded_compliance_certificates'
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Compliance Certificate"
        verbose_name_plural = "Compliance Certificates"
        ordering = ['-uploaded_at']

    def __str__(self):
        return f"{self.certificate_type.name} ({self.status})"

    @property
    def status(self):
        if not self.valid_until:
            return self.STATUS_VALID
        days_left = (self.valid_until - timezone.now().date()).days
        if days_left < 0:
            return self.STATUS_EXPIRED
        if days_left <= 60:
            return self.STATUS_EXPIRING_SOON
        return self.STATUS_VALID

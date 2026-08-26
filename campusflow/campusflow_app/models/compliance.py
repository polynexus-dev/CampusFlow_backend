from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

from .department import Department
from .finance import FinancialYear


class ComplianceCertificateType(models.Model):
    """
    Catalog of certificate/license categories a college must keep on file for
    regulatory bodies — e.g. "UGC 2(f) Recognition", "Fire Safety NOC",
    "AICTE EOA Letter", "Trust/Society Registration".
    """
    name = models.CharField(max_length=150, unique=True)
    issuing_authority = models.CharField(max_length=150, blank=True, null=True, help_text="e.g. UGC, AICTE, State Fire Department")
    renews_annually = models.BooleanField(default=False)
    varies_by_state = models.BooleanField(
        default=False,
        help_text="True for certificates whose issuing body/format is state-specific (Professional "
                   "Tax, Shops & Establishments, State Pollution Control Board Consent, etc.) rather "
                   "than a single national body — lets the college's own state stay in issuing_authority.",
    )

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


class InstitutionProfile(models.Model):
    """
    One row per tenant schema — static institution-level identifiers that
    regulatory returns need but that aren't computable from any other model.
    Fetched via get_or_create (see services/compliance.py), the same lazy-
    singleton idiom used by the academic calendar and clearance settings.
    """
    aishe_code = models.CharField(
        max_length=20, blank=True, null=True,
        help_text="AISHE institution code — feeds the IIQA submission and the AISHE annual return.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Institution Profile"
        verbose_name_plural = "Institution Profile"

    def __str__(self):
        return f"Institution Profile (AISHE: {self.aishe_code or 'not set'})"


class AccreditationCriterion(models.Model):
    """The NAAC/NBA criteria catalog (e.g. "1.1", "3.4") with title text —
    the rows the NAAC SSR/AQAR Evidence Workspace organizes evidence under."""
    BODY_NAAC = 'NAAC'
    BODY_NBA = 'NBA'
    BODY_CHOICES = [(BODY_NAAC, 'NAAC'), (BODY_NBA, 'NBA')]

    body = models.CharField(max_length=10, choices=BODY_CHOICES, default=BODY_NAAC)
    code = models.CharField(max_length=20, help_text='e.g. "1.1", "3.4"')
    title = models.CharField(max_length=255)

    class Meta:
        verbose_name = "Accreditation Criterion"
        verbose_name_plural = "Accreditation Criteria"
        ordering = ['body', 'code']
        constraints = [
            models.UniqueConstraint(fields=['body', 'code'], name='uniq_accreditation_criterion_code'),
        ]

    def __str__(self):
        return f"{self.body} {self.code} — {self.title}"


class EvidenceItem(models.Model):
    """
    A file OR a pointer back to an existing record (an exam result set, an
    assignment, a faculty publication link, a Phase-1 ComplianceCertificate)
    tagged to a criterion, department, and year — the "IQAC coordinator's
    Excel sheet" replacement. Evidence can reuse an existing record instead
    of forcing a re-upload, by design (see Docs/compliance_and_audit_portal_plan.md §4 Phase B).
    """
    STATUS_DRAFT = 'draft'
    STATUS_SUBMITTED = 'submitted'
    STATUS_SIGNED_OFF = 'signed_off'
    STATUS_CHOICES = [
        (STATUS_DRAFT, 'Draft'),
        (STATUS_SUBMITTED, 'Submitted'),
        (STATUS_SIGNED_OFF, 'Signed Off'),
    ]

    criterion = models.ForeignKey(AccreditationCriterion, on_delete=models.CASCADE, related_name='evidence')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='accreditation_evidence')
    financial_year = models.ForeignKey(
        FinancialYear, on_delete=models.CASCADE, related_name='accreditation_evidence',
        help_text="Reused as the academic-year anchor for this evidence item.",
    )
    file = models.FileField(upload_to='naac_evidence/', blank=True, null=True)
    description = models.TextField(blank=True, null=True)
    linked_certificate = models.ForeignKey(
        ComplianceCertificate, on_delete=models.SET_NULL, null=True, blank=True, related_name='evidence_items',
        help_text="Reuse a Phase 1 certificate instead of uploading the same PDF a second time.",
    )
    linked_object_type = models.CharField(
        max_length=100, blank=True, null=True,
        help_text='Optional pointer back to a source record instead of a re-upload, e.g. "Exam", "TeachingStaffProfile".',
    )
    linked_object_id = models.PositiveIntegerField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='uploaded_evidence_items')
    submitted_at = models.DateTimeField(null=True, blank=True)
    signed_off_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='signed_off_evidence',
    )
    signed_off_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Evidence Item"
        verbose_name_plural = "Evidence Items"
        ordering = ['criterion__code', '-created_at']

    def __str__(self):
        return f"{self.criterion} — {self.department or 'institution-wide'} [{self.status}]"

    def submit(self):
        self.status = self.STATUS_SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=['status', 'submitted_at'])

    def sign_off(self, by_user):
        self.status = self.STATUS_SIGNED_OFF
        self.signed_off_by = by_user
        self.signed_off_at = timezone.now()
        self.save(update_fields=['status', 'signed_off_by', 'signed_off_at'])

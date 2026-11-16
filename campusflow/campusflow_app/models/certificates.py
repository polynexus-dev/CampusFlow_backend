"""
Student certificates (Bonafide, Character, Leaving/Transfer, Course
Completion, custom) and their verification. Docs/college_gap_closure_plan.md §1.1.

Templates are plain text with {placeholder} tokens, substituted by
services/certificates.py with a regex (never str.format or Django template
rendering), so a College Admin editing a template cannot reach object
attributes or template tags.

Two ways a certificate gets issued:
  * an office user issues it directly (IssuedCertificate created at once), or
  * a student raises a CertificateRequest, which an office user approves
    (issuing it) or rejects, the same request/approve flow ConvocationRequest
    and MigrationRequest already use.
"""
import uuid

from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string

from .profile import StudentProfile


class CertificateTemplate(models.Model):
    TYPE_BONAFIDE = "bonafide"
    TYPE_CHARACTER = "character"
    TYPE_LEAVING = "leaving"
    TYPE_COURSE_COMPLETION = "course_completion"
    TYPE_PARTICIPATION = "participation"
    TYPE_CUSTOM = "custom"
    TYPE_CHOICES = [
        (TYPE_BONAFIDE, "Bonafide Certificate"),
        (TYPE_CHARACTER, "Character Certificate"),
        (TYPE_LEAVING, "Leaving / Transfer Certificate"),
        (TYPE_COURSE_COMPLETION, "Course Completion Certificate"),
        (TYPE_PARTICIPATION, "Participation Certificate"),
        (TYPE_CUSTOM, "Custom"),
    ]

    name = models.CharField(max_length=255)
    cert_type = models.CharField(max_length=30, choices=TYPE_CHOICES, default=TYPE_CUSTOM)
    title = models.CharField(
        max_length=255, help_text='Heading printed on the certificate, e.g. "BONAFIDE CERTIFICATE".',
    )
    body_text = models.TextField(
        help_text="Plain text with {placeholders}. Always available: {student_name}, {student_id}, "
                  "{guardian_name}, {department}, {program}, {semester}, {batch}, {date_of_birth}, "
                  "{admission_date}, {academic_year}, {college_name}, {today}, {purpose}, "
                  "{certificate_number}. Per-issuance extra_context keys are also available.",
    )
    requires_approval = models.BooleanField(
        default=True, help_text="If true, a student's request waits for an office user to approve it.",
    )
    requires_final_clearance = models.BooleanField(
        default=False,
        help_text="If true, the certificate can only be issued once the student's final-exit "
                  "(No-Dues) clearance is complete. On by default for Leaving certificates.",
    )
    student_can_request = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class CertificateRequest(models.Model):
    STATUS_PENDING = "pending"
    STATUS_ISSUED = "issued"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_ISSUED, "Issued"),
        (STATUS_REJECTED, "Rejected"),
    ]

    template = models.ForeignKey(CertificateTemplate, on_delete=models.PROTECT, related_name="requests")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="certificate_requests")
    purpose = models.CharField(max_length=255, blank=True, help_text='e.g. "Bank loan", "Passport".')
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    remarks = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="certificate_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    issued_certificate = models.OneToOneField(
        "IssuedCertificate", on_delete=models.SET_NULL, null=True, blank=True, related_name="source_request",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.template.name} request by {self.student.student_id} ({self.status})"


def _new_certificate_number():
    return f"CERT-{timezone.now():%Y%m%d}-{get_random_string(6, allowed_chars='ABCDEFGHJKLMNPQRSTUVWXYZ23456789')}"


class IssuedCertificate(models.Model):
    template = models.ForeignKey(CertificateTemplate, on_delete=models.PROTECT, related_name="issued_certificates")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="issued_certificates")
    certificate_number = models.CharField(max_length=50, unique=True, default=_new_certificate_number)
    verification_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    purpose = models.CharField(max_length=255, blank=True)
    extra_context = models.JSONField(
        default=dict, blank=True,
        help_text="Per-issuance values, e.g. {'reason_for_leaving': '...', 'conduct': 'Good'}.",
    )
    # Frozen at issue time so a later template edit or profile change does not
    # alter a certificate that has already been handed out.
    rendered_title = models.CharField(max_length=255)
    rendered_body = models.TextField()
    issued_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="certificates_issued",
    )
    issued_at = models.DateTimeField(auto_now_add=True)
    is_revoked = models.BooleanField(default=False)
    revoked_reason = models.TextField(blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-issued_at"]

    def __str__(self):
        return f"{self.certificate_number}: {self.template.name} for {self.student.student_id}"

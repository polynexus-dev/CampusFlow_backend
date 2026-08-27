"""
Anti-Ragging undertaking capture — UGC Regulations on Curbing the Menace of
Ragging in Higher Educational Institutions, 2009. The single most-cited
mandatory deliverable under this regulation is a signed student *and*
parent/guardian undertaking, collected at admission and again at the start
of every academic session, each traceable by its own reference number.

Deliberately shaped after BiometricConsentLog (models/face_embedding.py) —
per-record version, timestamp, IP/user-agent audit trail — rather than the
lighter StudentConsent, because this needs a reference number and an
explicit *parent-side* acknowledgment that StudentConsent has no room for.
`parent_guardian_name` is a plain text field rather than a GuardianProfile FK
since the signing parent need not have (or ever create) a system account —
the same reasoning CommitteeMembership.external_member_name uses for POSH's
mandatory external member.
"""
from django.db import models

from .academics import AcademicYear
from .profile import StudentProfile


class AntiRaggingUndertaking(models.Model):
    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="anti_ragging_undertakings",
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.PROTECT, related_name="anti_ragging_undertakings",
        help_text="One undertaking is required per student per session.",
    )
    reference_number = models.CharField(max_length=30, unique=True)
    undertaking_version = models.CharField(max_length=10, default="v1.0")

    student_acknowledged = models.BooleanField(default=False)
    student_acknowledged_at = models.DateTimeField(null=True, blank=True)

    parent_guardian_name = models.CharField(max_length=255, blank=True)
    parent_acknowledged = models.BooleanField(default=False)
    parent_acknowledged_at = models.DateTimeField(null=True, blank=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "anti_ragging_undertakings"
        verbose_name = "Anti-Ragging Undertaking"
        verbose_name_plural = "Anti-Ragging Undertakings"
        ordering = ["-academic_year__start_date", "student__student_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "academic_year"], name="uniq_undertaking_per_student_per_year",
            ),
        ]

    @property
    def is_complete(self):
        """Both signatures present — the audit-ready state. A row can exist
        with only one side signed (e.g. student signs at orientation, parent
        countersigns later), which is exactly the gap the coverage report
        below surfaces."""
        return self.student_acknowledged and self.parent_acknowledged

    def __str__(self):
        return f"{self.student.student_id} — {self.academic_year} ({self.reference_number})"

"""
Fee Regulating Authority (FRA) submissions — closes roadmap gap #9.

Maharashtra's Shikshan Shulka Samiti (Fee Regulating Authority) requires
every professional course to submit its proposed fee for FRA sanction each
academic year before that fee can be charged. This is deliberately a thin
"proposal to regulator" wrapper, not a new source of fee data — the actual
fee figures already live in FeeStructure/FeeStructureItem
(models/fees.py); `fee_structure` here is an optional pointer back to
that so a submission doesn't have to re-enter numbers the ledger module
already computed, while `proposed_fee_amount` stays its own field since
what was actually submitted to the FRA may predate or diverge from the
internal FeeStructure (rates typically get proposed before enrolment,
sanctioned mid-year, and only then finalized internally).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .academics import AcademicYear, Program
from .fees import FeeStructure


class FeeRegulatingAuthoritySubmission(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_REVISION_REQUESTED = "revision_requested"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_REVISION_REQUESTED, "Revision Requested"),
    ]

    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="fra_submissions")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="fra_submissions")
    fee_structure = models.ForeignKey(
        FeeStructure, on_delete=models.SET_NULL, null=True, blank=True, related_name="fra_submissions",
        help_text="Optional link to the internal fee structure this proposal corresponds to.",
    )
    proposed_fee_amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    fra_order_number = models.CharField(
        max_length=100, blank=True, help_text="The FRA's own order/reference number, recorded once decided.",
    )
    sanctioned_fee_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="The FRA-approved figure once decided — may differ from proposed_fee_amount.",
    )
    remarks = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fee Regulating Authority Submission"
        verbose_name_plural = "Fee Regulating Authority Submissions"
        ordering = ["-academic_year__start_date", "program__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "academic_year"], name="uniq_fra_submission_per_program_per_year",
            ),
        ]

    def __str__(self):
        return f"FRA {self.program.code} — {self.academic_year} [{self.status}]"

    def submit(self):
        self.status = self.STATUS_SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "updated_at"])

    def record_decision(self, decision, sanctioned_fee_amount=None, fra_order_number="", remarks=""):
        if decision not in (self.STATUS_APPROVED, self.STATUS_REJECTED, self.STATUS_REVISION_REQUESTED):
            raise ValueError("decision must be approved, rejected, or revision_requested.")
        self.status = decision
        self.decided_at = timezone.now()
        if decision == self.STATUS_APPROVED:
            self.sanctioned_fee_amount = sanctioned_fee_amount
            self.fra_order_number = fra_order_number
        if remarks:
            self.remarks = remarks
        self.save(update_fields=[
            "status", "decided_at", "sanctioned_fee_amount", "fra_order_number", "remarks", "updated_at",
        ])

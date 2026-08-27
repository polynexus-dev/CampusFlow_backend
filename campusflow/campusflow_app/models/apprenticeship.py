"""
NATS (National Apprenticeship Training Scheme) layer — closes roadmap gap
#15. PlacementApplication already tracks who got selected where; what was
missing is everything NATS itself needs once a selection becomes an
apprenticeship: a formal contract, and the recurring monthly stipend claim
against it.

ApprenticeshipContract extends one selected PlacementApplication (one-to-one
— a student either has an apprenticeship contract for that placement or
doesn't) with the employer/establishment/stipend/proof-of-employment
details NATS's own portal asks for.

StipendClaim follows the exact same pending -> approved/rejected +
reviewed_by/reviewed_at request/approval shape as ResultCorrectionRequest
and RevaluationRequest — one row per month, since a stipend claim is
inherently a recurring monthly submission, not a one-off request.
`attendance_percent` is employer-reported and self-declared at claim time
rather than pulled from this system's own Attendance model: an apprentice's
attendance is tracked by the employer off-campus, not by any Lecture this
system schedules.
"""
from django.contrib.auth.models import User
from django.db import models

from .tpo import PlacementApplication


class ApprenticeshipContract(models.Model):
    STATUS_ACTIVE = "active"
    STATUS_COMPLETED = "completed"
    STATUS_TERMINATED = "terminated"
    STATUS_CHOICES = [
        (STATUS_ACTIVE, "Active"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_TERMINATED, "Terminated"),
    ]

    placement_application = models.OneToOneField(
        PlacementApplication, on_delete=models.CASCADE, related_name="apprenticeship_contract",
    )
    employer_name = models.CharField(
        max_length=255,
        help_text="May differ from the drive's company_name if the apprenticeship is routed through a "
                   "different legal entity (a common NATS pattern for large employer groups).",
    )
    establishment_registration_number = models.CharField(
        max_length=100, blank=True, help_text="NATS/BOAT-BOPT establishment registration number.",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    monthly_stipend_amount = models.DecimalField(max_digits=10, decimal_places=2)
    proof_of_employment = models.FileField(upload_to="apprenticeship_contracts/", blank=True, null=True)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_ACTIVE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Apprenticeship Contract"
        verbose_name_plural = "Apprenticeship Contracts"
        ordering = ["-start_date"]

    def __str__(self):
        return f"{self.placement_application.student.student_id} @ {self.employer_name} ({self.get_status_display()})"


class StipendClaim(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    contract = models.ForeignKey(ApprenticeshipContract, on_delete=models.CASCADE, related_name="stipend_claims")
    month = models.PositiveSmallIntegerField(help_text="1-12.")
    year = models.PositiveSmallIntegerField()
    claimed_amount = models.DecimalField(max_digits=10, decimal_places=2)
    attendance_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="Employer-reported attendance for this month — self-declared at claim time, since "
                   "apprentice attendance is tracked by the employer, not this system's own Attendance model.",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="stipend_claims_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Stipend Claim"
        verbose_name_plural = "Stipend Claims"
        ordering = ["-year", "-month"]
        constraints = [
            models.UniqueConstraint(fields=["contract", "month", "year"], name="uniq_stipend_claim_per_month"),
        ]

    def __str__(self):
        return f"{self.contract} — {self.month}/{self.year} ({self.get_status_display()})"

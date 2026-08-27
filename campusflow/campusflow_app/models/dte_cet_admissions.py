"""
DTE/CET admissions — closes roadmap gap #10.

Structurally a second admissions pipeline, not an extension of the existing
one: Lead (models/admissions.py) is a CRM funnel for inquiries a college
sources itself, with no concept of a state-run seat matrix, reservation
quota, or multi-round centralized allotment. A CAP (Centralized Admission
Process) applicant instead arrives already carrying a state-issued CET
score/percentile and an allotment the *state* made, which the institute
only confirms or cancels — a fundamentally different shape than a Lead
progressing through a college's own funnel stages.

`CAPApplicant.lead` is an optional pointer back to a Lead for continuity
when the same person was *also* tracked in the CRM funnel before CAP
allotment happened (a common real-world overlap), not a requirement — most
CAP applicants will have never been a Lead at all.

`CAPAllotment.confirm()`/`cancel()` and the eventual conversion to a real
StudentProfile deliberately mirror Lead's own state-machine shape
(admit()/close()) and LeadConvertToStudentView's exact conversion mechanics
(views/admissions.py) — reusing generate_admission_number/create_pending_user
rather than a second implementation of "how do we turn an admitted
candidate into a system account."

QUOTA_CHOICES is Maharashtra's own reservation-category list (per the
source deck) — a curated CharField, not a hardcoded enum with only Open/SC/
ST/OBC, since the real list (VJ/NT sub-categories, EWS, TFWS, PWD, Defense,
Minority, Management, All-India) is long and state policy occasionally adds
to it.
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .academics import AcademicYear, Program
from .admissions import Lead
from .profile import StudentProfile

QUOTA_CHOICES = [
    ("open", "Open (General)"),
    ("sc", "SC"),
    ("st", "ST"),
    ("vjnt_a", "VJ(A)"),
    ("nt_b", "NT(B)"),
    ("nt_c", "NT(C)"),
    ("nt_d", "NT(D)"),
    ("obc", "OBC"),
    ("sbc", "SBC"),
    ("ews", "EWS"),
    ("tfws", "TFWS (Tuition Fee Waiver Scheme)"),
    ("pwd", "PWD"),
    ("defense", "Defense"),
    ("minority", "Minority"),
    ("management", "Management Quota"),
    ("all_india", "All India (AI)"),
]


class SeatMatrix(models.Model):
    """One quota category's sanctioned intake for one program in one
    academic year — the figure CAP allotment is made against."""

    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="seat_matrix_entries")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="seat_matrix_entries")
    quota_category = models.CharField(max_length=20, choices=QUOTA_CHOICES)
    total_seats = models.PositiveIntegerField()

    class Meta:
        verbose_name = "Seat Matrix Entry"
        verbose_name_plural = "Seat Matrix Entries"
        ordering = ["program__code", "quota_category"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "academic_year", "quota_category"], name="uniq_seat_matrix_entry",
            ),
        ]

    def __str__(self):
        return f"{self.program.code} — {self.get_quota_category_display()}: {self.total_seats} ({self.academic_year})"


class CAPRound(models.Model):
    """One round of the Centralized Admission Process (or an institute-level
    round after CAP rounds close)."""

    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="cap_rounds")
    round_number = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=100, blank=True, help_text='e.g. "CAP Round 1", "Institute Level Round".')
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "CAP Round"
        verbose_name_plural = "CAP Rounds"
        ordering = ["academic_year__start_date", "round_number"]
        constraints = [
            models.UniqueConstraint(fields=["academic_year", "round_number"], name="uniq_cap_round_per_year"),
        ]

    def __str__(self):
        return f"{self.name or f'Round {self.round_number}'} ({self.academic_year})"


class CAPApplicant(models.Model):
    """A candidate participating in state CAP admissions for this college —
    arrives with a state-issued application number and CET score, not
    sourced through this college's own inquiry funnel."""

    lead = models.ForeignKey(
        Lead, on_delete=models.SET_NULL, null=True, blank=True, related_name="cap_applicant",
        help_text="Optional link back to a CRM Lead, if this person was also tracked there.",
    )
    application_number = models.CharField(max_length=50, unique=True, help_text="State CAP application/form number.")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=15, blank=True)
    cet_score = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    cet_percentile = models.DecimalField(max_digits=6, decimal_places=4, null=True, blank=True)
    category = models.CharField(
        max_length=20, choices=QUOTA_CHOICES, blank=True,
        help_text="The candidate's own reservation category, matched against SeatMatrix.quota_category.",
    )
    guardian_name = models.CharField(max_length=255, blank=True)
    guardian_email = models.EmailField(blank=True)
    guardian_phone = models.CharField(max_length=15, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "CAP Applicant"
        verbose_name_plural = "CAP Applicants"
        ordering = ["-cet_percentile"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.application_number})"


class CAPAllotment(models.Model):
    """One applicant's allotment in one CAP round — the state's decision,
    which the institute only confirms or cancels, never originates."""

    STATUS_ALLOTTED = "allotted"
    STATUS_CONFIRMED = "confirmed"
    STATUS_CANCELLED = "cancelled"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [
        (STATUS_ALLOTTED, "Allotted"),
        (STATUS_CONFIRMED, "Confirmed"),
        (STATUS_CANCELLED, "Cancelled"),
        (STATUS_WITHDRAWN, "Withdrawn"),
    ]

    applicant = models.ForeignKey(CAPApplicant, on_delete=models.CASCADE, related_name="allotments")
    cap_round = models.ForeignKey(CAPRound, on_delete=models.CASCADE, related_name="allotments")
    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="cap_allotments")
    quota_category = models.CharField(max_length=20, choices=QUOTA_CHOICES)
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_ALLOTTED)
    allotted_at = models.DateTimeField(auto_now_add=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)
    converted_student = models.ForeignKey(
        StudentProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="from_cap_allotment",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        verbose_name = "CAP Allotment"
        verbose_name_plural = "CAP Allotments"
        ordering = ["-allotted_at"]
        constraints = [
            models.UniqueConstraint(fields=["applicant", "cap_round"], name="uniq_cap_allotment_per_round"),
        ]

    def __str__(self):
        return f"{self.applicant} -> {self.program.code} [{self.status}]"

    def confirm(self):
        if self.status != self.STATUS_ALLOTTED:
            raise ValueError(f"Cannot confirm from status '{self.status}'.")
        self.status = self.STATUS_CONFIRMED
        self.confirmed_at = timezone.now()
        self.save(update_fields=["status", "confirmed_at"])

    def cancel(self, reason=""):
        if self.status not in (self.STATUS_ALLOTTED, self.STATUS_CONFIRMED):
            raise ValueError(f"Cannot cancel from status '{self.status}'.")
        self.status = self.STATUS_CANCELLED
        self.cancelled_at = timezone.now()
        self.cancellation_reason = reason
        self.save(update_fields=["status", "cancelled_at", "cancellation_reason"])

"""
University exam administration layer — closes roadmap gap #18. All three
pieces connect to workflows this codebase already ships rather than
inventing new ones:

- AttendanceDetentionSettings + services/detention.py's is_student_detained
  mirror ClearanceSettings' lazy-singleton "not configured = not blocking"
  shape, and reuse the exact department-scoped Lecture/Attendance join
  services/risk_scoring.py's _attendance_signal already established — just
  windowed to the exam's own Term instead of a rolling 60-day lookback.
- The "exam form + fee remittance gate" needs no model at all: the existing
  ClearanceDesk system already models "a desk that must sign off before a
  student proceeds" (models/clearance.py). A college represents its
  University Exam Fee as a ClearanceDesk and it's already enforced via
  is_student_cleared, the same gate the student exam list already uses.
- RevaluationRequest, MigrationRequest, and ConvocationRequest each follow
  ResultCorrectionRequest's exact pending/approved/rejected +
  reviewed_by/reviewed_at shape (models/result_correction.py) rather than a
  new state machine per request type.
"""
from django.contrib.auth.models import User
from django.db import models

from .academics import AcademicYear
from .profile import StudentProfile
from .result import StudentExamResult

REQUEST_STATUS_PENDING = "pending"
REQUEST_STATUS_APPROVED = "approved"
REQUEST_STATUS_REJECTED = "rejected"
REQUEST_STATUS_CHOICES = [
    (REQUEST_STATUS_PENDING, "Pending"),
    (REQUEST_STATUS_APPROVED, "Approved"),
    (REQUEST_STATUS_REJECTED, "Rejected"),
]


class AttendanceDetentionSettings(models.Model):
    """One row per tenant schema — the college's minimum-attendance rule for
    exam eligibility. Fetched via get_or_create (see services/detention.py),
    same lazy-singleton idiom as ClearanceSettings. Disabled by default: a
    college that hasn't configured this hasn't turned detention on, so
    nothing blocks — the same "silence is not a block" rule ClearanceDesk
    uses for an unconfigured clearance workflow, applied here in the
    opposite direction (unconfigured = not blocking, vs. clearance's
    unconfigured-desks = not blocking either, for the same reason: no
    college should be silently gated by a feature it never set up)."""

    is_enabled = models.BooleanField(default=False)
    minimum_attendance_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=75,
        help_text="A student below this attendance percentage for the exam's term is detained "
                   "(barred from sitting that exam) once is_enabled is True.",
    )
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Attendance Detention Settings"
        verbose_name_plural = "Attendance Detention Settings"

    def __str__(self):
        return f"Detention {'ON' if self.is_enabled else 'off'} @ {self.minimum_attendance_percent}%"


class RevaluationRequest(models.Model):
    """A student requesting their published result be re-checked.
    `revised_marks` is set by the reviewer at approval time (the student
    proposes nothing — unlike ResultCorrectionRequest, where the requesting
    teacher proposes the new mark), and approval applies it to the result
    exactly the way HMCorrectionRequestActionView already does."""

    STATUS_PENDING = REQUEST_STATUS_PENDING
    STATUS_APPROVED = REQUEST_STATUS_APPROVED
    STATUS_REJECTED = REQUEST_STATUS_REJECTED
    STATUS_CHOICES = REQUEST_STATUS_CHOICES

    result = models.ForeignKey(StudentExamResult, on_delete=models.CASCADE, related_name="revaluation_requests")
    requested_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="revaluation_requests_made",
        help_text="The student requesting revaluation of their own result.",
    )
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=REQUEST_STATUS_CHOICES, default=REQUEST_STATUS_PENDING)
    revised_marks = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text="Set by the reviewer on approval; applied to the result the same way "
                   "ResultCorrectionRequest.marks_obtained is.",
    )
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="revaluation_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "revaluation_requests"
        verbose_name = "Revaluation Request"
        verbose_name_plural = "Revaluation Requests"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Revaluation: {self.result} ({self.get_status_display()})"


class MigrationRequest(models.Model):
    """A student requesting a migration certificate to transfer out."""

    STATUS_PENDING = REQUEST_STATUS_PENDING
    STATUS_APPROVED = REQUEST_STATUS_APPROVED
    STATUS_REJECTED = REQUEST_STATUS_REJECTED
    STATUS_CHOICES = REQUEST_STATUS_CHOICES

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="migration_requests")
    destination_institution = models.CharField(max_length=255)
    reason = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=REQUEST_STATUS_CHOICES, default=REQUEST_STATUS_PENDING)
    certificate_number = models.CharField(
        max_length=100, blank=True, help_text="Set by the reviewer once the migration certificate is issued.",
    )
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="migration_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "migration_requests"
        verbose_name = "Migration Request"
        verbose_name_plural = "Migration Requests"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Migration: {self.student.student_id} -> {self.destination_institution} ({self.get_status_display()})"


class ConvocationRequest(models.Model):
    """A student registering to attend convocation and receive their degree
    for a given academic year's ceremony."""

    STATUS_PENDING = REQUEST_STATUS_PENDING
    STATUS_APPROVED = REQUEST_STATUS_APPROVED
    STATUS_REJECTED = REQUEST_STATUS_REJECTED
    STATUS_CHOICES = REQUEST_STATUS_CHOICES

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="convocation_requests")
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name="convocation_requests",
        help_text="Which year's convocation ceremony.",
    )
    remarks = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=REQUEST_STATUS_CHOICES, default=REQUEST_STATUS_PENDING)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="convocation_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "convocation_requests"
        verbose_name = "Convocation Request"
        verbose_name_plural = "Convocation Requests"
        ordering = ["-requested_at"]
        constraints = [
            models.UniqueConstraint(fields=["student", "academic_year"], name="uniq_convocation_request_per_year"),
        ]

    def __str__(self):
        return f"Convocation: {self.student.student_id} — {self.academic_year} ({self.get_status_display()})"

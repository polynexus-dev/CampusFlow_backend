from django.db import models

from .profile import StudentProfile


class StudentRiskScore(models.Model):
    """
    One row per active student — the precomputed dropout/at-risk score.

    Deliberately a cached/stored record, not computed per-request: scoring a
    student joins across Attendance, StudentFeeInvoice, TermGradeSheet/
    StudentExamResult, and AssignmentSubmission, which is too expensive to
    redo on every dashboard GET for every student. Recomputed by the
    `recompute_risk_scores` management command (see
    campusflow_app/services/risk_scoring.py for the scoring logic itself),
    the same "compute periodically, store, serve fast" shape already used by
    TermGradeSheet/StudentAcademicSummary (models/grading.py).
    """

    TIER_LOW = "low"
    TIER_MEDIUM = "medium"
    TIER_HIGH = "high"
    TIER_CHOICES = [
        (TIER_LOW, "Low"),
        (TIER_MEDIUM, "Medium"),
        (TIER_HIGH, "High"),
    ]

    student = models.OneToOneField(
        StudentProfile, on_delete=models.CASCADE, related_name="risk_score",
    )
    computed_at = models.DateTimeField(auto_now=True)
    risk_score = models.FloatField(
        help_text="0-100 composite risk score; higher = more at risk.",
    )
    risk_tier = models.CharField(max_length=10, choices=TIER_CHOICES, default=TIER_LOW)

    # Per-signal breakdown, for dashboard transparency — null when that
    # signal had insufficient data at compute time (see compute_risk_score's
    # graceful-degradation handling).
    attendance_rate = models.FloatField(null=True, blank=True)
    fee_overdue_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    exam_trend_score = models.FloatField(null=True, blank=True)
    assignment_submission_rate = models.FloatField(null=True, blank=True)

    notes = models.TextField(
        blank=True,
        help_text="Human-readable summary of why this student is flagged.",
    )

    class Meta:
        db_table = "student_risk_scores"
        verbose_name = "Student Risk Score"
        verbose_name_plural = "Student Risk Scores"
        ordering = ["-risk_score"]

    def __str__(self):
        return f"{self.student.student_id} — {self.risk_tier} ({self.risk_score:.0f})"

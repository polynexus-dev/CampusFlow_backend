from django.db import models
from django.contrib.auth.models import User
from .department import Department
from .profile import StudentProfile


class PromotionBatch(models.Model):
    """
    A single year-end "promote class" operation: department + from-class ->
    to-class, applied to a set of students in one action. Reversible for a
    limited window (enforced in the view, not here) via the snapshotted
    PromotionRecord rows.
    """
    STATUS_APPLIED = "applied"
    STATUS_REVERTED = "reverted"
    STATUS_CHOICES = [
        (STATUS_APPLIED, "Applied"),
        (STATUS_REVERTED, "Reverted"),
    ]

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="promotion_batches")
    from_semester_year = models.CharField(max_length=50)
    from_section_division = models.CharField(max_length=10, blank=True)
    from_academic_year = models.CharField(max_length=9, blank=True)
    to_semester_year = models.CharField(max_length=50)
    to_section_division = models.CharField(max_length=10, blank=True)
    to_academic_year = models.CharField(max_length=9, blank=True)
    performed_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="promotion_batches_performed")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_APPLIED)
    applied_at = models.DateTimeField(auto_now_add=True)
    reverted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="promotion_batches_reverted",
    )
    reverted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "promotion_batches"
        verbose_name = "Promotion Batch"
        verbose_name_plural = "Promotion Batches"
        ordering = ["-applied_at"]

    def __str__(self):
        return f"{self.from_semester_year}-{self.from_section_division} -> {self.to_semester_year}-{self.to_section_division} ({self.status})"


class PromotionRecord(models.Model):
    """One student's decision within a PromotionBatch, with a snapshot of
    their pre-promotion field values so the batch can be reverted."""
    DECISION_PROMOTE = "promote"
    DECISION_HOLD = "hold"
    DECISION_EXCLUDE = "exclude"
    DECISION_CHOICES = [
        (DECISION_PROMOTE, "Promote"),
        (DECISION_HOLD, "Hold"),
        (DECISION_EXCLUDE, "Exclude"),
    ]

    batch = models.ForeignKey(PromotionBatch, on_delete=models.CASCADE, related_name="records")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="promotion_records")
    decision = models.CharField(max_length=10, choices=DECISION_CHOICES)
    notes = models.TextField(blank=True)
    override_reason = models.TextField(
        blank=True,
        help_text="Set when this student was promoted despite an uncleared clearance request.",
    )

    previous_semester_year = models.CharField(max_length=50, blank=True)
    previous_section_division = models.CharField(max_length=10, blank=True)
    previous_batch_academic_year = models.CharField(max_length=9, blank=True)
    previous_status = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "promotion_records"
        verbose_name = "Promotion Record"
        verbose_name_plural = "Promotion Records"

    def __str__(self):
        return f"{self.student.student_id} · {self.get_decision_display()} (batch {self.batch_id})"

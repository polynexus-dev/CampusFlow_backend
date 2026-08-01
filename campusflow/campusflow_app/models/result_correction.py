from django.db import models
from django.contrib.auth.models import User
from .result import StudentExamResult


class ResultCorrectionRequest(models.Model):
    """
    A teacher requesting to change a student's marks AFTER the exam's
    results have been published. Requires HM (Department Head or above)
    approval — a teacher cannot self-approve a post-publish change.
    """
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    result = models.ForeignKey(StudentExamResult, on_delete=models.CASCADE, related_name="correction_requests")
    requested_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="result_corrections_requested",
        help_text="The teacher requesting the change.",
    )
    proposed_marks = models.DecimalField(max_digits=6, decimal_places=2)
    reason = models.TextField(help_text="Why the published mark needs to change.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="result_corrections_reviewed",
        help_text="The HM (Department Head or above) who approved/rejected this.",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "result_correction_requests"
        verbose_name = "Result Correction Request"
        verbose_name_plural = "Result Correction Requests"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Result Correction: {self.result} → {self.proposed_marks} ({self.get_status_display()})"

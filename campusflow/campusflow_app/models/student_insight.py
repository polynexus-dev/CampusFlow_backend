"""
AI-generated advisory interpretation of a student's already-computed
performance data (see views/progress.py's StudentProgressView and
StudentTopicPerformanceView) — a narrative "here's what this means, here's
what to do next" layer over numbers that are already 100% real.

Deliberately NOT a review-gated draft like AccreditationNarrativeDraft: this
never becomes an "official" record or overwrites anything — it's read-only
advisory text shown alongside the real data, always labeled as AI-generated.
One row per student; a new generation replaces the old snapshot rather than
accumulating a history, since only the latest read is useful.
"""
from django.conf import settings
from django.db import models

from .profile import StudentProfile


class StudentInsightSnapshot(models.Model):
    STATUS_PENDING = "pending"
    STATUS_READY = "ready"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_READY, "Ready"),
        (STATUS_FAILED, "Failed"),
    ]

    student = models.OneToOneField(StudentProfile, on_delete=models.CASCADE, related_name="insight_snapshot")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    generated_at = models.DateTimeField(null=True, blank=True)
    model_used = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    narrative_text = models.TextField(blank=True)
    recommendations = models.JSONField(default=list, blank=True, help_text="Short list of concrete, actionable next steps.")
    error_message = models.TextField(blank=True)

    class Meta:
        verbose_name = "Student Insight Snapshot"
        verbose_name_plural = "Student Insight Snapshots"

    def __str__(self):
        return f"Insight for {self.student.student_id} ({self.status})"

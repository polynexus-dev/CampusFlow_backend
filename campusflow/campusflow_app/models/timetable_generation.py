from django.conf import settings
from django.db import models

from .academics import Term
from .department import Department


class TimetableGenerationRun(models.Model):
    """
    One CP-SAT solve attempt for one Term (optionally narrowed to one
    Department) — see services/timetable_generation.py for the solver and
    the run_generate_timetable Celery task (campusflow_app/tasks.py) that
    drives it. Mirrors AIGradingSuggestion's staging shape and
    PromotionBatch's batch-with-an-apply-step shape: a successful solve
    writes real Schedule rows flagged is_draft=True and linked here via
    Schedule.generation_run, never live Schedule rows directly — a human
    applies (flips them live) or discards the whole batch.
    """

    STATUS_PENDING = "pending"
    STATUS_COMPLETED = "completed"
    STATUS_INFEASIBLE = "infeasible"
    STATUS_FAILED = "failed"
    STATUS_APPLIED = "applied"
    STATUS_DISCARDED = "discarded"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_COMPLETED, "Completed"),
        (STATUS_INFEASIBLE, "Infeasible"),
        (STATUS_FAILED, "Failed"),
        (STATUS_APPLIED, "Applied"),
        (STATUS_DISCARDED, "Discarded"),
    ]

    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="timetable_generation_runs")
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        help_text="Optional — narrows generation to one department's offerings. Unset = whole term.",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    solve_time_seconds = models.FloatField(null=True, blank=True)
    unscheduled_offerings = models.JSONField(
        default=list, blank=True,
        help_text="CourseOffering ids the solver couldn't place, set when status is 'infeasible'.",
    )
    error_message = models.TextField(blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    class Meta:
        db_table = "timetable_generation_runs"
        verbose_name = "Timetable Generation Run"
        verbose_name_plural = "Timetable Generation Runs"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Timetable run for {self.term} ({self.status})"

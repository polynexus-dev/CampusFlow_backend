from django.conf import settings
from django.db import models

from .valuation import ScannedPaper


class AIGradingSuggestion(models.Model):
    """
    One AI-generated grading suggestion for a ScannedPaper, staged for human
    review — never written directly into ScannedPaper.question_scores.

    Lifecycle:
      1. Evaluator triggers POST /scanned-papers/<pk>/ai-suggest/, which
         creates a row here with status='pending' and queues
         `run_ai_grading_suggestion` (see campusflow_app/tasks.py).
      2. The task calls the local Ollama model (campusflow_app/ai_grading.py) and fills in
         `question_scores_suggested`/`overall_confidence`/`overall_notes` on
         success, or `error_message` and status='failed' on failure. It
         never touches ScannedPaper itself.
      3. The evaluator reviews the suggestion and either applies it
         (POST /ai-suggestions/<pk>/apply/ — copies scores into the paper
         and marks it Evaluated) or rejects it.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("applied", "Applied"),
        ("rejected", "Rejected"),
        ("failed", "Failed"),
    ]

    scanned_paper = models.ForeignKey(
        ScannedPaper, on_delete=models.CASCADE, related_name="ai_suggestions",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    model_used = models.CharField(max_length=100, blank=True)
    question_scores_suggested = models.JSONField(
        default=dict, blank=True,
        help_text="Per-question AI suggestion, e.g. "
                   "{'Q1': {'score': 8, 'max_marks': 10, 'rationale': '...', 'confidence': 0.82}}",
    )
    overall_confidence = models.FloatField(null=True, blank=True)
    overall_notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    error_message = models.TextField(blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    class Meta:
        db_table = "ai_grading_suggestions"
        verbose_name = "AI Grading Suggestion"
        verbose_name_plural = "AI Grading Suggestions"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"AI suggestion for {self.scanned_paper} ({self.status})"

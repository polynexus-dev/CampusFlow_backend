from django.conf import settings
from django.db import models

from .compliance import AccreditationCriterion
from .finance import FinancialYear


class AccreditationNarrativeDraft(models.Model):
    """
    An LLM-drafted SSR/AQAR criterion write-up, staged for human review —
    same human-in-the-loop shape as AIGradingSuggestion (models/ai_grading.py):
    the AI never writes into anything considered "official"; it drafts into
    this row, an IQAC reviewer edits `narrative_text` (unlike a grading
    suggestion, editing prose is the expected normal path here, so this
    field stays writable rather than being locked read-only), and explicitly
    applies it. SSRExportView surfaces the latest applied draft per
    criterion+year — that's the only place this touches "official" output.

    Lifecycle:
      1. POST .../narrative-draft/ creates a row with status="pending" and
         queues `run_accreditation_narrative_draft` (see tasks.py).
      2. The task calls the local Ollama model (campusflow_app/ai_narrative.py) and fills in
         narrative_text/caveats on success, or error_message and
         status="failed" on failure. It never touches AccreditationCriterion
         or EvidenceItem.
      3. A reviewer edits narrative_text as needed, then applies
         (status="applied", applied_at/applied_by) or rejects it.
    """

    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("applied", "Applied"),
        ("rejected", "Rejected"),
        ("failed", "Failed"),
    ]

    criterion = models.ForeignKey(
        AccreditationCriterion, on_delete=models.CASCADE, related_name="narrative_drafts",
    )
    financial_year = models.ForeignKey(
        FinancialYear, on_delete=models.CASCADE, related_name="narrative_drafts",
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )
    requested_at = models.DateTimeField(auto_now_add=True)
    model_used = models.CharField(max_length=100, blank=True)
    narrative_text = models.TextField(
        blank=True,
        help_text="The draft/final SSR write-up — human-editable at any time, before or after apply.",
    )
    caveats = models.TextField(
        blank=True,
        help_text="AI-flagged gaps, e.g. 'no evidence found for sub-metric X'.",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    error_message = models.TextField(blank=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    class Meta:
        db_table = "accreditation_narrative_drafts"
        verbose_name = "Accreditation Narrative Draft"
        verbose_name_plural = "Accreditation Narrative Drafts"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Narrative for {self.criterion} — {self.financial_year} ({self.status})"

from django.contrib.auth.models import User
from django.db import models

from .lecture import Lecture
from .offerings import CourseOffering
from .question_bank import SyllabusTopic


class SyllabusCoverageEntry(models.Model):
    """
    Current coverage state of one (CourseOffering x SyllabusTopic) pair — a
    checklist row, not an append-only log. Anchored to CourseOffering rather
    than bare Course+Term because an offering already carries faculty and
    section, which is the granularity "did *this* teacher cover *this*
    topic in *this* section" actually needs — two sections of the same
    course taught by different faculty must not share one ambiguous row.
    """
    STATUS_NOT_STARTED = "not_started"
    STATUS_IN_PROGRESS = "in_progress"
    STATUS_COVERED = "covered"
    STATUS_CHOICES = [
        (STATUS_NOT_STARTED, "Not Started"),
        (STATUS_IN_PROGRESS, "In Progress"),
        (STATUS_COVERED, "Covered"),
    ]

    offering = models.ForeignKey(
        CourseOffering, on_delete=models.CASCADE, related_name="syllabus_coverage_entries",
    )
    topic = models.ForeignKey(
        SyllabusTopic, on_delete=models.CASCADE, related_name="coverage_entries",
    )
    status = models.CharField(max_length=15, choices=STATUS_CHOICES, default=STATUS_NOT_STARTED)
    covered_on = models.DateField(
        null=True, blank=True,
        help_text="Date this topic was actually taught. Set when status moves to in_progress/covered.",
    )
    # Optional provenance link to the actual class session — nullable because
    # faculty may log coverage without a matching Lecture row existing for
    # every topic (Lecture has no course/topic field of its own to derive this from).
    lecture = models.ForeignKey(
        Lecture, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="syllabus_coverage_entries",
    )
    remarks = models.TextField(blank=True, help_text="e.g. why a topic took longer, or was skipped/deferred.")
    updated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="syllabus_coverage_updates",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "syllabus_coverage_entries"
        verbose_name = "Syllabus Coverage Entry"
        verbose_name_plural = "Syllabus Coverage Entries"
        ordering = ["topic__order", "topic__name"]
        constraints = [
            models.UniqueConstraint(fields=["offering", "topic"], name="uniq_offering_topic_coverage"),
        ]
        indexes = [
            models.Index(fields=["offering", "status"]),
        ]

    def __str__(self):
        return f"{self.offering} · {self.topic.name} ({self.get_status_display()})"

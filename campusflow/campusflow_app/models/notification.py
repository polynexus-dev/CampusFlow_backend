from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class Notification(models.Model):
    """
    Generic in-app notification inbox. Any workstream (bus events, homework
    posts, marks publish, correction approvals, ...) creates rows here via
    campusflow_app.services.notifications instead of building its own
    per-feature notification plumbing.
    """
    recipient = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="notifications",
    )
    title = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    category = models.CharField(
        max_length=50,
        help_text="e.g. bus_boarding, bus_alighting, bus_missing, homework, marks_published",
    )
    data = models.JSONField(default=dict, blank=True, help_text="Deep-link payload, e.g. {trip_id, student_id}")
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["recipient", "is_read"]),
        ]

    def __str__(self):
        return f"{self.recipient.username} · {self.category} · {self.title}"

from django.db import models
from django.contrib.auth.models import User


class AuditLog(models.Model):
    """
    Tracks every mutating action (CREATE, UPDATE, DELETE) across
    the entire tenant schema for compliance and admin visibility.
    """
    ACTION_CHOICES = [
        ('CREATE', 'Create'),
        ('UPDATE', 'Update'),
        ('DELETE', 'Delete'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs',
        help_text="The user who performed the action."
    )
    action = models.CharField(
        max_length=10, choices=ACTION_CHOICES,
        help_text="The type of action performed."
    )
    model_name = models.CharField(
        max_length=100,
        help_text="The Django model affected (e.g. 'Lecture', 'LeaveRequest')."
    )
    object_id = models.CharField(
        max_length=50, blank=True, null=True,
        help_text="Primary key of the affected object."
    )
    object_repr = models.CharField(
        max_length=500, blank=True, null=True,
        help_text="String representation of the object at the time of action."
    )
    changes = models.JSONField(
        default=dict, blank=True,
        help_text="JSON diff of changes: {field: {old: ..., new: ...}}"
    )
    ip_address = models.GenericIPAddressField(
        null=True, blank=True,
        help_text="IP address of the requester."
    )
    user_agent = models.CharField(
        max_length=500, blank=True, null=True,
        help_text="Browser/device user agent string."
    )
    endpoint = models.CharField(
        max_length=500, blank=True, null=True,
        help_text="The API endpoint that was called."
    )
    timestamp = models.DateTimeField(
        auto_now_add=True, db_index=True,
        help_text="When the action occurred."
    )

    class Meta:
        verbose_name = "Audit Log"
        verbose_name_plural = "Audit Logs"
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.action}] {self.model_name} #{self.object_id} by {self.user} at {self.timestamp}"

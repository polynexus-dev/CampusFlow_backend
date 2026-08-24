from django.db import models
from django.contrib.auth.models import User


class AuditLog(models.Model):
    """
    Tracks every mutating action (CREATE, UPDATE, DELETE) across the entire
    tenant schema, plus account-level LOGIN/LOGIN_FAILED/LOGOUT events, for
    compliance and admin visibility — see log_account_event() below for the
    latter, written directly from the auth flow rather than a model signal
    (a login doesn't save the User row, so signals.py's post_save hook never
    fires for it).
    """
    ACTION_CHOICES = [
        ('CREATE', 'Create'),
        ('UPDATE', 'Update'),
        ('DELETE', 'Delete'),
        ('LOGIN', 'Login'),
        ('LOGIN_FAILED', 'Login failed'),
        ('LOGOUT', 'Logout'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs',
        help_text="The user who performed the action."
    )
    action = models.CharField(
        max_length=15, choices=ACTION_CHOICES,
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


def log_account_event(user, action, request=None, ip_address=None, user_agent=None, object_repr=""):
    """
    Best-effort write of a LOGIN / LOGIN_FAILED / LOGOUT event. Never raises —
    a logging failure must never break sign-in or sign-out. Callers that
    already extracted client_ip/user_agent (e.g. the login serializer's
    device-info parsing) should pass them through directly rather than
    re-deriving from request.META.
    """
    try:
        if request is not None:
            if ip_address is None:
                xff = request.META.get('HTTP_X_FORWARDED_FOR')
                ip_address = xff.split(',')[0].strip() if xff else request.META.get('REMOTE_ADDR')
            if user_agent is None:
                user_agent = request.META.get('HTTP_USER_AGENT', '')
            endpoint = request.path[:500]
        else:
            endpoint = None

        AuditLog.objects.create(
            user=user,
            action=action,
            model_name='User',
            object_id=str(user.id) if user else None,
            object_repr=(object_repr or getattr(user, 'username', '') or '')[:500],
            ip_address=ip_address,
            user_agent=(user_agent or '')[:500],
            endpoint=endpoint,
        )
    except Exception:
        pass

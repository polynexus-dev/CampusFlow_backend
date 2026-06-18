from django.db import models
from django.contrib.auth.models import User
from .department import Department


class Announcement(models.Model):
    """
    College-wide broadcast system with optional department/role targeting.
    Supports priority levels, pinning, and auto-expiry.
    """
    PRIORITY_CHOICES = [
        ('low', 'Low'),
        ('normal', 'Normal'),
        ('high', 'High'),
        ('urgent', 'Urgent'),
    ]

    title = models.CharField(max_length=255)
    content = models.TextField(help_text="Full announcement body text.")
    author = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='announcements_authored',
        help_text="The user who created this announcement."
    )
    priority = models.CharField(
        max_length=10, choices=PRIORITY_CHOICES, default='normal',
        help_text="Visual priority level of the announcement."
    )
    target_roles = models.JSONField(
        default=list, blank=True,
        help_text="List of role names this announcement targets. Empty = all roles. e.g. ['student', 'Faculty']"
    )
    target_departments = models.ManyToManyField(
        Department, blank=True,
        related_name='announcements',
        help_text="Departments this announcement targets. Empty = all departments."
    )
    is_pinned = models.BooleanField(
        default=False,
        help_text="Pinned announcements always appear at the top."
    )
    expires_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Auto-hide announcement after this datetime. Null = never expires."
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Announcement"
        verbose_name_plural = "Announcements"
        ordering = ['-is_pinned', '-created_at']

    def __str__(self):
        return f"[{self.get_priority_display()}] {self.title}"

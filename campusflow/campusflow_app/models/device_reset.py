from django.db import models
from django.contrib.auth.models import User
from .profile import StudentProfile

class DeviceResetRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='device_resets')
    requested_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reason = models.TextField(help_text="Reason for changing their mobile device.")
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_device_resets',
        help_text="The admin or staff who approved/rejected this request."
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Device Reset Request"
        verbose_name_plural = "Device Reset Requests"

    def __str__(self):
        return f"Reset Request: {self.student} ({self.get_status_display()})"

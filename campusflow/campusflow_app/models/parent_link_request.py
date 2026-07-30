from django.db import models
from django.contrib.auth.models import User
from .profile import StudentProfile


class ParentLinkRequest(models.Model):
    """
    A guardian requesting to link to a student WITHOUT the instant
    self-verification ParentLinkChildView offers (DOB/admission number) —
    this is the admin-reviewed path, used when the requester can't supply
    that shared secret, with a phone-mismatch fraud signal for the admin.
    """
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_ID_REQUESTED = "id_requested"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_ID_REQUESTED, "ID Requested"),
    ]

    requested_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="parent_link_requests")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="link_requests")
    claimed_relationship = models.CharField(max_length=50, blank=True, help_text="e.g. Father, Mother, Guardian")
    contact_phone = models.CharField(max_length=15, blank=True)
    phone_mismatch = models.BooleanField(
        default=False,
        help_text="True if contact_phone doesn't match any guardian already linked to this student.",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    admin_note = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="parent_link_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "parent_link_requests"
        verbose_name = "Parent Link Request"
        verbose_name_plural = "Parent Link Requests"
        ordering = ["-requested_at"]

    def __str__(self):
        return f"Link Request: {self.requested_by} -> {self.student} ({self.get_status_display()})"

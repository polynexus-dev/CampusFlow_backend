from django.db import models
from django.contrib.auth.models import User
from .profile import StudentProfile
from .lecture import Lecture


class AttendanceCorrectionRequest(models.Model):
    """
    A GUARDIAN disputing a student's marked-absent lecture, reviewed by the
    teacher/HM. Distinct from ManualAttendanceRequest, which is the
    student's own same-day "I couldn't face-scan" self-service request.
    """
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_HALF_DAY = "half_day"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_HALF_DAY, "Half Day"),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="attendance_correction_requests")
    lecture = models.ForeignKey(Lecture, on_delete=models.CASCADE, related_name="attendance_correction_requests")
    requested_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name="attendance_corrections_requested",
        help_text="The guardian user who filed this dispute.",
    )
    reason = models.TextField(help_text="Guardian's explanation for why the absence is disputed.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="attendance_corrections_reviewed",
        help_text="The teacher/HM who approved/rejected/half-dayed this request.",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    requested_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "attendance_correction_requests"
        verbose_name = "Attendance Correction Request"
        verbose_name_plural = "Attendance Correction Requests"
        constraints = [
            models.UniqueConstraint(
                fields=["student", "lecture"],
                name="unique_student_lecture_correction_request",
            )
        ]

    def __str__(self):
        return f"Correction Request: {self.student} for {self.lecture} ({self.get_status_display()})"

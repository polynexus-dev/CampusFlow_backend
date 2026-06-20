from django.db import models
from django.contrib.auth.models import User
from .profile import StudentProfile
from .lecture import Lecture

class ManualAttendanceRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='manual_attendance_requests')
    lecture = models.ForeignKey(Lecture, on_delete=models.CASCADE, related_name='manual_attendance_requests')
    requested_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(help_text="Reason student is requesting manual attendance.")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    reviewed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='reviewed_attendance_requests',
        help_text="The lecturer who approved/rejected this request."
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "manual_attendance_requests"
        verbose_name = "Manual Attendance Request"
        verbose_name_plural = "Manual Attendance Requests"
        # Avoid duplicate requests for the same student + lecture
        constraints = [
            models.UniqueConstraint(
                fields=["student", "lecture"],
                name="unique_student_lecture_manual_request"
            )
        ]

    def __str__(self):
        return f"Manual Request: {self.student} for {self.lecture} ({self.get_status_display()})"

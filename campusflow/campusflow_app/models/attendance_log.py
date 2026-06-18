from django.db import models
from .profile import StudentProfile
from .lecture import Lecture

class FaceAttendanceLog(models.Model):
    """
    Records the outcome of a single face attendance verification attempt.
    Stores the confidence score and liveness check result for audit.
    """

    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="face_attendance_logs",
    )
    lecture = models.ForeignKey(
        Lecture,
        on_delete=models.CASCADE,
        related_name="face_attendance_logs",
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    confidence_score = models.FloatField(
        help_text="Highest cosine similarity score from the face match."
    )
    is_verified = models.BooleanField(
        default=False,
        help_text="True if confidence >= threshold AND liveness passed.",
    )
    liveness_passed = models.BooleanField(
        default=False,
        help_text="True if the anti-spoofing check passed.",
    )

    class Meta:
        db_table = "face_attendance_logs"
        verbose_name = "Face Attendance Log"
        verbose_name_plural = "Face Attendance Logs"
        ordering = ["-timestamp"]
        # Prevent duplicate attendance logs for same student + lecture
        constraints = [
            models.UniqueConstraint(
                fields=["student", "lecture"],
                name="unique_student_lecture_face_attendance",
            )
        ]

    def __str__(self):
        status = "✓" if self.is_verified else "✗"
        return f"{status} {self.student} — {self.lecture} ({self.confidence_score:.2f})"

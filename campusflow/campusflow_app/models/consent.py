from django.db import models
from django.contrib.auth.models import User
from .profile import StudentProfile


class StudentConsent(models.Model):
    """
    Unified consent tracking for the admin enrollment/consent dashboard.
    Separate from BiometricConsentLog (face_embedding.py), which remains the
    actual enforcement mechanism inside the face-attendance pipeline — this
    model is a lighter, admin-facing record of the three consent types the
    enrollment screen shows.
    """
    TYPE_APP_NOTIFICATIONS = "app_notifications"
    TYPE_BUS_GPS = "bus_gps"
    TYPE_FACE_RECOGNITION = "face_recognition"
    TYPE_CHOICES = [
        (TYPE_APP_NOTIFICATIONS, "App notifications & academic records"),
        (TYPE_BUS_GPS, "Bus GPS tracking & boarding alerts"),
        (TYPE_FACE_RECOGNITION, "Face recognition for attendance"),
    ]

    REQUIREMENT_REQUIRED = "required"
    REQUIREMENT_OPT_IN = "opt_in"
    REQUIREMENT_CHOICES = [
        (REQUIREMENT_REQUIRED, "Required"),
        (REQUIREMENT_OPT_IN, "Opt-in"),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="consents")
    consent_type = models.CharField(max_length=30, choices=TYPE_CHOICES)
    requirement = models.CharField(max_length=10, choices=REQUIREMENT_CHOICES)
    is_granted = models.BooleanField(default=False)
    granted_at = models.DateTimeField(null=True, blank=True)
    granted_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="consents_granted",
        help_text="The guardian (or admin) who granted this consent.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "student_consents"
        verbose_name = "Student Consent"
        verbose_name_plural = "Student Consents"
        constraints = [
            models.UniqueConstraint(fields=["student", "consent_type"], name="unique_student_consent_type")
        ]

    def __str__(self):
        return f"{self.student.student_id} · {self.get_consent_type_display()} · {'granted' if self.is_granted else 'pending'}"

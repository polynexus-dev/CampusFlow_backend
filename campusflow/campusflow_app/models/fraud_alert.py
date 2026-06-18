from django.db import models
from .profile import StudentProfile
from .lecture import Lecture

class FraudAlert(models.Model):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='fraud_alerts')
    lecture = models.ForeignKey(Lecture, on_delete=models.CASCADE, related_name='fraud_alerts')
    attempted_at = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=255, help_text="Reason for the fraud warning (e.g. Failed Liveness, Spoof Attempt)")
    confidence_score = models.FloatField(help_text="Cosine similarity score during the attempt.")
    captured_image = models.ImageField(upload_to="fraud_attempts/", null=True, blank=True, help_text="Captured frame of the suspicious attempt.")

    class Meta:
        verbose_name = "Fraud Alert"
        verbose_name_plural = "Fraud Alerts"

    def __str__(self):
        return f"Fraud Alert: {self.student} at {self.lecture} ({self.reason})"

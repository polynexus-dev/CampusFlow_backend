from django.db import models
from django.contrib.auth.models import User
from .lecture import Lecture

class AttendanceSession(models.Model):
    lecture = models.OneToOneField(Lecture, on_delete=models.CASCADE, related_name='active_session')
    started_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='started_sessions')
    started_at = models.DateTimeField(auto_now_add=True)
    duration_minutes = models.PositiveIntegerField(default=5)
    extended_minutes = models.PositiveIntegerField(default=0)
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    radius_meters = models.PositiveIntegerField(default=100)
    tolerance_meters = models.PositiveIntegerField(default=15)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Attendance Session"
        verbose_name_plural = "Attendance Sessions"

    def __str__(self):
        return f"Session for {self.lecture} by {self.started_by.username} ({'Active' if self.is_active else 'Inactive'})"

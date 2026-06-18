from django.db import models
from django.contrib.auth.models import User
from .schedule import Schedule
from .lecture import Lecture

# Attendance Record Model (supporting dynamic geofence & lecture tracking)
class Attendance(models.Model):
    VERIFICATION_METHODS = [
        ('face_geofence', 'Face + Geofence'),
        ('manual', 'Manual Roll Call'),
    ]

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # For lecture attendance, link to the specific schedule entry
    schedule = models.ForeignKey(Schedule, on_delete=models.SET_NULL, null=True, blank=True,
                                 help_text="For lecture attendance, refers to the specific scheduled class.")
    lecture = models.ForeignKey(Lecture, on_delete=models.SET_NULL, null=True, blank=True,
                                help_text="For specific lecture sessions.")
    check_in_time = models.DateTimeField(auto_now_add=True)
    check_out_time = models.DateTimeField(null=True, blank=True, help_text="Time of checkout (mainly for teaching staff).")
    is_geofence_valid = models.BooleanField(default=False)
    device_id = models.CharField(max_length=255, null=True, blank=True, help_text="ID of the device used for this check-in")
    verification_method = models.CharField(
        max_length=20,
        choices=VERIFICATION_METHODS,
        default='face_geofence',
        help_text="The method used to verify attendance."
    )

    class Meta:
        verbose_name = "Attendance"
        verbose_name_plural = "Attendance Records"
        # Ensure a user has a single attendance record per lecture session
        unique_together = ('user', 'lecture')

    def __str__(self):
        return f"{self.user.username} - {self.get_verification_method_display()} at {self.check_in_time.strftime('%Y-%m-%d %H:%M')}"
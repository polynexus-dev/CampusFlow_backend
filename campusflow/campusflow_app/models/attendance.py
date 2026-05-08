from django.db import models
from django.contrib.auth.models import User
from .location import Location
from .schedule import Schedule
from .lecture import Lecture
# This model tracks attendance records for users, including their check-in times and locations.


# Attendance Record Model
class Attendance(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    # The location_id here refers to the QR code location that was used for initial entry (premises or zone)
    scanned_location = models.ForeignKey(Location, on_delete=models.CASCADE, null=True, blank=True)
    # For lecture attendance, link to the specific schedule entry
    schedule = models.ForeignKey(Schedule, on_delete=models.SET_NULL, null=True, blank=True,
                                 help_text="For lecture attendance, refers to the specific scheduled class.")
    lecture = models.ForeignKey(Lecture, on_delete=models.SET_NULL, null=True, blank=True,
                                help_text="For specific lecture sessions.")
    check_in_time = models.DateTimeField(auto_now_add=True)
    is_geofence_valid = models.BooleanField(default=False)
    device_id = models.CharField(max_length=255, null=True, blank=True, help_text="ID of the device used for this check-in")
  
    attendance_type = models.CharField(max_length=20)

    class Meta:
        verbose_name = "Attendance"
        verbose_name_plural = "Attendance Records"
        # Ensure a user can only check-in once per schedule per day (or per specific type if needed)
        # For 'lecture_checkin', ensure unique per user-schedule-date
        # For 'premises_entry', ensure unique per user-location-date
        unique_together = ('user', 'scanned_location', 'schedule', 'check_in_time') # More complex unique constraints might be needed based on exact business rules

    def __str__(self):
        return f"{self.user.username} - {self.get_attendance_type_display()} at {self.check_in_time.strftime('%Y-%m-%d %H:%M')}"
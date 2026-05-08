from django.db import models
from ..models.department import Department


# Location Model for QR codes (e.g., premises entrance, building zone) — scoped per tenant schema
class Location(models.Model):
    location_id = models.CharField(
        max_length=50, unique=True, help_text="Unique ID for the QR Code / Location")
    name = models.CharField(
        max_length=255, help_text="Descriptive name of the location (e.g., Main Entrance, Block A Entrance)")
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    geofence_radius_meters = models.PositiveIntegerField(
        default=50, help_text="Geofence radius in meters for this location")
    is_premises_entry = models.BooleanField(
        default=False, help_text="True if this location is for initial premises entry")
    is_classroom_entry = models.BooleanField(
        default=False, help_text="True if this location is for classroom entry (lecture attendance)")
    department_owner = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='owned_locations',
                                         help_text="Department responsible for this location (e.g., a lab owned by Physics Dept)")

    class Meta:
        verbose_name = "Location"
        verbose_name_plural = "Locations"

    def __str__(self):
        return f"{self.name} ({self.location_id})"

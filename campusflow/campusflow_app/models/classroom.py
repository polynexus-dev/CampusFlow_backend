# from django.contrib.gis.db import models as gis_models  # Commented out - requires GDAL
from django.db import models
from ..models.location import Location


class Classroom(models.Model):
    name = models.CharField(max_length=255)
    # polygon = gis_models.PolygonField(
    #     srid=4326, help_text="Classroom boundary by four (lat, lon) corners")
    code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    # Optional: link entrypoint location
    main_entry_location = models.ForeignKey(
        Location,   # adjust import as needed
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='classroom_main_entry'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    # ── ADVANCED GEOFENCING (Bounding Box) ──
    # Top-Right and Bottom-Left coordinates define the rectangular boundary.
    # A 5-10 meter buffer should be added during verification to account for GPS drift.
    
    # top_right_lat = models.FloatField(null=True, blank=True)
    # top_right_lon = models.FloatField(null=True, blank=True)
    # bottom_left_lat = models.FloatField(null=True, blank=True)
    # bottom_left_lon = models.FloatField(null=True, blank=True)


    def __str__(self):
        return self.name

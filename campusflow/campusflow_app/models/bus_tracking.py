from django.db import models
from django.contrib.auth import get_user_model

User = get_user_model()


class BusRoute(models.Model):
    """
    A college bus route with named stops.
    Admin defines the route; a bus driver is assigned to it.
    """
    name = models.CharField(max_length=255, help_text="e.g. Route 1 - Wardha Road")
    driver = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_bus_routes",
        help_text="The staff user who drives this bus",
    )
    stops = models.JSONField(
        default=list,
        help_text='List of stops: [{"name": "Stop Name", "lat": 0.0, "lng": 0.0}]',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bus Route"
        verbose_name_plural = "Bus Routes"

    def __str__(self):
        return self.name


class BusLocation(models.Model):
    """
    Stores the LAST KNOWN live location of a bus driver.
    Only one row per user (upserted on every GPS update).
    """
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="bus_current_location",
    )
    lat = models.FloatField()
    lng = models.FloatField()
    route = models.ForeignKey(
        BusRoute,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="live_locations",
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Bus Live: {self.user.get_full_name()} @ ({self.lat}, {self.lng})"


class BusTrail(models.Model):
    """
    Breadcrumb history for bus route replay.
    One new row per meaningful GPS movement (>= 8m apart).
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bus_trails",
    )
    route = models.ForeignKey(
        BusRoute,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trails",
    )
    lat = models.FloatField()
    lng = models.FloatField()
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["timestamp"]
        indexes = [
            models.Index(fields=["user", "timestamp"]),
        ]

    def __str__(self):
        return f"Trail: {self.user.username} @ {self.timestamp}"

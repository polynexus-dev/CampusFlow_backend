import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone

User = get_user_model()


class BusRoute(models.Model):
    """
    A college bus route with named stops.
    Admin defines the route; a bus driver is assigned to it.
    Each route has a unique QR token used for student boarding scan.
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
    # Unique token embedded in the QR code — regenerating this invalidates old printed QRs
    qr_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="Unique token for QR code generation. Regenerate to invalidate printed QRs.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bus Route"
        verbose_name_plural = "Bus Routes"

    def __str__(self):
        return self.name

    def regenerate_qr_token(self):
        """Call this to invalidate all existing printed QR codes for this route."""
        self.qr_token = uuid.uuid4()
        self.save(update_fields=["qr_token"])


class BusSubscription(models.Model):
    """
    Records which students are subscribed (paid bus fees) for a route.
    Only subscribed students can board (scan QR).
    """
    STATUS_ACTIVE = "active"
    STATUS_EXPIRED = "expired"
    STATUS_SUSPENDED = "suspended"
    STATUS_CHOICES = [
        (STATUS_ACTIVE,    "Active"),
        (STATUS_EXPIRED,   "Expired"),
        (STATUS_SUSPENDED, "Suspended"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bus_subscriptions",
    )
    route = models.ForeignKey(
        BusRoute,
        on_delete=models.CASCADE,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_ACTIVE,
    )
    valid_from = models.DateField(default=timezone.localdate)
    valid_until = models.DateField(
        null=True,
        blank=True,
        help_text="Leave blank for no expiry",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, help_text="e.g. Semester 1 fees paid")

    class Meta:
        verbose_name = "Bus Subscription"
        verbose_name_plural = "Bus Subscriptions"
        unique_together = [("user", "route")]   # one active subscription per user per route

    def __str__(self):
        return f"{self.user.get_full_name()} → {self.route.name} ({self.status})"

    @property
    def is_valid(self):
        today = timezone.localdate()
        if self.status != self.STATUS_ACTIVE:
            return False
        if self.valid_from > today:
            return False
        if self.valid_until and self.valid_until < today:
            return False
        return True


class BusAttendance(models.Model):
    """
    Records each bus boarding event (QR scan).
    One record per user per route per day.
    """
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bus_attendance",
    )
    route = models.ForeignKey(
        BusRoute,
        on_delete=models.CASCADE,
        related_name="attendance_records",
    )
    scanned_at = models.DateTimeField(auto_now_add=True)
    device_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        help_text="Device fingerprint to prevent proxy scanning",
    )

    class Meta:
        verbose_name = "Bus Attendance"
        verbose_name_plural = "Bus Attendance"
        indexes = [
            models.Index(fields=["user", "route", "scanned_at"]),
        ]

    def __str__(self):
        return f"{self.user.get_full_name()} boarded {self.route.name} @ {self.scanned_at}"


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


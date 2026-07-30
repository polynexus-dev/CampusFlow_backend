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
    conductor = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_conductor_bus_routes",
        help_text="The staff user who acts as conductor on this bus",
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
    boarding_stop = models.CharField(
        max_length=255,
        blank=True,
        help_text="Name of the stop where student boards the bus (e.g. Wardha Road stop)",
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


class BusTrip(models.Model):
    """
    A single discrete trip, delineated by the driver tapping
    "Start Active Trip" / "End Trip" in the Conductor Panel.
    Powers the driver's weekly/monthly trip-count and distance stats.
    """
    TYPE_PICKUP = "pickup"
    TYPE_DROP = "drop"
    TYPE_CHOICES = [
        (TYPE_PICKUP, "Morning Pickup"),
        (TYPE_DROP, "Evening Drop"),
    ]

    driver = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="bus_trips",
    )
    route = models.ForeignKey(
        BusRoute,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="trips",
    )
    trip_type = models.CharField(max_length=10, choices=TYPE_CHOICES, default=TYPE_PICKUP)
    started_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    distance_km = models.FloatField(default=0.0)

    # Per-trip summary, populated by BusTripEndView once the trip closes.
    expected_count = models.PositiveIntegerField(default=0)
    boarded_count = models.PositiveIntegerField(default=0)
    missing_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        status = "in progress" if not self.ended_at else f"{self.distance_km} km"
        return f"Trip by {self.driver.username} @ {self.started_at} ({status})"


class BusScanEvent(models.Model):
    """
    One row per conductor scan of a student's ID-card QR — boarding in the
    morning, alighting in the evening. Distinct from BusAttendance (which
    records a STUDENT scanning the BUS's own QR to self-check-in); this is
    the CONDUCTOR scanning the STUDENT's ID card, with a typed outcome.

    A `missing` row is system-generated at trip-end for any subscribed
    student who never got a `boarded` scan — it has no real scan behind it.
    """
    DIRECTION_BOARD = "board"
    DIRECTION_ALIGHT = "alight"
    DIRECTION_CHOICES = [
        (DIRECTION_BOARD, "Board"),
        (DIRECTION_ALIGHT, "Alight"),
    ]

    STATUS_BOARDED = "boarded"
    STATUS_ALIGHTED = "alighted"
    STATUS_WRONG_ROUTE = "wrong_route"
    STATUS_NOT_SUBSCRIBED = "not_subscribed"
    STATUS_ALREADY_SCANNED = "already_scanned"
    STATUS_UNREADABLE = "unreadable"
    STATUS_NO_AUTHORIZED_PICKUP = "no_authorized_pickup"
    STATUS_MISSING = "missing"
    STATUS_CHOICES = [
        (STATUS_BOARDED, "Boarded"),
        (STATUS_ALIGHTED, "Alighted"),
        (STATUS_WRONG_ROUTE, "Wrong Route"),
        (STATUS_NOT_SUBSCRIBED, "Not Subscribed"),
        (STATUS_ALREADY_SCANNED, "Already Scanned"),
        (STATUS_UNREADABLE, "Unreadable"),
        (STATUS_NO_AUTHORIZED_PICKUP, "No Authorized Pickup"),
        (STATUS_MISSING, "Missing · Did Not Board"),
    ]

    trip = models.ForeignKey(
        BusTrip,
        on_delete=models.CASCADE,
        related_name="scan_events",
    )
    route = models.ForeignKey(
        BusRoute,
        on_delete=models.CASCADE,
        related_name="scan_events",
    )
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="bus_scan_events",
        help_text="Null when the scanned code could not be resolved to a student (UNREADABLE).",
    )
    scanned_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="conducted_scan_events",
        help_text="The conductor/driver who performed the scan. Null for system-generated MISSING rows.",
    )
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES)
    stop_name = models.CharField(max_length=255, blank=True)
    raw_code = models.CharField(max_length=255, blank=True, help_text="Whatever code was scanned, for audit trail.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Bus Scan Event"
        verbose_name_plural = "Bus Scan Events"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["trip", "direction", "status"]),
            models.Index(fields=["student", "trip"]),
        ]

    def __str__(self):
        who = self.student.get_full_name() if self.student else "unknown"
        return f"{who} · {self.direction} · {self.status} @ {self.created_at}"


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


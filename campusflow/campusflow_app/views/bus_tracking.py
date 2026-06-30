"""
Bus Tracking Views
==================

REST API for the CampusNexus Bus Module:

  Admin endpoints
  ---------------
  GET/POST   /api/bus/routes/                  — List / create routes
  GET/PATCH  /api/bus/routes/<id>/             — Route detail / update / delete
  GET        /api/bus/routes/<id>/qr/          — Download printable QR code PNG
  POST       /api/bus/routes/<id>/regen-qr/    — Regenerate QR token (invalidate old prints)
  GET/POST   /api/bus/subscriptions/           — List / assign student subscriptions
  PATCH/DEL  /api/bus/subscriptions/<id>/      — Update / revoke subscription
  GET        /api/bus/live/                    — Live bus positions (last 12 h)
  GET        /api/bus/trail/<driver_id>/       — Trail history for a bus
  GET        /api/bus/attendance/              — Bus attendance log (filter by route/date)

  Student endpoint
  ----------------
  POST  /api/bus/scan/                         — Scan QR → validate subscription → board
"""

import io
import qrcode
from django.http import HttpResponse
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework import serializers as drf_serializers
from django.utils import timezone
from datetime import timedelta

from campusflow_app.models import (
    BusRoute, BusLocation, BusTrail,
    BusSubscription, BusAttendance,
)
from campusflow_app.permissions import IsSaaSOrCollegeAdmin


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────

class BusRouteSerializer(drf_serializers.ModelSerializer):
    driver_name = drf_serializers.SerializerMethodField()
    subscriber_count = drf_serializers.SerializerMethodField()

    class Meta:
        model = BusRoute
        fields = [
            "id", "name", "driver", "driver_name",
            "stops", "qr_token", "is_active",
            "subscriber_count", "created_at",
        ]
        read_only_fields = ["qr_token", "created_at"]

    def get_driver_name(self, obj):
        if obj.driver:
            return obj.driver.get_full_name() or obj.driver.username
        return None

    def get_subscriber_count(self, obj):
        return obj.subscriptions.filter(status="active").count()


class BusSubscriptionSerializer(drf_serializers.ModelSerializer):
    student_name = drf_serializers.SerializerMethodField()
    route_name   = drf_serializers.SerializerMethodField()
    is_valid     = drf_serializers.SerializerMethodField()

    class Meta:
        model = BusSubscription
        fields = [
            "id", "user", "student_name",
            "route", "route_name",
            "status", "valid_from", "valid_until",
            "boarding_stop", "notes", "is_valid", "created_at",
        ]

        read_only_fields = ["created_at"]

    def get_student_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_route_name(self, obj):
        return obj.route.name

    def get_is_valid(self, obj):
        return obj.is_valid


class BusAttendanceSerializer(drf_serializers.ModelSerializer):
    student_name = drf_serializers.SerializerMethodField()
    route_name   = drf_serializers.SerializerMethodField()

    class Meta:
        model = BusAttendance
        fields = ["id", "user", "student_name", "route", "route_name", "scanned_at", "device_id"]

    def get_student_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_route_name(self, obj):
        return obj.route.name


class BusLiveLocationSerializer(drf_serializers.ModelSerializer):
    driver_name = drf_serializers.SerializerMethodField()
    route_name  = drf_serializers.SerializerMethodField()
    trail       = drf_serializers.SerializerMethodField()
    distance_km = drf_serializers.SerializerMethodField()

    class Meta:
        model = BusLocation
        fields = ["id", "driver_name", "lat", "lng", "route_name", "trail", "distance_km", "updated_at"]

    def get_driver_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_route_name(self, obj):
        return obj.route.name if obj.route else None

    def get_trail(self, obj):
        if obj.route:
            trails = BusTrail.objects.filter(user=obj.user, route=obj.route).order_by("timestamp")
        else:
            cutoff = timezone.now() - timedelta(hours=12)
            trails = BusTrail.objects.filter(
                user=obj.user, route__isnull=True, timestamp__gte=cutoff
            ).order_by("timestamp")
        coords = [[t.lat, t.lng] for t in trails]
        unique = []
        for c in coords:
            if not unique or unique[-1] != c:
                unique.append(c)
        return unique

    def get_distance_km(self, obj):
        import math
        trail = self.get_trail(obj)
        if len(trail) < 2:
            return 0.0

        def haversine(la1, ln1, la2, ln2):
            la1, ln1, la2, ln2 = map(math.radians, [la1, ln1, la2, ln2])
            a = math.sin((la2-la1)/2)**2 + math.cos(la1)*math.cos(la2)*math.sin((ln2-ln1)/2)**2
            return 2 * math.asin(math.sqrt(a)) * 6_371_000

        total = sum(haversine(trail[i][0], trail[i][1], trail[i+1][0], trail[i+1][1])
                    for i in range(len(trail)-1))
        return round(total / 1000.0, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Route management (Admin)
# ─────────────────────────────────────────────────────────────────────────────

class BusRouteListCreateView(generics.ListCreateAPIView):
    """GET /api/bus/routes/ — POST /api/bus/routes/"""
    serializer_class   = BusRouteSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get_queryset(self):
        return BusRoute.objects.select_related("driver").prefetch_related("subscriptions").order_by("-created_at")


class BusRouteDetailView(generics.RetrieveUpdateDestroyAPIView):
    """GET/PATCH/DELETE /api/bus/routes/<id>/"""
    serializer_class   = BusRouteSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get_queryset(self):
        return BusRoute.objects.select_related("driver")


# ─────────────────────────────────────────────────────────────────────────────
# QR Code generation (Admin)
# ─────────────────────────────────────────────────────────────────────────────

class BusRouteQRView(APIView):
    """
    GET /api/bus/routes/<id>/qr/
    Returns a PNG image of the QR code for this route.
    Print and stick it inside the bus door.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request, pk):
        try:
            route = BusRoute.objects.get(pk=pk)
        except BusRoute.DoesNotExist:
            return Response({"error": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

        # The QR payload — the mobile app will POST this token to /api/bus/scan/
        payload = str(route.qr_token)

        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_H,
            box_size=10,
            border=4,
        )
        qr.add_data(payload)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffer = io.BytesIO()
        img.save(buffer, format="PNG")
        buffer.seek(0)

        response = HttpResponse(buffer.read(), content_type="image/png")
        response["Content-Disposition"] = f'attachment; filename="bus_qr_{route.id}.png"'
        return response


class BusRouteRegenQRView(APIView):
    """
    POST /api/bus/routes/<id>/regen-qr/
    Regenerates the QR token, invalidating all previously printed QR codes.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def post(self, request, pk):
        try:
            route = BusRoute.objects.get(pk=pk)
        except BusRoute.DoesNotExist:
            return Response({"error": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

        route.regenerate_qr_token()
        return Response({
            "message": f"QR token regenerated for '{route.name}'. Old printed QR codes are now invalid.",
            "new_qr_token": str(route.qr_token),
        })


# ─────────────────────────────────────────────────────────────────────────────
# Subscription management (Admin)
# ─────────────────────────────────────────────────────────────────────────────

class BusSubscriptionListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/bus/subscriptions/?route_id=&user_id=&status=
    POST /api/bus/subscriptions/   — Assign a student to a route
    """
    serializer_class   = BusSubscriptionSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get_queryset(self):
        qs = BusSubscription.objects.select_related("user", "route").order_by("-created_at")
        route_id = self.request.query_params.get("route_id")
        user_id  = self.request.query_params.get("user_id")
        sub_status = self.request.query_params.get("status")
        if route_id:
            qs = qs.filter(route_id=route_id)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if sub_status:
            qs = qs.filter(status=sub_status)
        return qs


class BusSubscriptionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /api/bus/subscriptions/<id>/
    Admin updates status (active/expired/suspended) or removes a student from route.
    """
    serializer_class   = BusSubscriptionSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get_queryset(self):
        return BusSubscription.objects.select_related("user", "route")


# ─────────────────────────────────────────────────────────────────────────────
# Bus Boarding QR Scan (Student)
# ─────────────────────────────────────────────────────────────────────────────

class BusBoardingScanView(APIView):
    """
    POST /api/bus/scan/

    Payload: { "qr_token": "<uuid>", "device_id": "<fingerprint>" }

    Flow:
      1. Resolve route from qr_token
      2. Check student has an active subscription for that route
      3. Prevent duplicate boarding (only one scan per day per route)
      4. Mark BusAttendance → return success
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        qr_token  = request.data.get("qr_token")
        device_id = request.data.get("device_id")

        if not qr_token:
            return Response(
                {"error": "qr_token is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 1. Resolve route ──────────────────────────────────────────────
        try:
            route = BusRoute.objects.get(qr_token=qr_token, is_active=True)
        except BusRoute.DoesNotExist:
            return Response(
                {"error": "Invalid or inactive QR code. Please contact admin."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── 2. Check subscription ─────────────────────────────────────────
        subscription = BusSubscription.objects.filter(
            user=request.user, route=route
        ).first()

        if not subscription:
            return Response(
                {
                    "error": "Access Denied. You are not subscribed to this bus route.",
                    "route": route.name,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        if not subscription.is_valid:
            return Response(
                {
                    "error": f"Your bus subscription for '{route.name}' is {subscription.status}. "
                             f"Please contact admin to renew.",
                    "status": subscription.status,
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── 3. Duplicate scan check (one boarding per day per route) ──────
        today = timezone.localdate()
        already_boarded = BusAttendance.objects.filter(
            user=request.user,
            route=route,
            scanned_at__date=today,
        ).exists()

        if already_boarded:
            return Response(
                {
                    "message": "You have already boarded this bus today.",
                    "route": route.name,
                    "already_boarded": True,
                },
                status=status.HTTP_200_OK,
            )

        # ── 4. Record boarding ────────────────────────────────────────────
        BusAttendance.objects.create(
            user=request.user,
            route=route,
            device_id=device_id or "",
        )

        return Response(
            {
                "message": f"Welcome aboard! Boarding confirmed for '{route.name}'.",
                "route": route.name,
                "boarded_at": timezone.now().isoformat(),
                "student_name": request.user.get_full_name() or request.user.username,
            },
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# Bus Attendance Log (Admin)
# ─────────────────────────────────────────────────────────────────────────────

class BusAttendanceListView(generics.ListAPIView):
    """
    GET /api/bus/attendance/?route_id=&date=YYYY-MM-DD&user_id=
    Admin can filter bus boarding records.
    """
    serializer_class   = BusAttendanceSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get_queryset(self):
        qs = BusAttendance.objects.select_related("user", "route").order_by("-scanned_at")
        route_id = self.request.query_params.get("route_id")
        date_str = self.request.query_params.get("date")
        user_id  = self.request.query_params.get("user_id")

        if route_id:
            qs = qs.filter(route_id=route_id)
        if user_id:
            qs = qs.filter(user_id=user_id)
        if date_str:
            from datetime import datetime
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
                qs = qs.filter(scanned_at__date=date)
            except ValueError:
                pass
        return qs


# ─────────────────────────────────────────────────────────────────────────────
# Live & Trail (existing, unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class BusLiveLocationsView(generics.ListAPIView):
    """GET /api/bus/live/ — All active buses seen in last 12 hours."""
    serializer_class   = BusLiveLocationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        cutoff = timezone.now() - timedelta(hours=12)
        return BusLocation.objects.select_related("user", "route").filter(updated_at__gte=cutoff)


class BusTrailView(APIView):
    """GET /api/bus/trail/<driver_id>/?date=YYYY-MM-DD"""
    permission_classes = [IsAuthenticated]

    def get(self, request, driver_id):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            driver = User.objects.get(id=driver_id)
        except User.DoesNotExist:
            return Response({"error": "Driver not found."}, status=status.HTTP_404_NOT_FOUND)

        date_str = request.query_params.get("date")
        if date_str:
            from datetime import datetime
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return Response({"error": "Invalid date. Use YYYY-MM-DD."}, status=400)
            trails = BusTrail.objects.filter(user=driver, timestamp__date=date).order_by("timestamp")
        else:
            loc = BusLocation.objects.filter(user=driver).first()
            active_route = loc.route if loc else None
            if active_route:
                trails = BusTrail.objects.filter(user=driver, route=active_route).order_by("timestamp")
            else:
                cutoff = timezone.now() - timedelta(hours=12)
                trails = BusTrail.objects.filter(user=driver, timestamp__gte=cutoff).order_by("timestamp")

        coords = [[t.lat, t.lng] for t in trails]
        return Response({
            "driver_id": driver_id,
            "driver_name": driver.get_full_name() or driver.username,
            "point_count": len(coords),
            "trail": coords,
        })



# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────

class BusRouteSerializer(drf_serializers.ModelSerializer):
    driver_name = drf_serializers.SerializerMethodField()

    class Meta:
        model = BusRoute
        fields = ["id", "name", "driver", "driver_name", "stops", "is_active", "created_at"]

    def get_driver_name(self, obj):
        if obj.driver:
            return obj.driver.get_full_name() or obj.driver.username
        return None


class BusLiveLocationSerializer(drf_serializers.ModelSerializer):
    driver_name = drf_serializers.SerializerMethodField()
    route_name = drf_serializers.SerializerMethodField()
    trail = drf_serializers.SerializerMethodField()
    distance_km = drf_serializers.SerializerMethodField()

    class Meta:
        model = BusLocation
        fields = ["id", "driver_name", "lat", "lng", "route_name", "trail", "distance_km", "updated_at"]

    def get_driver_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_route_name(self, obj):
        return obj.route.name if obj.route else None

    def get_trail(self, obj):
        if obj.route:
            trails = BusTrail.objects.filter(user=obj.user, route=obj.route).order_by("timestamp")
        else:
            cutoff = timezone.now() - timedelta(hours=12)
            trails = BusTrail.objects.filter(
                user=obj.user, route__isnull=True, timestamp__gte=cutoff
            ).order_by("timestamp")

        coords = [[t.lat, t.lng] for t in trails]
        # Deduplicate consecutive
        unique = []
        for c in coords:
            if not unique or unique[-1] != c:
                unique.append(c)
        return unique

    def get_distance_km(self, obj):
        import math
        trail = self.get_trail(obj)
        if len(trail) < 2:
            return 0.0

        def haversine(lat1, lng1, lat2, lng2):
            lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
            dlat, dlng = lat2 - lat1, lng2 - lng1
            a = math.sin(dlat/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin(dlng/2)**2
            return 2 * math.asin(math.sqrt(a)) * 6_371_000

        total = sum(haversine(trail[i][0], trail[i][1], trail[i+1][0], trail[i+1][1])
                    for i in range(len(trail)-1))
        return round(total / 1000.0, 2)


# ─────────────────────────────────────────────────────────────────────────────
# Views
# ─────────────────────────────────────────────────────────────────────────────

class BusRouteListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/bus/routes/       — List all routes (Admin)
    POST /api/bus/routes/       — Create a route (Admin)
    """
    serializer_class = BusRouteSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get_queryset(self):
        return BusRoute.objects.select_related("driver").order_by("-created_at")


class BusRouteDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/bus/routes/<id>/  — Route detail
    PATCH  /api/bus/routes/<id>/  — Update route
    DELETE /api/bus/routes/<id>/  — Delete route
    """
    serializer_class = BusRouteSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get_queryset(self):
        return BusRoute.objects.select_related("driver")


class BusLiveLocationsView(generics.ListAPIView):
    """
    GET /api/bus/live/   — All active buses seen in last 12 hours (Admin)
    """
    serializer_class = BusLiveLocationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        cutoff = timezone.now() - timedelta(hours=12)
        return BusLocation.objects.select_related("user", "route").filter(updated_at__gte=cutoff)


class BusTrailView(generics.ListAPIView):
    """
    GET /api/bus/trail/<driver_id>/?date=YYYY-MM-DD
    Returns the GPS breadcrumb trail for a bus on a given date.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, driver_id, *args, **kwargs):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        try:
            driver = User.objects.get(id=driver_id)
        except User.DoesNotExist:
            return Response({"error": "Driver not found."}, status=status.HTTP_404_NOT_FOUND)

        date_str = request.query_params.get("date")
        if date_str:
            from datetime import datetime
            try:
                date = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                return Response({"error": "Invalid date format. Use YYYY-MM-DD."}, status=400)
            trails = BusTrail.objects.filter(user=driver, timestamp__date=date).order_by("timestamp")
        else:
            # Default: active route trail or last 12h
            loc = BusLocation.objects.filter(user=driver).first()
            active_route = loc.route if loc else None
            if active_route:
                trails = BusTrail.objects.filter(user=driver, route=active_route).order_by("timestamp")
            else:
                cutoff = timezone.now() - timedelta(hours=12)
                trails = BusTrail.objects.filter(user=driver, timestamp__gte=cutoff).order_by("timestamp")

        coords = [[t.lat, t.lng] for t in trails]

        return Response({
            "driver_id": driver_id,
            "driver_name": driver.get_full_name() or driver.username,
            "point_count": len(coords),
            "trail": coords,
        })


class BusDriverDashboardView(APIView):
    """
    GET /api/bus/driver/dashboard/
    Conductor/Driver dashboard view on mobile app.
    Shows assigned Route, its Stops, expected passenger lift counts per stop,
    and boarding stats (boarded vs absent).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        driver = request.user
        route = BusRoute.objects.filter(driver=driver, is_active=True).first()

        if not route:
            return Response(
                {"error": "No active route assigned to your driver account."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get list of all active subscriptions for this route
        active_subs = BusSubscription.objects.filter(route=route, status=BusSubscription.STATUS_ACTIVE)
        expected_user_ids = active_subs.values_list("user_id", flat=True)

        # Boarded today
        today = timezone.localdate()
        boarded_attendance = BusAttendance.objects.filter(route=route, scanned_at__date=today)
        boarded_user_ids = boarded_attendance.values_list("user_id", flat=True)

        # Calculate totals
        expected_total = len(expected_user_ids)
        boarded_total = len(boarded_user_ids)
        absent_total = max(0, expected_total - boarded_total)

        # Breakdown per stop
        stops_breakdown = []
        stops_list = route.stops if isinstance(route.stops, list) else []

        for stop in stops_list:
            stop_name = stop.get("name", "")
            lat = stop.get("lat")
            lng = stop.get("lng")

            # How many students are registered for this stop
            stop_subs = active_subs.filter(boarding_stop=stop_name)
            stop_expected = stop_subs.count()

            # How many of these stop-specific students scanned today
            stop_boarded = boarded_attendance.filter(user_id__in=stop_subs.values_list("user_id", flat=True)).count()
            stop_absent = max(0, stop_expected - stop_boarded)

            stops_breakdown.append({
                "name": stop_name,
                "lat": lat,
                "lng": lng,
                "expected": stop_expected,
                "boarded": stop_boarded,
                "absent": stop_absent
            })

        return Response({
            "route_id": route.id,
            "route_name": route.name,
            "qr_token": str(route.qr_token),
            "expected_total": expected_total,
            "boarded_total": boarded_total,
            "absent_total": absent_total,
            "stops": stops_breakdown
        })


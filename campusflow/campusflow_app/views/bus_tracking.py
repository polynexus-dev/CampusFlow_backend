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

from django.http import HttpResponse
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView
from rest_framework import serializers as drf_serializers
from django.utils import timezone
from datetime import timedelta

from campusflow_app.models import (
    BusRoute, BusLocation, BusTrail, BusTrip,
    BusSubscription, BusAttendance, BusScanEvent,
)
from campusflow_app.permissions import IsSaaSOrCollegeAdmin, RequiresModule, is_saas_or_college_admin, get_user_group
from campusflow_app.services.qr_branding import render_branded_qr
from campusflow_app.services.notifications import notify_guardians_of_student

BUS_PERMS = [IsAuthenticated, RequiresModule("bus-tracking")]
BUS_ADMIN_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("bus-tracking")]


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────

class BusSubscriptionSerializer(drf_serializers.ModelSerializer):
    student_name = drf_serializers.SerializerMethodField()
    route_name   = drf_serializers.SerializerMethodField()
    is_valid     = drf_serializers.SerializerMethodField()
    allocated_fee = drf_serializers.SerializerMethodField()
    paid_fee      = drf_serializers.SerializerMethodField()
    balance_fee   = drf_serializers.SerializerMethodField()
    last_payment_date = drf_serializers.SerializerMethodField()

    class Meta:
        model = BusSubscription
        fields = [
            "id", "user", "student_name",
            "route", "route_name",
            "status", "valid_from", "valid_until",
            "boarding_stop", "notes", "is_valid",
            "allocated_fee", "paid_fee", "balance_fee", "last_payment_date",
            "created_at",
        ]
        read_only_fields = ["created_at"]

    def get_student_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_route_name(self, obj):
        return obj.route.name

    def get_is_valid(self, obj):
        return obj.is_valid

    def _get_bus_fee_metrics(self, obj):
        if hasattr(obj, "_fee_metrics"):
            return obj._fee_metrics

        from campusflow_app.models import StudentFeeInvoice

        invoices = StudentFeeInvoice.objects.filter(
            student=obj.user,
            items__category__name__icontains="Bus"
        ).distinct()

        allocated = 0.0
        paid = 0.0
        last_payment = None

        for inv in invoices:
            bus_item = inv.items.filter(category__name__icontains="Bus").first()
            if not bus_item:
                continue
            item_allocated = float(bus_item.amount)
            allocated += item_allocated

            net_amount = float(inv.total_amount - inv.discount_amount)
            if net_amount > 0:
                paid_ratio = min(1.0, float(inv.paid_amount) / net_amount)
                paid += item_allocated * paid_ratio
            elif inv.status == "paid":
                paid += item_allocated

            latest_pay = inv.payments.order_by("-payment_date").first()
            if latest_pay:
                if not last_payment or latest_pay.payment_date > last_payment:
                    last_payment = latest_pay.payment_date

        balance = max(0.0, allocated - paid)

        obj._fee_metrics = {
            "allocated": round(allocated, 2),
            "paid": round(paid, 2),
            "balance": round(balance, 2),
            "last_payment_date": last_payment.strftime("%Y-%m-%d %H:%M:%S") if last_payment else None
        }
        return obj._fee_metrics

    def get_allocated_fee(self, obj):
        return self._get_bus_fee_metrics(obj)["allocated"]

    def get_paid_fee(self, obj):
        return self._get_bus_fee_metrics(obj)["paid"]

    def get_balance_fee(self, obj):
        return self._get_bus_fee_metrics(obj)["balance"]

    def get_last_payment_date(self, obj):
        return self._get_bus_fee_metrics(obj)["last_payment_date"]


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
    route       = drf_serializers.SerializerMethodField()
    trail       = drf_serializers.SerializerMethodField()
    distance_km = drf_serializers.SerializerMethodField()
    last_seen   = drf_serializers.DateTimeField(source="updated_at")

    class Meta:
        model = BusLocation
        fields = ["id", "driver_name", "lat", "lng", "route", "trail", "distance_km", "last_seen"]

    def get_driver_name(self, obj):
        return obj.user.get_full_name() or obj.user.username

    def get_route(self, obj):
        if not obj.route:
            return None
        return {"id": obj.route.id, "name": obj.route.name, "stops": obj.route.stops}

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

# ─────────────────────────────────────────────────────────────────────────────
# QR Code generation (Admin)
# ─────────────────────────────────────────────────────────────────────────────

class BusRouteQRView(APIView):
    """
    GET /api/bus/routes/<id>/qr/
    Returns a PNG image of the QR code for this route.
    Print and stick it inside the bus door.
    """
    permission_classes = BUS_ADMIN_PERMS

    def get(self, request, pk):
        try:
            route = BusRoute.objects.get(pk=pk)
        except BusRoute.DoesNotExist:
            return Response({"error": "Route not found."}, status=status.HTTP_404_NOT_FOUND)

        # The QR payload — the mobile app will POST this token to /api/bus/scan/
        png_bytes = render_branded_qr(
            payload=str(route.qr_token),
            title_text="CAMPUSNEXUS TRANSIT BOARDING PASS",
        )

        response = HttpResponse(png_bytes, content_type="image/png")
        response["Content-Disposition"] = f'attachment; filename="bus_qr_{route.id}.png"'
        return response


class StudentIDQRView(APIView):
    """
    GET /api/bus/student/<id>/id-card-qr/
    Returns a PNG of the student's ID-card QR code — this is what the bus
    conductor scans to board/alight the student (see BusConductorScanStudentView).
    Admins can fetch anyone's; a student may only fetch their own.
    """
    permission_classes = BUS_PERMS

    def get(self, request, pk):
        from campusflow_app.models import StudentProfile

        try:
            profile = StudentProfile.objects.select_related("user").get(pk=pk)
        except StudentProfile.DoesNotExist:
            return Response({"error": "Student not found."}, status=status.HTTP_404_NOT_FOUND)

        if profile.user_id != request.user.id and not is_saas_or_college_admin(request.user):
            return Response({"error": "You are not authorized to view this student's ID card."}, status=status.HTTP_403_FORBIDDEN)

        png_bytes = render_branded_qr(
            payload=str(profile.qr_token),
            title_text="CAMPUSNEXUS STUDENT ID CARD",
        )

        response = HttpResponse(png_bytes, content_type="image/png")
        response["Content-Disposition"] = f'attachment; filename="student_id_qr_{profile.id}.png"'
        return response


class BusRouteRegenQRView(APIView):
    """
    POST /api/bus/routes/<id>/regen-qr/
    Regenerates the QR token, invalidating all previously printed QR codes.
    """
    permission_classes = BUS_ADMIN_PERMS

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
    POST /api/bus/subscriptions/   — Assign a student to a route (Admin only)
    Students can view their own subscriptions.
    """
    serializer_class   = BusSubscriptionSerializer
    permission_classes = BUS_PERMS

    def get_queryset(self):
        user = self.request.user
        qs = BusSubscription.objects.select_related("user", "route").order_by("-created_at")

        # Students can only see their own subscriptions
        if not is_saas_or_college_admin(user):
            return qs.filter(user=user)

        # Admin filters
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

    def create(self, request, *args, **kwargs):
        # Only admins can create subscriptions
        if not is_saas_or_college_admin(request.user):
            return Response(
                {"error": "Only admins can assign bus subscriptions."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return super().create(request, *args, **kwargs)


class BusSubscriptionDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET/PATCH/DELETE /api/bus/subscriptions/<id>/
    Admin updates status (active/expired/suspended) or removes a student from route.
    """
    serializer_class   = BusSubscriptionSerializer
    permission_classes = BUS_ADMIN_PERMS

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
    permission_classes = BUS_PERMS

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
# Conductor scans a STUDENT's ID card (board / alight)
# ─────────────────────────────────────────────────────────────────────────────

class BusConductorScanStudentView(APIView):
    """
    POST /api/bus/conductor/scan-student/

    Payload: {
        "trip_id": <int>,
        "student_qr_token": "<uuid>",
        "direction": "board" | "alight",
        "stop_name": "<str>",
        "authorized_pickup_confirmed": <bool>   # only checked for direction="alight"
    }

    This is the Conductor App's "Scan ID cards" screen: the conductor scans
    the STUDENT's ID card (StudentProfile.qr_token), not the bus's own QR
    (that's the student self-boarding flow in BusBoardingScanView above).
    Returns one of BusScanEvent.STATUS_CHOICES so the app can render the
    matching success/error card.
    """
    permission_classes = BUS_PERMS

    def post(self, request):
        from campusflow_app.models import StudentProfile

        trip_id = request.data.get("trip_id")
        raw_code = request.data.get("student_qr_token") or ""
        direction = request.data.get("direction")
        stop_name = request.data.get("stop_name", "")
        authorized_pickup_confirmed = bool(request.data.get("authorized_pickup_confirmed"))

        if direction not in (BusScanEvent.DIRECTION_BOARD, BusScanEvent.DIRECTION_ALIGHT):
            return Response({"error": "direction must be 'board' or 'alight'."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            trip = BusTrip.objects.select_related("route").get(pk=trip_id)
        except (BusTrip.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Trip not found."}, status=status.HTTP_404_NOT_FOUND)

        if trip.ended_at is not None:
            return Response({"error": "This trip has already ended."}, status=status.HTTP_400_BAD_REQUEST)

        route = trip.route
        is_conductor_or_driver = route is not None and request.user.id in (route.driver_id, route.conductor_id)
        if not is_conductor_or_driver and not is_saas_or_college_admin(request.user):
            return Response({"error": "You are not the assigned driver/conductor for this trip."}, status=status.HTTP_403_FORBIDDEN)

        def record(status_value, student=None):
            return BusScanEvent.objects.create(
                trip=trip,
                route=route,
                student=student,
                scanned_by=request.user,
                direction=direction,
                status=status_value,
                stop_name=stop_name,
                raw_code=raw_code,
            )

        # ── Resolve the student from the scanned ID card ───────────────────
        import uuid as uuid_lib
        try:
            token = uuid_lib.UUID(str(raw_code))
            profile = StudentProfile.objects.select_related("user").get(qr_token=token)
        except (StudentProfile.DoesNotExist, ValueError, TypeError):
            record(BusScanEvent.STATUS_UNREADABLE)
            return Response(
                {"status": BusScanEvent.STATUS_UNREADABLE, "message": "Could not read this ID card. Try manual entry."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        student_user = profile.user

        # ── Subscription checks ────────────────────────────────────────────
        subscription = BusSubscription.objects.filter(user=student_user, route=route).first() if route else None
        other_route_sub = (
            BusSubscription.objects.filter(user=student_user).exclude(route=route).first()
            if not subscription else None
        )

        if not subscription:
            if other_route_sub:
                record(BusScanEvent.STATUS_WRONG_ROUTE, student=student_user)
                return Response(
                    {
                        "status": BusScanEvent.STATUS_WRONG_ROUTE,
                        "message": f"{student_user.get_full_name() or student_user.username} is subscribed to a different route: {other_route_sub.route.name}.",
                        "student_name": student_user.get_full_name() or student_user.username,
                        "subscribed_route": other_route_sub.route.name,
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
            record(BusScanEvent.STATUS_NOT_SUBSCRIBED, student=student_user)
            return Response(
                {"status": BusScanEvent.STATUS_NOT_SUBSCRIBED, "message": "This student is not subscribed to any bus route."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if not subscription.is_valid:
            record(BusScanEvent.STATUS_NOT_SUBSCRIBED, student=student_user)
            return Response(
                {"status": BusScanEvent.STATUS_NOT_SUBSCRIBED, "message": f"Subscription is {subscription.status}.", "sub_status": subscription.status},
                status=status.HTTP_403_FORBIDDEN,
            )

        # ── Duplicate scan check (one board/alight per trip per student) ──
        already = BusScanEvent.objects.filter(
            trip=trip, student=student_user, direction=direction,
            status__in=[BusScanEvent.STATUS_BOARDED, BusScanEvent.STATUS_ALIGHTED],
        ).exists()
        if already:
            record(BusScanEvent.STATUS_ALREADY_SCANNED, student=student_user)
            return Response(
                {"status": BusScanEvent.STATUS_ALREADY_SCANNED, "message": "Already scanned for this trip.", "student_name": student_user.get_full_name() or student_user.username},
                status=status.HTTP_200_OK,
            )

        # ── Alighting requires an authorized pickup confirmation ──────────
        if direction == BusScanEvent.DIRECTION_ALIGHT and not authorized_pickup_confirmed:
            record(BusScanEvent.STATUS_NO_AUTHORIZED_PICKUP, student=student_user)
            return Response(
                {
                    "status": BusScanEvent.STATUS_NO_AUTHORIZED_PICKUP,
                    "message": f"No authorised pickup at stop. {student_user.get_full_name() or student_user.username} stays on the bus.",
                    "student_name": student_user.get_full_name() or student_user.username,
                },
                status=status.HTTP_200_OK,
            )

        # ── Success ─────────────────────────────────────────────────────────
        final_status = BusScanEvent.STATUS_BOARDED if direction == BusScanEvent.DIRECTION_BOARD else BusScanEvent.STATUS_ALIGHTED
        record(final_status, student=student_user)

        class_label = " · ".join(filter(None, [profile.current_semester_year, profile.section_division]))
        notify_guardians_of_student(
            profile,
            title=f"{student_user.get_full_name() or student_user.username} {'boarded' if final_status == BusScanEvent.STATUS_BOARDED else 'alighted'} the bus",
            body=f"{stop_name} · {timezone.now().strftime('%I:%M %p')} · Route {route.name if route else ''}",
            category=f"bus_{'boarding' if final_status == BusScanEvent.STATUS_BOARDED else 'alighting'}",
            data={"trip_id": trip.id, "student_id": profile.id, "stop_name": stop_name},
        )

        return Response(
            {
                "status": final_status,
                "message": f"{'Boarded' if final_status == BusScanEvent.STATUS_BOARDED else 'Alighted'} · {timezone.now().strftime('%I:%M %p')}",
                "student_name": student_user.get_full_name() or student_user.username,
                "class_label": class_label,
                "stop_name": stop_name,
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
    permission_classes = BUS_ADMIN_PERMS

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

        # Cap unbounded growth by default (mirrors AuditLogListView /
        # AllAttendanceView) — boarding scans accumulate per rider per
        # route per day with no natural upper bound.
        limit = min(int(self.request.query_params.get('limit', 200)), 1000)
        return qs[:limit]


# ─────────────────────────────────────────────────────────────────────────────
# Live & Trail (existing, unchanged)
# ─────────────────────────────────────────────────────────────────────────────

class BusLiveLocationsView(generics.ListAPIView):
    """
    GET /api/bus/live/
    Admins see every active route. Everyone else (students/faculty riders)
    only sees routes they hold a currently-valid subscription for.
    If a route has no active tracking log, return a stationary placeholder
    at the first stop so stops and maps load on the client.
    """
    serializer_class   = BusLiveLocationSerializer
    permission_classes = BUS_PERMS

    def get_queryset(self):
        return BusLocation.objects.none()

    def list(self, request, *args, **kwargs):
        from campusflow_app.models import BusRoute, BusLocation, BusSubscription
        from django.db.models import Q
        from django.utils import timezone
        from datetime import timedelta

        routes = BusRoute.objects.filter(is_active=True).select_related("driver")

        if not is_saas_or_college_admin(request.user):
            today = timezone.localdate()
            subscribed_route_ids = BusSubscription.objects.filter(
                user=request.user,
                status=BusSubscription.STATUS_ACTIVE,
                valid_from__lte=today,
            ).filter(
                Q(valid_until__isnull=True) | Q(valid_until__gte=today)
            ).values_list("route_id", flat=True)
            routes = routes.filter(id__in=subscribed_route_ids)

        cutoff = timezone.now() - timedelta(hours=12)

        buses = []
        for r in routes:
            # Check if there is a live location update in the last 12 hours
            loc = BusLocation.objects.filter(route=r, updated_at__gte=cutoff).first()
            if loc:
                serializer = self.get_serializer(loc)
                buses.append(serializer.data)
            else:
                # Build a placeholder location at the first stop of the route
                first_stop = r.stops[0] if r.stops else {"name": "Terminus", "lat": 21.1458, "lng": 79.0882}
                try:
                    lat = float(first_stop.get("lat", 21.1458))
                    lng = float(first_stop.get("lng", 79.0882))
                except (ValueError, TypeError):
                    lat, lng = 21.1458, 79.0882
                    
                buses.append({
                    "driver_id": str(r.driver.id) if r.driver else "none",
                    "driver_name": r.driver.get_full_name() or r.driver.username if r.driver else "Unassigned",
                    "lat": lat,
                    "lng": lng,
                    "trail": [[lat, lng]],
                    "distance_km": 0.0,
                    "route": {
                        "id": r.id,
                        "name": r.name,
                        "stops": r.stops
                    },
                    "last_seen": timezone.now().isoformat()
                })
        return Response(buses)


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────

class BusRouteSerializer(drf_serializers.ModelSerializer):
    driver_name = drf_serializers.SerializerMethodField()
    conductor_name = drf_serializers.SerializerMethodField()
    subscriber_count = drf_serializers.SerializerMethodField()

    class Meta:
        model = BusRoute
        fields = [
            "id", "name", "driver", "driver_name",
            "conductor", "conductor_name",
            "stops", "is_active", "created_at", "subscriber_count",
        ]

    def get_driver_name(self, obj):
        if obj.driver:
            return obj.driver.get_full_name() or obj.driver.username
        return None

    def get_conductor_name(self, obj):
        if obj.conductor:
            return obj.conductor.get_full_name() or obj.conductor.username
        return None

    def get_subscriber_count(self, obj):
        return obj.subscriptions.filter(status="active").count()


# ─────────────────────────────────────────────────────────────────────────────
# Views
# ─────────────────────────────────────────────────────────────────────────────

class BusRouteListCreateView(generics.ListCreateAPIView):
    """
    GET  /api/bus/routes/       — List all routes (Admin)
    POST /api/bus/routes/       — Create a route (Admin)
    """
    serializer_class = BusRouteSerializer
    permission_classes = BUS_ADMIN_PERMS

    def get_queryset(self):
        return BusRoute.objects.select_related("driver", "conductor").order_by("-created_at")


class BusRouteDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    GET    /api/bus/routes/<id>/  — Route detail
    PATCH  /api/bus/routes/<id>/  — Update route
    DELETE /api/bus/routes/<id>/  — Delete route
    """
    serializer_class = BusRouteSerializer
    permission_classes = BUS_ADMIN_PERMS

    def get_queryset(self):
        return BusRoute.objects.select_related("driver", "conductor")


class BusTrailView(generics.ListAPIView):
    """
    GET /api/bus/trail/<driver_id>/?date=YYYY-MM-DD
    Returns the GPS breadcrumb trail for a bus on a given date.
    """
    permission_classes = BUS_PERMS

    def get(self, request, driver_id, *args, **kwargs):
        from django.contrib.auth import get_user_model
        User = get_user_model()

        # Only admins, or the driver viewing their own trail, may access this.
        if str(request.user.id) != str(driver_id) and not is_saas_or_college_admin(request.user):
            return Response({"error": "You are not authorized to view this driver's trail."}, status=status.HTTP_403_FORBIDDEN)

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
    permission_classes = BUS_PERMS

    def get(self, request):
        from django.db.models import Q

        driver = request.user
        route = BusRoute.objects.filter(
            Q(driver=driver) | Q(conductor=driver), is_active=True
        ).first()

        if not route:
            return Response(
                {"error": "No active route assigned to your driver/conductor account."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Get list of all active subscriptions for this route
        active_subs = BusSubscription.objects.filter(route=route, status=BusSubscription.STATUS_ACTIVE).select_related("user")
        expected_user_ids = active_subs.values_list("user_id", flat=True)

        # Boarded today
        today = timezone.localdate()
        boarded_attendance = BusAttendance.objects.filter(route=route, scanned_at__date=today)
        boarded_user_ids = set(boarded_attendance.values_list("user_id", flat=True))

        # Calculate totals
        expected_total = len(expected_user_ids)
        boarded_total = len(boarded_user_ids)
        absent_total = max(0, expected_total - boarded_total)

        # Passenger roster with fee status. Only students pay an additional bus
        # fee (tracked via StudentFeeInvoice); everyone else's bus charge is
        # deducted from payroll, so there's no "pending" balance to chase.
        fee_serializer = BusSubscriptionSerializer()
        passengers = []
        for sub in active_subs:
            role = get_user_group(sub.user) or "Unknown"
            entry = {
                "user_id": sub.user.id,
                "name": sub.user.get_full_name() or sub.user.username,
                "role": role,
                "boarding_stop": sub.boarding_stop,
                "boarded_today": sub.user_id in boarded_user_ids,
            }
            if role.lower() == "student":
                metrics = fee_serializer._get_bus_fee_metrics(sub)
                entry["balance_fee"] = metrics["balance"]
                entry["fee_status"] = "pending" if metrics["balance"] > 0 else "paid"
            else:
                entry["balance_fee"] = None
                entry["fee_status"] = "payroll_deduction"
            passengers.append(entry)

        total_pending_bus_dues = round(
            sum(p["balance_fee"] for p in passengers if p["fee_status"] == "pending"), 2
        )

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
            "stops": stops_breakdown,
            "passengers": passengers,
            "total_pending_bus_dues": total_pending_bus_dues,
        })


class BusSummaryStatsView(APIView):
    """
    GET /api/bus/summary-stats/
    Returns summary statistics for the transit/bus tracking module.
    """
    permission_classes = BUS_PERMS

    def get(self, request):
        total_routes = BusRoute.objects.filter(is_active=True).count()
        active_subs = BusSubscription.objects.filter(status=BusSubscription.STATUS_ACTIVE)
        total_subscribers = active_subs.count()

        # Group count filter
        student_subscribers = active_subs.filter(user__groups__name='student').distinct().count()
        employee_subscribers = max(0, total_subscribers - student_subscribers)

        total_drivers = BusRoute.objects.filter(is_active=True, driver__isnull=False).values("driver").distinct().count()

        cutoff = timezone.now() - timedelta(hours=12)
        active_buses_live = BusLocation.objects.filter(updated_at__gte=cutoff).count()

        return Response({
            "total_routes": total_routes,
            "total_subscribers": total_subscribers,
            "student_subscribers": student_subscribers,
            "employee_subscribers": employee_subscribers,
            "total_drivers": total_drivers,
            "active_buses_live": active_buses_live
        })


# ─────────────────────────────────────────────────────────────────────────────
# Driver Trip Logging & Stats
# ─────────────────────────────────────────────────────────────────────────────

class BusTripStartView(APIView):
    """
    POST /api/bus/driver/trip/start/
    Driver taps "Start Active Trip". Closes any dangling open trip first
    (e.g. the app was killed mid-trip last time) so stats never double-count.
    """
    permission_classes = BUS_PERMS

    def post(self, request):
        from django.db.models import Q

        BusTrip.objects.filter(driver=request.user, ended_at__isnull=True).update(ended_at=timezone.now())

        route = BusRoute.objects.filter(
            Q(driver=request.user) | Q(conductor=request.user), is_active=True
        ).first()
        trip = BusTrip.objects.create(driver=request.user, route=route)
        return Response(
            {"trip_id": trip.id, "started_at": trip.started_at.isoformat()},
            status=status.HTTP_201_CREATED,
        )


class BusTripEndView(APIView):
    """
    POST /api/bus/driver/trip/end/
    Driver taps "End Trip & Stop GPS". Closes the most recent open trip and
    computes its distance from the BusTrail breadcrumbs logged during it.
    """
    permission_classes = BUS_PERMS

    def post(self, request):
        trip = BusTrip.objects.filter(driver=request.user, ended_at__isnull=True).order_by("-started_at").first()
        if not trip:
            return Response({"error": "No active trip to end."}, status=status.HTTP_400_BAD_REQUEST)

        trail_qs = BusTrail.objects.filter(user=request.user, timestamp__gte=trip.started_at).order_by("timestamp")
        if trip.route:
            trail_qs = trail_qs.filter(route=trip.route)
        coords = [[t.lat, t.lng] for t in trail_qs]

        import math

        def haversine(la1, ln1, la2, ln2):
            la1, ln1, la2, ln2 = map(math.radians, [la1, ln1, la2, ln2])
            a = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((ln2 - ln1) / 2) ** 2
            return 2 * math.asin(math.sqrt(a)) * 6_371_000

        distance_km = 0.0
        if len(coords) >= 2:
            total_m = sum(
                haversine(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
                for i in range(len(coords) - 1)
            )
            distance_km = round(total_m / 1000.0, 2)

        trip.ended_at = timezone.now()
        trip.distance_km = distance_km

        # ── Per-trip summary + missing-student detection ───────────────────
        from campusflow_app.models import StudentProfile

        expected_count = boarded_count = missing_count = 0
        if trip.route:
            expected_subs = BusSubscription.objects.filter(
                route=trip.route, status=BusSubscription.STATUS_ACTIVE
            ).select_related("user")
            expected_user_ids = set(expected_subs.values_list("user_id", flat=True))
            boarded_user_ids = set(
                BusScanEvent.objects.filter(
                    trip=trip, direction=BusScanEvent.DIRECTION_BOARD, status=BusScanEvent.STATUS_BOARDED
                ).values_list("student_id", flat=True)
            )
            missing_user_ids = expected_user_ids - boarded_user_ids

            expected_count = len(expected_user_ids)
            boarded_count = len(boarded_user_ids)
            missing_count = len(missing_user_ids)

            if missing_user_ids:
                missing_profiles = StudentProfile.objects.filter(user_id__in=missing_user_ids).select_related("user")
                for profile in missing_profiles:
                    BusScanEvent.objects.create(
                        trip=trip,
                        route=trip.route,
                        student=profile.user,
                        scanned_by=None,
                        direction=BusScanEvent.DIRECTION_BOARD,
                        status=BusScanEvent.STATUS_MISSING,
                    )
                    notify_guardians_of_student(
                        profile,
                        title=f"{profile.user.get_full_name() or profile.user.username} did not board the bus",
                        body=f"Route {trip.route.name} · trip ended {trip.ended_at.strftime('%I:%M %p')}",
                        category="bus_missing",
                        data={"trip_id": trip.id, "student_id": profile.id},
                    )

        trip.expected_count = expected_count
        trip.boarded_count = boarded_count
        trip.missing_count = missing_count
        trip.save(update_fields=["ended_at", "distance_km", "expected_count", "boarded_count", "missing_count"])

        return Response({
            "trip_id": trip.id,
            "ended_at": trip.ended_at.isoformat(),
            "distance_km": trip.distance_km,
            "expected_count": trip.expected_count,
            "boarded_count": trip.boarded_count,
            "missing_count": trip.missing_count,
        })


class BusDriverTripStatsView(APIView):
    """
    GET /api/bus/driver/trip-stats/
    Completed-trip counts and distance for this calendar week and month,
    shown on the Conductor Panel's dashboard section.
    """
    permission_classes = BUS_PERMS

    def get(self, request):
        from django.db.models import Count, Sum

        now = timezone.now()
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        completed = BusTrip.objects.filter(driver=request.user, ended_at__isnull=False)
        week_agg = completed.filter(started_at__gte=week_start).aggregate(count=Count("id"), distance=Sum("distance_km"))
        month_agg = completed.filter(started_at__gte=month_start).aggregate(count=Count("id"), distance=Sum("distance_km"))

        return Response({
            "trips_this_week": week_agg["count"] or 0,
            "distance_this_week_km": round(week_agg["distance"] or 0.0, 2),
            "trips_this_month": month_agg["count"] or 0,
            "distance_this_month_km": round(month_agg["distance"] or 0.0, 2),
        })


class BusTripSummaryView(APIView):
    """
    GET /api/bus/driver/trip/<id>/summary/
    Powers the Conductor App's "Trip summary" screen: boarded/expected/
    missing counts plus the missing-student list (name, class, stop) for
    the "Missing · did not board" section with a call-parent action.
    """
    permission_classes = BUS_PERMS

    def get(self, request, pk):
        try:
            trip = BusTrip.objects.select_related("route", "driver").get(pk=pk)
        except BusTrip.DoesNotExist:
            return Response({"error": "Trip not found."}, status=status.HTTP_404_NOT_FOUND)

        is_conductor_or_driver = trip.route is not None and request.user.id in (trip.route.driver_id, trip.route.conductor_id)
        if not is_conductor_or_driver and not is_saas_or_college_admin(request.user):
            return Response({"error": "You are not authorized to view this trip."}, status=status.HTTP_403_FORBIDDEN)

        missing_events = BusScanEvent.objects.filter(
            trip=trip, status=BusScanEvent.STATUS_MISSING
        ).select_related("student")

        missing_students = []
        for event in missing_events:
            sub = BusSubscription.objects.filter(user=event.student, route=trip.route).first()
            profile = getattr(event.student, "student_profile", None)
            class_label = " · ".join(filter(None, [
                getattr(profile, "current_semester_year", None),
                getattr(profile, "section_division", None),
            ])) if profile else ""
            missing_students.append({
                "student_id": event.student_id,
                "name": event.student.get_full_name() or event.student.username,
                "class_label": class_label,
                "stop_name": sub.boarding_stop if sub else "",
            })

        return Response({
            "trip_id": trip.id,
            "route_name": trip.route.name if trip.route else None,
            "trip_type": trip.trip_type,
            "started_at": trip.started_at.isoformat(),
            "ended_at": trip.ended_at.isoformat() if trip.ended_at else None,
            "expected_count": trip.expected_count,
            "boarded_count": trip.boarded_count,
            "missing_count": trip.missing_count,
            "missing_students": missing_students,
        })



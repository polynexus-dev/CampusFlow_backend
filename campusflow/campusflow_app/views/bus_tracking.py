from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import serializers as drf_serializers
from django.utils import timezone
from datetime import timedelta

from campusflow_app.models import BusRoute, BusLocation, BusTrail
from campusflow_app.permissions import IsSaaSOrCollegeAdmin


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

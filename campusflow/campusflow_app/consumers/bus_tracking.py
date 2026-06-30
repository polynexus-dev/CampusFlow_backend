import json
import math
import traceback

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async


def calculate_distance(lat1, lng1, lat2, lng2):
    """Haversine distance between two GPS points in metres."""
    lat1, lng1, lat2, lng2 = map(math.radians, [lat1, lng1, lat2, lng2])
    dlat = lat2 - lat1
    dlng = lng2 - lng1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlng / 2) ** 2
    return 2 * math.asin(math.sqrt(a)) * 6_371_000  # metres


def trail_distance_km(coords):
    """Total cumulative distance along [[lat,lng],...] list in km."""
    if len(coords) < 2:
        return 0.0
    total = sum(
        calculate_distance(coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1])
        for i in range(len(coords) - 1)
    )
    return round(total / 1000.0, 2)


class BusTrackingConsumer(AsyncWebsocketConsumer):
    """
    WebSocket consumer for real-time bus tracking.

    Bus Driver connects  → sends {lat, lng} every N seconds
    Admin/Viewer connects → receives live bus position broadcasts

    Groups:
      "bus_admins"           – all admin watchers (receive broadcasts)
      "bus_<user_id>"        – individual driver (receives ack)
    """

    JITTER_THRESHOLD_M = 8.0       # ignore movement < 8 metres (GPS noise)
    SPEED_LIMIT_KMH    = 150.0     # reject impossible teleports
    MAX_TRAIL_POINTS   = 120       # downsample trail above this count

    # ------------------------------------------------------------------ #
    # Connect / Disconnect
    # ------------------------------------------------------------------ #

    async def connect(self):
        self.user = self.scope.get("user")
        if not self.user or self.user.is_anonymous:
            await self.close()
            return

        self.is_driver = await self._is_bus_driver()
        self.is_admin  = self.user.is_staff or self.user.is_superuser

        if not self.is_driver and not self.is_admin:
            await self.close()
            return

        if self.is_admin:
            await self.channel_layer.group_add("bus_admins", self.channel_name)
        else:
            await self.channel_layer.group_add(f"bus_{self.user.id}", self.channel_name)

        await self.accept()

        # Send initial state to admin on connect
        if self.is_admin:
            state = await self._get_all_buses_state()
            await self.send(text_data=json.dumps({"type": "initial_state", "buses": state}))

    async def disconnect(self, close_code):
        if hasattr(self, "is_admin") and self.is_admin:
            await self.channel_layer.group_discard("bus_admins", self.channel_name)
        elif hasattr(self, "user"):
            await self.channel_layer.group_discard(f"bus_{self.user.id}", self.channel_name)

    # ------------------------------------------------------------------ #
    # Receive GPS from Driver
    # ------------------------------------------------------------------ #

    async def receive(self, text_data):
        if not self.is_driver:
            return
        try:
            data = json.loads(text_data)
            lat = data.get("lat")
            lng = data.get("lng")
            if lat is None or lng is None:
                return

            result = await self._update_bus_location(float(lat), float(lng))
            if result is None:
                return

            snapped_lat, snapped_lng, trail, distance_km, route_info = result

            payload = {
                "type": "bus_location_update",
                "driver_id": str(self.user.id),
                "driver_name": self.user.get_full_name() or self.user.username,
                "lat": snapped_lat,
                "lng": snapped_lng,
                "trail": trail,
                "distance_km": distance_km,
                "route": route_info,
            }

            # Broadcast to all admins
            await self.channel_layer.group_send("bus_admins", payload)

            # Ack back to the driver
            await self.send(text_data=json.dumps({**payload, "type": "location_ack"}))

        except Exception:
            traceback.print_exc()

    # ------------------------------------------------------------------ #
    # Channel layer message handlers (called by group_send)
    # ------------------------------------------------------------------ #

    async def bus_location_update(self, event):
        await self.send(text_data=json.dumps(event))

    # ------------------------------------------------------------------ #
    # Database helpers
    # ------------------------------------------------------------------ #

    @database_sync_to_async
    def _is_bus_driver(self):
        from campusflow_app.models import BusRoute
        return BusRoute.objects.filter(driver=self.user, is_active=True).exists()

    @database_sync_to_async
    def _update_bus_location(self, lat, lng):
        from campusflow_app.models import BusRoute, BusLocation, BusTrail
        from django.utils import timezone
        from datetime import timedelta

        try:
            # Find the driver's active route
            route = BusRoute.objects.filter(driver=self.user, is_active=True).first()

            # ----- GPS Jitter / Speed filter -----
            prev = BusTrail.objects.filter(user=self.user).order_by("-timestamp").first()
            if prev:
                dist = calculate_distance(lat, lng, prev.lat, prev.lng)

                # Speed outlier check
                time_diff = (timezone.now() - prev.timestamp).total_seconds()
                if time_diff > 0:
                    speed = (dist / time_diff) * 3.6  # km/h
                    if speed > self.SPEED_LIMIT_KMH:
                        print(f"[BusTracking] Rejected outlier: {speed:.1f} km/h for {self.user.username}")
                        return self._build_result(lat, lng, route)

                # Jitter filter — don't store if barely moved
                if dist < self.JITTER_THRESHOLD_M:
                    BusLocation.objects.update_or_create(
                        user=self.user,
                        defaults={"lat": lat, "lng": lng, "route": route},
                    )
                    return self._build_result(lat, lng, route)

            # ----- Save live position -----
            BusLocation.objects.update_or_create(
                user=self.user,
                defaults={"lat": lat, "lng": lng, "route": route},
            )

            # ----- Append trail breadcrumb -----
            BusTrail.objects.create(user=self.user, route=route, lat=lat, lng=lng)

            return self._build_result(lat, lng, route)

        except Exception:
            traceback.print_exc()
            return None

    def _build_result(self, lat, lng, route):
        """Build the trail + metadata tuple from DB."""
        from campusflow_app.models import BusTrail
        from django.utils import timezone
        from datetime import timedelta

        if route:
            trails = BusTrail.objects.filter(user=self.user, route=route).order_by("timestamp")
        else:
            cutoff = timezone.now() - timedelta(hours=12)
            trails = BusTrail.objects.filter(
                user=self.user, route__isnull=True, timestamp__gte=cutoff
            ).order_by("timestamp")

        coords = [[t.lat, t.lng] for t in trails]

        # Deduplicate consecutive duplicates
        unique = []
        for c in coords:
            if not unique or unique[-1] != c:
                unique.append(c)

        # Downsample if too many
        if len(unique) > self.MAX_TRAIL_POINTS:
            step = len(unique) // self.MAX_TRAIL_POINTS + 1
            sampled = unique[::step]
            if sampled[-1] != unique[-1]:
                sampled.append(unique[-1])
        else:
            sampled = unique

        route_info = None
        if route:
            route_info = {"id": route.id, "name": route.name, "stops": route.stops}

        return lat, lng, sampled, trail_distance_km(sampled), route_info

    @database_sync_to_async
    def _get_all_buses_state(self):
        """Return initial state of all active buses for admin dashboard."""
        from campusflow_app.models import BusLocation
        from django.utils import timezone
        from datetime import timedelta

        cutoff = timezone.now() - timedelta(hours=12)
        active = BusLocation.objects.select_related("user", "route").filter(updated_at__gte=cutoff)

        buses = []
        for loc in active:
            result = self._build_result(loc.lat, loc.lng, loc.route)
            if result:
                lat, lng, trail, dist_km, route_info = result
                buses.append({
                    "driver_id": str(loc.user.id),
                    "driver_name": loc.user.get_full_name() or loc.user.username,
                    "lat": loc.lat,
                    "lng": loc.lng,
                    "trail": trail,
                    "distance_km": dist_km,
                    "route": route_info,
                    "last_seen": loc.updated_at.isoformat(),
                })
        return buses

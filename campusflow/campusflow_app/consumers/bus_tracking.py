import json
import math
import traceback
import asyncio
from urllib.parse import parse_qs

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django_tenants.utils import schema_context


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
        # Parse query parameters for mobile auth & schema routing
        query_params = parse_qs(self.scope.get("query_string", b"").decode("utf-8"))
        token = query_params.get("token", [None])[0]
        schema = query_params.get("schema", [None])[0] or "public"

        self.schema = schema
        self.user = None
        self.mock_task = None

        print(f"[WS Connect] Initiating connection. Schema: {schema}, Token present: {bool(token)}")

        if token:
            try:
                from rest_framework_simplejwt.tokens import AccessToken
                access_token = AccessToken(token)
                user_id = access_token["user_id"]
                self.user = await self._get_user_by_id(user_id, schema)
                if self.user:
                    print(f"[WS Connect] Token authenticated successfully. User: {self.user.username} (ID: {self.user.id})")
                else:
                    print(f"[WS Connect] Token decoded to user ID {user_id} but user not found in schema {schema}")
            except Exception as e:
                print(f"[WS Connect] Token auth failed/invalid: {e}")

        # Fallback to standard session auth
        if not self.user:
            self.user = self.scope.get("user")
            if self.user and not self.user.is_anonymous:
                print(f"[WS Connect] Authenticated via session cookie. User: {self.user.username}")

        if not self.user or self.user.is_anonymous:
            print("[WS Connect] Rejected connection: Anonymous / Unauthenticated user.")
            await self.close()
            return

        self.is_driver = await self._is_bus_driver(self.schema)
        self.is_admin  = self.user.is_staff or self.user.is_superuser
        self.tracked_groups = []

        if self.is_admin:
            await self.channel_layer.group_add("bus_admins", self.channel_name)
        elif self.is_driver:
            await self.channel_layer.group_add(f"bus_{self.user.id}", self.channel_name)

        await self.accept()
        print(f"[WS Connect] Accepted connection. User: {self.user.username}, IsDriver: {self.is_driver}, IsAdmin: {self.is_admin}")

        # Send initial state to admin on connect
        if self.is_admin:
            state = await self._get_all_buses_state(self.schema)
            await self.send(text_data=json.dumps({"type": "initial_state", "buses": state}))

    async def disconnect(self, close_code):
        print(f"[WS Disconnect] Connection closed with code {close_code}.")
        if hasattr(self, "is_admin") and self.is_admin:
            await self.channel_layer.group_discard("bus_admins", self.channel_name)
        elif hasattr(self, "user") and hasattr(self, "is_driver") and self.is_driver:
            await self.channel_layer.group_discard(f"bus_{self.user.id}", self.channel_name)

        if hasattr(self, "tracked_groups"):
            for group_name in self.tracked_groups:
                await self.channel_layer.group_discard(group_name, self.channel_name)

        # Cancel the mock simulation if it is running
        if hasattr(self, "mock_task") and self.mock_task:
            self.mock_task.cancel()

    # ------------------------------------------------------------------ #
    # Receive GPS from Driver or Subscriptions from Client
    # ------------------------------------------------------------------ #

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            action = data.get("action")

            # Student/viewer subscribes to route live updates
            if action == "track_route":
                route_id = data.get("route_id")
                print(f"[WS Receive] track_route request received for Route ID: {route_id}")
                if route_id:
                    allowed = await self._can_track_route(route_id, self.schema)
                    if not allowed:
                        await self.send(text_data=json.dumps({
                            "type": "track_route_denied",
                            "route_id": route_id,
                            "message": "You do not have an active subscription for this route."
                        }))
                        return

                    group_name = f"bus_route_{route_id}"
                    await self.channel_layer.group_add(group_name, self.channel_name)
                    if group_name not in self.tracked_groups:
                        self.tracked_groups.append(group_name)
                    await self.send(text_data=json.dumps({
                        "type": "track_route_ack",
                        "route_id": route_id,
                        "message": f"Now tracking route {route_id}"
                    }))

                    # Check if there is already an active driver for this route
                    has_driver = await self._has_active_driver(route_id, self.schema)
                    if not has_driver:
                        # Cancel existing mock task if any
                        if self.mock_task:
                            self.mock_task.cancel()
                        # Start a mock bus location simulator in the background
                        self.mock_task = asyncio.create_task(self._simulate_bus_route(route_id))
                return

            if not self.is_driver:
                return

            lat = data.get("lat")
            lng = data.get("lng")
            if lat is None or lng is None:
                return

            result = await self._update_bus_location(float(lat), float(lng), self.schema)
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

            # Broadcast to route group
            if route_info:
                route_id = route_info.get("id")
                route_group = f"bus_route_{route_id}"
                await self.channel_layer.group_send(route_group, payload)

                # Check geofences
                geofences = await self._check_route_geofences(route_info, snapped_lat, snapped_lng, self.schema)
                for alert in geofences:
                    alert_payload = {
                        "type": "bus_geofence_alert",
                        "route_id": route_id,
                        "route_name": route_info.get("name"),
                        "stop_name": alert["stop_name"],
                        "distance_metres": alert["distance"],
                        "message": f"Bus is approaching stop '{alert['stop_name']}' ({alert['distance']:.0f}m away)."
                    }
                    await self.channel_layer.group_send(route_group, alert_payload)
                    await self.channel_layer.group_send("bus_admins", alert_payload)

            # Ack back to the driver
            await self.send(text_data=json.dumps({**payload, "type": "location_ack"}))

        except Exception:
            traceback.print_exc()

    # ------------------------------------------------------------------ #
    # Channel layer message handlers (called by group_send)
    # ------------------------------------------------------------------ #

    async def bus_location_update(self, event):
        await self.send(text_data=json.dumps(event))

    async def bus_geofence_alert(self, event):
        await self.send(text_data=json.dumps(event))

    # ------------------------------------------------------------------ #
    # Database and Geofencing helpers
    # ------------------------------------------------------------------ #

    @database_sync_to_async
    def _get_user_by_id(self, uid, s_name):
        from django.contrib.auth.models import User
        with schema_context(s_name):
            try:
                return User.objects.get(id=uid)
            except User.DoesNotExist:
                return None

    @database_sync_to_async
    def _has_active_driver(self, route_id, schema_name):
        from campusflow_app.models import BusLocation
        from django.utils import timezone
        from datetime import timedelta
        with schema_context(schema_name):
            cutoff = timezone.now() - timedelta(minutes=5)
            return BusLocation.objects.filter(route_id=route_id, updated_at__gte=cutoff).exists()

    @database_sync_to_async
    def _can_track_route(self, route_id, schema_name):
        """Admins may watch any route; everyone else needs a currently-valid subscription to it."""
        if self.is_admin:
            return True
        from campusflow_app.models import BusSubscription
        from django.db.models import Q
        from django.utils import timezone
        with schema_context(schema_name):
            today = timezone.localdate()
            return BusSubscription.objects.filter(
                user=self.user, route_id=route_id,
                status=BusSubscription.STATUS_ACTIVE,
                valid_from__lte=today,
            ).filter(
                Q(valid_until__isnull=True) | Q(valid_until__gte=today)
            ).exists()

    @database_sync_to_async
    def _check_route_geofences(self, route_info, bus_lat, bus_lng, schema_name):
        from campusflow_app.models import BusTrail
        with schema_context(schema_name):
            stops = route_info.get("stops", [])
            if not stops:
                return []

            alerts = []
            prev = BusTrail.objects.filter(user=self.user).order_by("-timestamp")
            prev_pt = None
            if prev.count() > 1:
                prev_pt = prev[1]

            for stop in stops:
                stop_name = stop.get("name", "")
                try:
                    stop_lat = float(stop.get("lat"))
                    stop_lng = float(stop.get("lng"))
                except (ValueError, TypeError):
                    continue

                dist_now = calculate_distance(bus_lat, bus_lng, stop_lat, stop_lng)

                # 2000m Geofence
                if dist_now <= 2000.0:
                    if prev_pt:
                        dist_prev = calculate_distance(prev_pt.lat, prev_pt.lng, stop_lat, stop_lng)
                        # Alert only when entering range
                        if dist_prev > 2000.0:
                            alerts.append({"stop_name": stop_name, "distance": dist_now})
                    else:
                        alerts.append({"stop_name": stop_name, "distance": dist_now})
            return alerts

    @database_sync_to_async
    def _is_bus_driver(self, schema_name):
        from campusflow_app.models import BusRoute
        with schema_context(schema_name):
            return BusRoute.objects.filter(driver=self.user, is_active=True).exists()

    @database_sync_to_async
    def _update_bus_location(self, lat, lng, schema_name):
        from campusflow_app.models import BusRoute, BusLocation, BusTrail
        from django.utils import timezone
        from datetime import timedelta

        try:
            with schema_context(schema_name):
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
                            return self._build_result(lat, lng, route, schema_name)

                    # Jitter filter — don't store if barely moved
                    if dist < self.JITTER_THRESHOLD_M:
                        BusLocation.objects.update_or_create(
                            user=self.user,
                            defaults={"lat": lat, "lng": lng, "route": route},
                        )
                        return self._build_result(lat, lng, route, schema_name)

                # ----- Save live position -----
                BusLocation.objects.update_or_create(
                    user=self.user,
                    defaults={"lat": lat, "lng": lng, "route": route},
                )

                # ----- Append trail breadcrumb -----
                BusTrail.objects.create(user=self.user, route=route, lat=lat, lng=lng)

                return self._build_result(lat, lng, route, schema_name)

        except Exception:
            traceback.print_exc()
            return None

    def _build_result(self, lat, lng, route, schema_name):
        """Build the trail + metadata tuple from DB."""
        from campusflow_app.models import BusTrail
        from django.utils import timezone
        from datetime import timedelta

        with schema_context(schema_name):
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
    def _get_all_buses_state(self, schema_name):
        """Return initial state of all active buses for admin dashboard."""
        from campusflow_app.models import BusLocation
        from django.utils import timezone
        from datetime import timedelta

        with schema_context(schema_name):
            cutoff = timezone.now() - timedelta(hours=12)
            active = BusLocation.objects.select_related("user", "route").filter(updated_at__gte=cutoff)

            buses = []
            for loc in active:
                result = self._build_result(loc.lat, loc.lng, loc.route, schema_name)
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

    # ------------------------------------------------------------------ #
    # Mock Route Simulation Generator Task
    # ------------------------------------------------------------------ #

    async def _simulate_bus_route(self, route_id):
        from campusflow_app.models import BusRoute
        from django_tenants.utils import schema_context
        from django.utils import timezone

        # Fetch route stops details from database
        @database_sync_to_async
        def get_route_stops(r_id, s_name):
            with schema_context(s_name):
                try:
                    route = BusRoute.objects.get(id=r_id)
                    return route.name, list(route.stops)
                except BusRoute.DoesNotExist:
                    return None, []

        route_name, stops = await get_route_stops(route_id, self.schema)
        if not stops:
            return

        print(f"[WS Simulator] Starting mock bus simulation for route {route_id} ({route_name})")

        try:
            # Create a path of points by interpolating between consecutive stops
            path = []
            for i in range(len(stops) - 1):
                s1 = stops[i]
                s2 = stops[i+1]
                lat1, lng1 = float(s1["lat"]), float(s1["lng"])
                lat2, lng2 = float(s2["lat"]), float(s2["lng"])
                # 10 interpolation steps between each stop for a smooth moving effect
                steps = 10
                for step in range(steps):
                    t = step / steps
                    lat = lat1 + (lat2 - lat1) * t
                    lng = lng1 + (lng2 - lng1) * t
                    path.append((lat, lng))
            
            # Add final stop
            final = stops[-1]
            path.append((float(final["lat"]), float(final["lng"])))

            idx = 0
            while True:
                lat, lng = path[idx % len(path)]
                
                payload = {
                    "type": "bus_location_update",
                    "driver_id": "mock_driver",
                    "driver_name": "Demo Simulator (Auto-Push)",
                    "lat": lat,
                    "lng": lng,
                    "trail": [[p[0], p[1]] for p in path[:idx % len(path) + 1]],
                    "distance_km": round((idx % len(path)) * 0.3, 2),
                    "route": {
                        "id": route_id,
                        "name": route_name,
                        "stops": stops
                    },
                    "last_seen": timezone.now().isoformat()
                }
                
                # Broadcast update to the route group (notifying student app)
                await self.channel_layer.group_send(f"bus_route_{route_id}", payload)
                
                # Sleep for 10 seconds before moving to the next simulated coordinate
                await asyncio.sleep(10)
                idx += 1
                
        except asyncio.CancelledError:
            print(f"[WS Simulator] Simulation for route {route_id} cancelled.")
        except Exception as e:
            print(f"[WS Simulator] Error in simulation: {e}")

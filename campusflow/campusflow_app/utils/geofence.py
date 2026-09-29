"""
Point-in-polygon geofencing without GDAL/PostGIS.

A classroom boundary is a list of [lat, lng] corners (Classroom.boundary).
Rooms are small, so a local equirectangular projection around the polygon is
accurate to well under a metre — plenty for GPS, whose own error is 5–15 m.
A point just outside the polygon but within `buffer_m` of an edge still
counts as inside, to absorb that GPS drift.
"""
import math

EARTH_RADIUS_M = 6_371_000


def validate_boundary(boundary):
    """Returns an error message, or None if `boundary` is a usable polygon."""
    if not isinstance(boundary, list) or len(boundary) < 3:
        return "boundary must be a list of at least 3 [lat, lng] points."
    for point in boundary:
        if not (isinstance(point, (list, tuple)) and len(point) == 2):
            return "Each boundary point must be [lat, lng]."
        lat, lng = point
        if not all(isinstance(v, (int, float)) for v in (lat, lng)):
            return "Boundary coordinates must be numbers."
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            return "Boundary coordinates are out of range."
    return None


def _to_local_xy(lat, lng, ref_lat, ref_lng):
    """Metres east (x) / north (y) of the reference point."""
    x = math.radians(lng - ref_lng) * EARTH_RADIUS_M * math.cos(math.radians(ref_lat))
    y = math.radians(lat - ref_lat) * EARTH_RADIUS_M
    return x, y


def _distance_to_segment(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    if dx == 0 and dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def point_in_boundary(lat, lng, boundary, buffer_m=0.0):
    """
    Returns (inside, distance_to_edge_m). `inside` is True when the point is
    within the polygon, or outside it by no more than `buffer_m`.
    """
    ref_lat = sum(p[0] for p in boundary) / len(boundary)
    ref_lng = sum(p[1] for p in boundary) / len(boundary)
    poly = [_to_local_xy(p[0], p[1], ref_lat, ref_lng) for p in boundary]
    px, py = _to_local_xy(lat, lng, ref_lat, ref_lng)

    # Ray casting (even-odd rule).
    inside = False
    n = len(poly)
    for i in range(n):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % n]
        if (ay > py) != (by > py):
            x_cross = ax + (py - ay) * (bx - ax) / (by - ay)
            if px < x_cross:
                inside = not inside

    edge_distance = min(
        _distance_to_segment(px, py, *poly[i], *poly[(i + 1) % n]) for i in range(n)
    )
    return inside or edge_distance <= buffer_m, round(edge_distance, 1)

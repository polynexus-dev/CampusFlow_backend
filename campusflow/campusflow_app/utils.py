import math
from django.db import connection


def calculate_distance(lat1, lon1, lat2, lon2):
    """
    Calculate the distance between two points on Earth using the Haversine formula.
    Returns distance in meters.
    """
    R = 6371000  # Radius of Earth in meters
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2)**2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    distance = R * c
    return distance


def get_current_tenant():
    """Get the current tenant from the database connection."""
    return getattr(connection, 'tenant', None)


def get_current_tenant_name():
    """Get the name of the current tenant (college)."""
    tenant = get_current_tenant()
    if tenant:
        return getattr(tenant, 'name', None) or getattr(tenant, 'schema_name', 'Public')
    return None


# Helper to get user's role string
def get_user_role_string(user):
    if hasattr(user, 'student_profile'):
        return 'student'
    elif hasattr(user, 'teaching_staff_profile'):
        return user.teaching_staff_profile.staff_role
    elif hasattr(user, 'non_teaching_staff_profile'):
        return user.non_teaching_staff_profile.staff_role
    elif hasattr(user, 'management_profile'):
        return user.management_profile.staff_role
    elif user.is_superuser:
        return 'admin'
    return 'unknown'
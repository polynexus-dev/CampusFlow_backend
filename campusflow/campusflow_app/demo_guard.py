"""
Guardrails for the public demo tenant.

The `demo` tenant's credentials are handed out publicly (in client-facing
manuals, sales demos, etc.), so it needs to stay usable for the *next*
visitor no matter what the current one does with it. This module is the
single place that answers "is the active tenant the public demo sandbox,"
and provides both a DRF permission class (for normally-authenticated views)
and a plain response helper (for the AllowAny password-recovery views, where
the tenant isn't resolved until partway through the view body, too late for
permission_classes to help).
"""

from django.db import connection
from rest_framework import status
from rest_framework.permissions import BasePermission
from rest_framework.response import Response

DEMO_BLOCK_MESSAGE = (
    "This is a public demo account shared by every visitor. Password changes, "
    "email changes, and configuration/destructive actions are disabled here "
    "so the demo stays usable for everyone — everything else is free to explore."
)


def is_demo_tenant():
    """True when the currently active tenant schema is flagged as the public demo sandbox."""
    tenant = getattr(connection, "tenant", None)
    return bool(tenant and getattr(tenant, "is_demo", False))


def demo_block_response():
    """Standard 403 for use inside AllowAny views where permission_classes can't help."""
    return Response({"error": DEMO_BLOCK_MESSAGE}, status=status.HTTP_403_FORBIDDEN)


class IsNotDemoTenant(BasePermission):
    """
    Blocks mutating requests (POST/PUT/PATCH/DELETE) when the active tenant is
    the public demo sandbox. Read access (GET/HEAD/OPTIONS) is always allowed,
    so demo visitors can still see everything — they just can't change it.
    """

    message = DEMO_BLOCK_MESSAGE

    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        return not is_demo_tenant()

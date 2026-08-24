"""
Audit Log Views
================
AuditLogListView gives College Admins read-only access to the whole tenant's
audit trail (every user, every model, plus LOGIN/LOGIN_FAILED/LOGOUT — see
models/audit.py). MyActivityView gives any authenticated user the same view
scoped to just their own actions, so "what has my account done" doesn't
require admin access to answer.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from ..models.audit import AuditLog
from ..permissions import IsCollegeAdmin


def _serialize_log(log):
    return {
        "id": log.id,
        "user": {
            "id": log.user.id if log.user else None,
            "username": log.user.username if log.user else "System",
            "full_name": log.user.get_full_name() if log.user else "System",
        },
        "action": log.action,
        "model_name": log.model_name,
        "object_id": log.object_id,
        "object_repr": log.object_repr,
        "changes": log.changes,
        "ip_address": log.ip_address,
        "user_agent": log.user_agent,
        "endpoint": log.endpoint,
        "timestamp": log.timestamp.isoformat(),
    }


def _filtered_queryset(request, base_qs):
    model_name = request.query_params.get('model')
    action = request.query_params.get('action')
    date_from = request.query_params.get('date_from')
    date_to = request.query_params.get('date_to')
    search = request.query_params.get('search')

    qs = base_qs
    if model_name:
        qs = qs.filter(model_name__icontains=model_name)
    if action:
        qs = qs.filter(action=action.upper())
    if date_from:
        qs = qs.filter(timestamp__date__gte=date_from)
    if date_to:
        qs = qs.filter(timestamp__date__lte=date_to)
    if search:
        qs = qs.filter(object_repr__icontains=search)

    # Pagination — return last 200 entries by default, capped so a caller
    # can't request an unbounded dump via ?limit=
    limit = min(int(request.query_params.get('limit', 200)), 1000)
    return qs[:limit]


class AuditLogListView(APIView):
    """
    GET all audit log entries with optional filters.
    Only College Admins (Management/Administrator) can access.
    """
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def get(self, request):
        qs = AuditLog.objects.all().select_related('user')

        user_id = request.query_params.get('user_id')
        if user_id:
            qs = qs.filter(user__id=user_id)

        qs = _filtered_queryset(request, qs)
        return Response([_serialize_log(log) for log in qs], status=status.HTTP_200_OK)


class MyActivityView(APIView):
    """
    GET the requesting user's own activity: every CREATE/UPDATE/DELETE they
    made plus their own LOGIN/LOGIN_FAILED/LOGOUT history. No admin
    permission required — this is always scoped to request.user, so it can
    never surface another account's activity.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = AuditLog.objects.filter(user=request.user).select_related('user')
        qs = _filtered_queryset(request, qs)
        return Response([_serialize_log(log) for log in qs], status=status.HTTP_200_OK)

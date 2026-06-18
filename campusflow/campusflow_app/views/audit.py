"""
Audit Log Views
================
Provides read-only access to the audit trail for College Admins.
Supports filtering by user, model, action type, and date range.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from ..models.audit import AuditLog
from ..permissions import IsCollegeAdmin


class AuditLogListView(APIView):
    """
    GET all audit log entries with optional filters.
    Only College Admins (Management/Administrator) can access.
    """
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def get(self, request):
        qs = AuditLog.objects.all().select_related('user')

        # Optional filters
        user_id = request.query_params.get('user_id')
        model_name = request.query_params.get('model')
        action = request.query_params.get('action')
        date_from = request.query_params.get('date_from')
        date_to = request.query_params.get('date_to')
        search = request.query_params.get('search')

        if user_id:
            qs = qs.filter(user__id=user_id)
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

        # Pagination — return last 200 entries by default
        limit = int(request.query_params.get('limit', 200))
        qs = qs[:limit]

        data = []
        for log in qs:
            data.append({
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
            })

        return Response(data, status=status.HTTP_200_OK)

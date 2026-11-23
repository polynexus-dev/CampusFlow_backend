"""
Notifications Views
====================
Generic in-app notification inbox, shared by every workstream (bus events,
homework posts, marks publish, correction approvals, ...) via
campusflow_app.services.notifications.notify_user / notify_guardians_of_student.
"""

from django.db import connection
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Notification


def _serialize(n):
    return {
        "id": n.id,
        "title": n.title,
        "body": n.body,
        "category": n.category,
        "data": n.data,
        "is_read": n.is_read,
        "created_at": n.created_at.isoformat(),
    }


class NotificationListView(APIView):
    """
    GET /api/notifications/?unread=true&limit=50
    Lists the current user's notifications, most recent first.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if getattr(connection, "schema_name", "public") == "public":
            return Response({"results": []}, status=status.HTTP_200_OK)

        qs = Notification.objects.filter(recipient=request.user)

        if request.query_params.get("unread") == "true":
            qs = qs.filter(is_read=False)

        limit = min(int(request.query_params.get("limit", 50)), 200)
        qs = qs[:limit]

        return Response({
            "results": [_serialize(n) for n in qs],
        }, status=status.HTTP_200_OK)


class NotificationMarkReadView(APIView):
    """
    POST /api/notifications/<id>/read/
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        if getattr(connection, "schema_name", "public") == "public":
            return Response({"error": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            notification = Notification.objects.get(pk=pk, recipient=request.user)
        except Notification.DoesNotExist:
            return Response({"error": "Notification not found."}, status=status.HTTP_404_NOT_FOUND)

        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=["is_read"])

        return Response(_serialize(notification), status=status.HTTP_200_OK)


class NotificationUnreadCountView(APIView):
    """
    GET /api/notifications/unread-count/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if getattr(connection, "schema_name", "public") == "public":
            return Response({"unread_count": 0}, status=status.HTTP_200_OK)
        count = Notification.objects.filter(recipient=request.user, is_read=False).count()
        return Response({"unread_count": count}, status=status.HTTP_200_OK)

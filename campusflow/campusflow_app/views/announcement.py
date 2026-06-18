"""
Announcement Views
===================
College-wide broadcast system. Faculty and above can create,
all authenticated users can view (filtered by their role/department).
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q
from django.utils import timezone
from ..models.announcement import Announcement
from ..permissions import (
    IsCollegeAdmin, IsFacultyOrAbove,
    get_user_group, is_saas_admin, is_college_admin
)


class AnnouncementListCreateView(APIView):
    """
    GET: List announcements visible to the requesting user (filtered by role/department).
    POST: Create a new announcement (Faculty and above only).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user_group = get_user_group(user)
        now = timezone.now()

        # Exclude expired announcements
        qs = Announcement.objects.filter(
            Q(expires_at__isnull=True) | Q(expires_at__gt=now)
        )

        # Role-based filtering: only show announcements targeting the user's role
        # If target_roles is empty list, it means "all roles"
        if not is_saas_admin(user) and not is_college_admin(user):
            # For non-admins, filter by role targeting
            # Show announcements that target the user's role OR have empty target_roles (= all)
            filtered = []
            for ann in qs:
                if not ann.target_roles or user_group in ann.target_roles:
                    filtered.append(ann.id)
            qs = qs.filter(id__in=filtered)

        data = []
        for ann in qs.select_related('author'):
            data.append({
                "id": ann.id,
                "title": ann.title,
                "content": ann.content,
                "author": {
                    "id": ann.author.id,
                    "username": ann.author.username,
                    "full_name": ann.author.get_full_name(),
                },
                "priority": ann.priority,
                "target_roles": ann.target_roles,
                "target_departments": list(ann.target_departments.values_list('name', flat=True)),
                "is_pinned": ann.is_pinned,
                "expires_at": ann.expires_at.isoformat() if ann.expires_at else None,
                "created_at": ann.created_at.isoformat(),
                "updated_at": ann.updated_at.isoformat(),
            })

        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        # Only Faculty and above can create announcements
        if not IsFacultyOrAbove().has_permission(request, self):
            return Response(
                {"error": "Only Faculty and above can create announcements."},
                status=status.HTTP_403_FORBIDDEN
            )

        title = request.data.get('title', '').strip()
        content = request.data.get('content', '').strip()
        priority = request.data.get('priority', 'normal')
        target_roles = request.data.get('target_roles', [])
        target_dept_ids = request.data.get('target_departments', [])
        is_pinned = request.data.get('is_pinned', False)
        expires_at = request.data.get('expires_at', None)

        if not title or not content:
            return Response(
                {"error": "Title and content are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        announcement = Announcement.objects.create(
            title=title,
            content=content,
            author=request.user,
            priority=priority,
            target_roles=target_roles,
            is_pinned=is_pinned,
            expires_at=expires_at,
        )

        if target_dept_ids:
            from ..models.department import Department
            departments = Department.objects.filter(id__in=target_dept_ids)
            announcement.target_departments.set(departments)

        return Response(
            {"message": "Announcement created successfully.", "id": announcement.id},
            status=status.HTTP_201_CREATED
        )


class AnnouncementDetailView(APIView):
    """
    GET: Retrieve a single announcement.
    PUT: Update (author or College Admin).
    DELETE: Remove (author or College Admin).
    """
    permission_classes = [IsAuthenticated]

    def get_announcement(self, pk):
        try:
            return Announcement.objects.get(id=pk)
        except Announcement.DoesNotExist:
            return None

    def get(self, request, pk):
        ann = self.get_announcement(pk)
        if not ann:
            return Response({"error": "Announcement not found."}, status=status.HTTP_404_NOT_FOUND)

        data = {
            "id": ann.id,
            "title": ann.title,
            "content": ann.content,
            "author": {
                "id": ann.author.id,
                "username": ann.author.username,
                "full_name": ann.author.get_full_name(),
            },
            "priority": ann.priority,
            "target_roles": ann.target_roles,
            "target_departments": list(ann.target_departments.values_list('id', 'name')),
            "is_pinned": ann.is_pinned,
            "expires_at": ann.expires_at.isoformat() if ann.expires_at else None,
            "created_at": ann.created_at.isoformat(),
        }
        return Response(data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        ann = self.get_announcement(pk)
        if not ann:
            return Response({"error": "Announcement not found."}, status=status.HTTP_404_NOT_FOUND)

        # Only author or college admin can edit
        if ann.author != request.user and not is_college_admin(request.user):
            return Response({"error": "You can only edit your own announcements."}, status=status.HTTP_403_FORBIDDEN)

        ann.title = request.data.get('title', ann.title)
        ann.content = request.data.get('content', ann.content)
        ann.priority = request.data.get('priority', ann.priority)
        ann.target_roles = request.data.get('target_roles', ann.target_roles)
        ann.is_pinned = request.data.get('is_pinned', ann.is_pinned)
        ann.expires_at = request.data.get('expires_at', ann.expires_at)
        ann.save()

        target_dept_ids = request.data.get('target_departments')
        if target_dept_ids is not None:
            from ..models.department import Department
            departments = Department.objects.filter(id__in=target_dept_ids)
            ann.target_departments.set(departments)

        return Response({"message": "Announcement updated successfully."}, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        ann = self.get_announcement(pk)
        if not ann:
            return Response({"error": "Announcement not found."}, status=status.HTTP_404_NOT_FOUND)

        if ann.author != request.user and not is_college_admin(request.user):
            return Response({"error": "You can only delete your own announcements."}, status=status.HTTP_403_FORBIDDEN)

        ann.delete()
        return Response({"message": "Announcement deleted."}, status=status.HTTP_204_NO_CONTENT)

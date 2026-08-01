"""
Quick-create posts
===================
Unifies homework (Assignment) and announcement (Announcement) creation
behind one endpoint, matching the Teacher App's "Homework / Announcement"
tab-toggle quick-create screen — a thin dispatcher over the two existing,
already-working models/endpoints rather than a replacement for them.
"""

from rest_framework import status
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Assignment, Announcement, Department, Course
from ..permissions import IsFacultyOrAbove
from ..utils.file_validation import validate_attachment
from ..services.notifications import notify_guardians_of_department


class QuickCreatePostView(APIView):
    """
    POST /api/posts/quick-create/
    Payload: {
        post_type: "homework" | "announcement",
        title, body, department_id,
        course_id, due_date        # required when post_type == "homework"
        priority                    # optional, announcement only
        notify_parents, attachment  # optional, both
    }
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        post_type = request.data.get('post_type')
        title = (request.data.get('title') or '').strip()
        body = (request.data.get('body') or '').strip()
        dept_id = request.data.get('department_id')
        notify_parents = str(request.data.get('notify_parents', False)).lower() in ('true', '1')
        attachment = request.FILES.get('attachment')

        if post_type not in ('homework', 'announcement'):
            return Response({"error": "post_type must be 'homework' or 'announcement'."}, status=status.HTTP_400_BAD_REQUEST)
        if not title or not body or not dept_id:
            return Response({"error": "title, body, and department_id are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            dept = Department.objects.get(id=dept_id)
        except Department.DoesNotExist:
            return Response({"error": "Invalid department selection."}, status=status.HTTP_400_BAD_REQUEST)

        attachment_error = validate_attachment(attachment)
        if attachment_error:
            return Response({"error": attachment_error}, status=status.HTTP_400_BAD_REQUEST)

        if post_type == 'homework':
            course_id = request.data.get('course_id')
            due_date = request.data.get('due_date')
            if not course_id or not due_date:
                return Response({"error": "course_id and due_date are required for homework."}, status=status.HTTP_400_BAD_REQUEST)

            try:
                course = Course.objects.get(id=course_id)
            except Course.DoesNotExist:
                return Response({"error": "Invalid course selection."}, status=status.HTTP_400_BAD_REQUEST)

            post = Assignment.objects.create(
                title=title,
                description=body,
                department=dept,
                course=course,
                due_date=due_date,
                attachment=attachment,
                notify_parents=notify_parents,
                created_by=request.user,
            )
            if notify_parents:
                notify_guardians_of_department(
                    dept.id,
                    title=f"New homework: {title}",
                    body=f"{course.course_name} · due {post.due_date}",
                    category="homework",
                    data={"assignment_id": post.id},
                )
        else:
            priority = request.data.get('priority', 'normal')
            post = Announcement.objects.create(
                title=title,
                content=body,
                author=request.user,
                priority=priority,
                notify_parents=notify_parents,
            )
            post.target_departments.set([dept])
            if notify_parents:
                notify_guardians_of_department(
                    dept.id,
                    title=f"Announcement: {title}",
                    body=body,
                    category="announcement",
                    data={"announcement_id": post.id},
                )

        return Response(
            {"message": f"{post_type.capitalize()} created successfully.", "post_type": post_type, "id": post.id},
            status=status.HTTP_201_CREATED,
        )

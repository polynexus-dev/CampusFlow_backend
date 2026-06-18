from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from ..models.assignment import Assignment
from ..models.department import Department
from ..models.course import Course
from ..permissions import IsFacultyOrAbove, get_user_group, is_college_admin

class AssignmentListCreateView(APIView):
    """
    GET: List assignments. Filtered automatically for students by their department.
    POST: Create a new assignment (Faculty/HOD/Admin only, supports file attachments).
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        user = request.user
        user_group = get_user_group(user)
        qs = Assignment.objects.all().select_related('department', 'course', 'created_by')

        # Filters
        dept_id = request.query_params.get('department_id')
        course_id = request.query_params.get('course_id')

        if dept_id:
            qs = qs.filter(department_id=dept_id)
        if course_id:
            qs = qs.filter(course_id=course_id)

        # Students can only see assignments in their department
        if user_group == 'student':
            profile = getattr(user, 'student_profile', None)
            if profile and profile.department:
                qs = qs.filter(department=profile.department)
            else:
                qs = qs.none()

        data = []
        for a in qs:
            data.append({
                "id": a.id,
                "title": a.title,
                "description": a.description,
                "department_id": a.department_id,
                "department_name": a.department.name,
                "course_id": a.course_id,
                "course_code": a.course.course_code,
                "course_name": a.course.course_name,
                "due_date": a.due_date.isoformat(),
                "attachment": a.attachment.url if a.attachment else None,
                "created_by": a.created_by.get_full_name() or a.created_by.username,
                "created_at": a.created_at.isoformat()
            })
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        if not IsFacultyOrAbove().has_permission(request, self):
            return Response({"error": "Only Faculty or Admins can post assignments."}, status=status.HTTP_403_FORBIDDEN)

        title = request.data.get('title', '').strip()
        description = request.data.get('description', '').strip()
        due_date = request.data.get('due_date')
        dept_id = request.data.get('department_id')
        course_id = request.data.get('course_id')
        attachment = request.FILES.get('attachment')

        if not title or not description or not due_date or not dept_id or not course_id:
            return Response({"error": "title, description, due_date, department_id, and course_id are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            dept = Department.objects.get(id=dept_id)
            course = Course.objects.get(id=course_id)
        except (Department.DoesNotExist, Course.DoesNotExist) as e:
            return Response({"error": "Invalid department or course selection."}, status=status.HTTP_400_BAD_REQUEST)

        assignment = Assignment.objects.create(
            title=title,
            description=description,
            department=dept,
            course=course,
            due_date=due_date,
            attachment=attachment,
            created_by=request.user
        )

        return Response({
            "message": "Assignment created successfully.",
            "id": assignment.id
        }, status=status.HTTP_201_CREATED)


class AssignmentDetailView(APIView):
    """
    GET: Retrieve single assignment details.
    PUT/DELETE: Update or delete assignment (Owner or Admin only).
    """
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, pk):
        try:
            a = Assignment.objects.select_related('department', 'course', 'created_by').get(id=pk)
        except Assignment.DoesNotExist:
            return Response({"error": "Assignment not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "id": a.id,
            "title": a.title,
            "description": a.description,
            "department_id": a.department_id,
            "department_name": a.department.name,
            "course_id": a.course_id,
            "course_code": a.course.course_code,
            "course_name": a.course.course_name,
            "due_date": a.due_date.isoformat(),
            "attachment": a.attachment.url if a.attachment else None,
            "created_by_id": a.created_by_id,
            "created_by": a.created_by.get_full_name() or a.created_by.username,
            "created_at": a.created_at.isoformat()
        }, status=status.HTTP_200_OK)

    def put(self, request, pk):
        try:
            a = Assignment.objects.get(id=pk)
        except Assignment.DoesNotExist:
            return Response({"error": "Assignment not found."}, status=status.HTTP_404_NOT_FOUND)

        # Permission check: Owner or Admin
        if a.created_by != request.user and not is_college_admin(request.user):
            return Response({"error": "You are not authorized to update this assignment."}, status=status.HTTP_403_FORBIDDEN)

        a.title = request.data.get('title', a.title)
        a.description = request.data.get('description', a.description)
        a.due_date = request.data.get('due_date', a.due_date)
        
        if 'department_id' in request.data:
            try:
                a.department = Department.objects.get(id=request.data['department_id'])
            except Department.DoesNotExist:
                pass
        
        if 'course_id' in request.data:
            try:
                a.course = Course.objects.get(id=request.data['course_id'])
            except Course.DoesNotExist:
                pass

        if 'attachment' in request.FILES:
            a.attachment = request.FILES['attachment']

        a.save()
        return Response({"message": "Assignment updated."}, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        try:
            a = Assignment.objects.get(id=pk)
        except Assignment.DoesNotExist:
            return Response({"error": "Assignment not found."}, status=status.HTTP_404_NOT_FOUND)

        if a.created_by != request.user and not is_college_admin(request.user):
            return Response({"error": "You are not authorized to delete this assignment."}, status=status.HTTP_403_FORBIDDEN)

        a.delete()
        return Response({"message": "Assignment deleted."}, status=status.HTTP_200_OK)

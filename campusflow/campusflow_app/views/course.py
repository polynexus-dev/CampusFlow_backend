from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from ..models.course import Course
from ..models.department import Department
from ..permissions import IsCollegeAdmin

class CourseListCreateView(APIView):
    """
    GET: List all courses in the tenant schema. Can filter by ?department_id=X.
    POST: Create a new course (College Admin only).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        dept_id = request.query_params.get('department_id')
        if dept_id:
            courses = Course.objects.filter(department_id=dept_id)
        else:
            courses = Course.objects.all().select_related('department')

        data = []
        for c in courses:
            data.append({
                "id": c.id,
                "course_code": c.course_code,
                "course_name": c.course_name,
                "department_id": c.department.id,
                "department_name": c.department.name
            })
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        if not IsCollegeAdmin().has_permission(request, self):
            return Response({"error": "Only College Admin can create courses."}, status=status.HTTP_403_FORBIDDEN)

        code = request.data.get('course_code', '').strip().upper()
        name = request.data.get('course_name', '').strip()
        dept_id = request.data.get('department_id')

        if not code or not name or not dept_id:
            return Response({"error": "course_code, course_name, and department_id are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            dept = Department.objects.get(id=dept_id)
        except Department.DoesNotExist:
            return Response({"error": "Department not found."}, status=status.HTTP_404_NOT_FOUND)

        if Course.objects.filter(course_code=code).exists():
            return Response({"error": f"Course with code '{code}' already exists."}, status=status.HTTP_400_BAD_REQUEST)

        course = Course.objects.create(
            course_code=code,
            course_name=name,
            department=dept
        )

        return Response({
            "message": "Course created.",
            "id": course.id
        }, status=status.HTTP_201_CREATED)

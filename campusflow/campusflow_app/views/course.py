from django.db import IntegrityError
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.academics import Regulation
from ..models.course import Course
from ..models.department import Department
from ..permissions import IsCollegeAdmin

# Credit-bearing attributes. Grouped because a locked Regulation freezes exactly
# these — they are the values a transcript was computed from.
CURRICULUM_FIELDS = (
    "semester_number", "course_type", "credits",
    "lecture_hours", "tutorial_hours", "practical_hours",
    "is_credit_bearing", "counts_toward_cgpa",
)


def _serialize_course(c):
    """
    NOTE: the list endpoint returns a bare array, not a {"results": [...]} envelope.
    Assignments.jsx and Exams.jsx both read `res.data` directly, so the shape is
    load-bearing — new keys are additive but the array must stay an array.
    """
    return {
        "id": c.id,
        "course_code": c.course_code,
        "course_name": c.course_name,
        "department_id": c.department_id,
        "department_name": c.department.name if c.department_id else None,
        # ── curriculum spine ──
        "regulation_id": c.regulation_id,
        "regulation_code": c.regulation.code if c.regulation_id else None,
        "semester_number": c.semester_number,
        "course_type": c.course_type,
        "credits": float(c.credits) if c.credits is not None else None,
        "lecture_hours": c.lecture_hours,
        "tutorial_hours": c.tutorial_hours,
        "practical_hours": c.practical_hours,
        "total_contact_hours": c.total_contact_hours,
        "is_credit_bearing": c.is_credit_bearing,
        "counts_toward_cgpa": c.counts_toward_cgpa,
        "canonical_code": c.canonical_code,
        "is_active": c.is_active,
    }


def _apply_curriculum_fields(course, data):
    """Copy whichever curriculum attributes are present in `data` onto `course`."""
    int_fields = ("semester_number", "lecture_hours", "tutorial_hours", "practical_hours")
    for field in CURRICULUM_FIELDS:
        if field not in data:
            continue
        value = data.get(field)
        if field in ("is_credit_bearing", "counts_toward_cgpa"):
            setattr(course, field, bool(value))
        elif field == "course_type":
            setattr(course, field, value or Course.TYPE_CORE)
        elif field in int_fields:
            if value in (None, ""):
                # semester_number is nullable; the hour counts are not.
                setattr(course, field, None if field == "semester_number" else 0)
            else:
                try:
                    setattr(course, field, int(value))
                except (TypeError, ValueError):
                    raise ValueError(f"{field} must be a whole number.")
        else:  # credits
            setattr(course, field, value if value not in (None, "") else None)


class CourseListCreateView(APIView):
    """
    GET: List courses in the tenant schema.
         Filters: ?department_id= ?regulation_id= ?semester_number= ?is_active=true
    POST: Create a course (College Admin only). Accepts the curriculum fields;
          omit regulation_id to create a legacy, unscoped course.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        courses = Course.objects.select_related('department', 'regulation')

        dept_id = request.query_params.get('department_id')
        if dept_id:
            courses = courses.filter(department_id=dept_id)
        regulation_id = request.query_params.get('regulation_id')
        if regulation_id:
            courses = courses.filter(regulation_id=regulation_id)
        semester = request.query_params.get('semester_number')
        if semester:
            courses = courses.filter(semester_number=semester)
        if request.query_params.get('is_active') == 'true':
            courses = courses.filter(is_active=True)

        return Response([_serialize_course(c) for c in courses], status=status.HTTP_200_OK)

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

        regulation = None
        if request.data.get('regulation_id'):
            regulation = Regulation.objects.filter(pk=request.data.get('regulation_id')).first()
            if not regulation:
                return Response({"error": "Invalid regulation_id."}, status=status.HTTP_400_BAD_REQUEST)
            if regulation.is_locked:
                return Response(
                    {"error": f"Regulation '{regulation.code}' is locked. Unlock it before adding courses."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # Uniqueness is scoped to the regulation, matching the DB constraints: two
        # regulations may each define CS301, one regulation may not define it twice,
        # and legacy (unscoped) courses stay globally unique.
        if Course.objects.filter(course_code=code, regulation=regulation).exists():
            scope = f"regulation '{regulation.code}'" if regulation else "the course catalogue"
            return Response({"error": f"Course '{code}' already exists in {scope}."}, status=status.HTTP_400_BAD_REQUEST)

        course = Course(
            course_code=code,
            course_name=name,
            department=dept,
            regulation=regulation,
            canonical_code=(request.data.get('canonical_code') or '').strip().upper(),
        )
        try:
            _apply_curriculum_fields(course, request.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            course.save()
        except IntegrityError:
            return Response({"error": f"Course '{code}' already exists."}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            "message": "Course created.",
            "id": course.id,
            "course": _serialize_course(course),
        }, status=status.HTTP_201_CREATED)


class CourseDetailView(APIView):
    """
    GET    /api/courses/<pk>/
    PUT    /api/courses/<pk>/     — College Admin only
    DELETE /api/courses/<pk>/     — College Admin only

    Added alongside the curriculum fields: without an update path, credits could
    be set at creation and then never corrected.
    """
    permission_classes = [IsAuthenticated]

    def _get(self, pk):
        return Course.objects.select_related('department', 'regulation').filter(pk=pk).first()

    def get(self, request, pk):
        course = self._get(pk)
        if not course:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_course(course), status=status.HTTP_200_OK)

    def put(self, request, pk):
        if not IsCollegeAdmin().has_permission(request, self):
            return Response({"error": "Only College Admin can update courses."}, status=status.HTTP_403_FORBIDDEN)

        course = self._get(pk)
        if not course:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        # A locked regulation means transcripts have been issued against these
        # credits. Renaming stays allowed; re-weighting does not.
        if course.regulation_id and course.regulation.is_locked:
            frozen = [f for f in CURRICULUM_FIELDS if f in request.data]
            if frozen:
                return Response(
                    {"error": f"Regulation '{course.regulation.code}' is locked, so "
                              f"{', '.join(frozen)} cannot be changed. Results already "
                              f"computed from these values would silently shift."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        if 'course_name' in request.data:
            name = (request.data.get('course_name') or '').strip()
            if not name:
                return Response({"error": "course_name cannot be blank."}, status=status.HTTP_400_BAD_REQUEST)
            course.course_name = name
        if 'course_code' in request.data:
            code = (request.data.get('course_code') or '').strip().upper()
            if not code:
                return Response({"error": "course_code cannot be blank."}, status=status.HTTP_400_BAD_REQUEST)
            course.course_code = code
        if 'canonical_code' in request.data:
            course.canonical_code = (request.data.get('canonical_code') or '').strip().upper()
        if 'department_id' in request.data:
            dept = Department.objects.filter(pk=request.data.get('department_id')).first()
            if not dept:
                return Response({"error": "Invalid department_id."}, status=status.HTTP_400_BAD_REQUEST)
            course.department = dept
        if 'is_active' in request.data:
            course.is_active = bool(request.data.get('is_active'))

        try:
            _apply_curriculum_fields(course, request.data)
        except ValueError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)

        try:
            course.save()
        except IntegrityError:
            return Response(
                {"error": "Another course with that code already exists in this regulation."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(_serialize_course(course), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        if not IsCollegeAdmin().has_permission(request, self):
            return Response({"error": "Only College Admin can delete courses."}, status=status.HTTP_403_FORBIDDEN)

        course = self._get(pk)
        if not course:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            course.delete()
        except ProtectedError:
            return Response(
                {"error": "This course has exams, schedules or assignments attached. "
                          "Deactivate it instead of deleting."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)

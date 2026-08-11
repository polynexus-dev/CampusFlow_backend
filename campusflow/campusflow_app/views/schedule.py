from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q
from django.utils import timezone

from ..models.schedule import Schedule
from ..models.lecture import Lecture
from ..models.attendance import Attendance
from ..serializers import ScheduleSerializer
from ..permissions import get_user_group, is_saas_admin, IsFacultyOrAbove
from ..utils.tenant_utils import ensure_tenant_schema


class ScheduleListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Ensure we're on the correct tenant schema (JWT fallback for IP-based requests)
        ensure_tenant_schema(request)

        user = request.user
        user_group = get_user_group(user)

        if is_saas_admin(user) or user_group in ('Management', 'Administrator'):
            # Admin roles see everything
            qs = Schedule.objects.filter(is_draft=False).select_related('course', 'classroom', 'faculty')
        elif user_group == 'student':
            # Students see their department's schedules
            profile = getattr(user, 'student_profile', None)
            if profile and hasattr(profile, 'department') and profile.department:
                qs = Schedule.objects.filter(
                    course__department=profile.department, is_draft=False,
                ).select_related('course', 'classroom', 'faculty')
            else:
                # No department set — show all schedules (demo/testing mode)
                qs = Schedule.objects.filter(is_draft=False).select_related('course', 'classroom', 'faculty')
        elif user_group == 'Faculty':
            # Faculty see their own scheduled classes (including substitutions)
            qs = Schedule.objects.filter(
                Q(faculty=user) | Q(substitute_faculty=user), is_draft=False,
            ).select_related('course', 'classroom', 'faculty')
        else:
            qs = Schedule.objects.none()

        # Optional day-of-week filter
        day = request.query_params.get('day_of_week')
        if day:
            qs = qs.filter(day_of_week=day)

        dept_id = request.query_params.get('department_id')
        if dept_id:
            qs = qs.filter(course__department_id=dept_id)

        semester = request.query_params.get('semester')
        if semester:
            qs = qs.filter(semester=semester)

        academic_year = request.query_params.get('academic_year')
        if academic_year:
            qs = qs.filter(academic_year=academic_year)

        days_order = {
            'Monday': 1, 'Tuesday': 2, 'Wednesday': 3,
            'Thursday': 4, 'Friday': 5, 'Saturday': 6, 'Sunday': 7
        }

        serialized_data = ScheduleSerializer(qs, many=True).data
        try:
            serialized_data.sort(
                key=lambda x: (days_order.get(x['day_of_week'], 8), x['start_time'])
            )
        except Exception:
            pass

        return Response(serialized_data, status=status.HTTP_200_OK)

    def post(self, request):
        # Ensure we're on the correct tenant schema (JWT fallback for IP-based requests)
        ensure_tenant_schema(request)

        user = request.user
        user_group = get_user_group(user)

        if not (is_saas_admin(user) or user_group in ('Management', 'Administrator')):
            return Response(
                {"error": "Only College Admins can create schedules."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = ScheduleSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class TeacherTodayScheduleView(APIView):
    """
    GET /api/schedule/today/
    The requesting faculty member's Lectures scheduled for today, with an
    attendance-marked count so the Teacher App's timetable screen can show
    "attendance pending" the way the design does.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request):
        ensure_tenant_schema(request)

        today = timezone.localdate()
        lectures = Lecture.objects.filter(
            faculty=request.user, start_time__date=today
        ).select_related("classroom").order_by("start_time")

        periods = []
        for lecture in lectures:
            marked_count = Attendance.objects.filter(lecture=lecture).count()
            periods.append({
                "id": lecture.id,
                "name": lecture.name,
                "subject": lecture.subject,
                "classroom": lecture.classroom.name if lecture.classroom else None,
                "start_time": lecture.start_time.isoformat(),
                "end_time": lecture.end_time.isoformat(),
                "attendance_marked_count": marked_count,
                "attendance_pending": marked_count == 0,
            })

        return Response({"date": today.isoformat(), "periods": periods}, status=status.HTTP_200_OK)

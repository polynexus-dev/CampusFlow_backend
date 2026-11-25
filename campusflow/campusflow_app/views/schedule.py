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
from ..permissions import RequiresModule, get_user_group, is_saas_admin, IsFacultyOrAbove
from ..utils.tenant_utils import ensure_tenant_schema


class ScheduleListView(APIView):
    permission_classes = [IsAuthenticated, RequiresModule("schedule")]

    def get(self, request):
        # Ensure we're on the correct tenant schema (JWT fallback for IP-based requests)
        ensure_tenant_schema(request)

        user = request.user
        user_group = get_user_group(user)

        if is_saas_admin(user) or user_group in ('Management', 'Administrator', 'Principal'):
            # Admin and Principal roles see all schedules across the college
            qs = Schedule.objects.filter(is_draft=False).select_related('course', 'classroom', 'faculty', 'course_offering__section')
        elif user_group == 'Department Head':
            # Department Head sees all schedules in their department (or all if no department set)
            hod_profile = getattr(user, 'department_head_profile', None)
            if hod_profile and hod_profile.department:
                qs = Schedule.objects.filter(
                    course__department=hod_profile.department, is_draft=False,
                ).select_related('course', 'classroom', 'faculty', 'course_offering__section')
            else:
                qs = Schedule.objects.filter(is_draft=False).select_related('course', 'classroom', 'faculty', 'course_offering__section')
        elif user_group == 'student':
            # Students see their department's and section-wise schedules
            profile = getattr(user, 'student_profile', None)
            if profile and hasattr(profile, 'department') and profile.department:
                qs = Schedule.objects.filter(
                    course__department=profile.department, is_draft=False,
                ).select_related('course', 'classroom', 'faculty', 'course_offering__section')

                # Filter section-wise if student has a section assigned
                student_section = (
                    getattr(profile, 'section_division', None)
                    or (profile.section.name if getattr(profile, 'section', None) else None)
                )
                if student_section:
                    qs = qs.filter(
                        Q(course_offering__section__name__iexact=student_section) |
                        Q(course_offering__section__isnull=True) |
                        Q(course_offering__isnull=True)
                    )

                # Filter by student's current semester if set
                sem = getattr(profile, 'current_semester_year', None) or getattr(profile, 'current_semester_number', None)
                if sem:
                    qs = qs.filter(semester__icontains=str(sem))
            else:
                # No department set — show all schedules (demo/testing mode)
                qs = Schedule.objects.filter(is_draft=False).select_related('course', 'classroom', 'faculty', 'course_offering__section')
        elif user_group == 'Faculty':
            # Faculty see only their own sessions (including substitutions)
            qs = Schedule.objects.filter(
                Q(faculty=user) | Q(substitute_faculty=user), is_draft=False,
            ).select_related('course', 'classroom', 'faculty', 'course_offering__section')
        else:
            qs = Schedule.objects.filter(is_draft=False).select_related('course', 'classroom', 'faculty', 'course_offering__section')

        # Allow HOD / Admin to filter by a specific faculty member
        faculty_id = request.query_params.get('faculty_id')
        if faculty_id and (is_saas_admin(user) or user_group in ('Management', 'Administrator', 'Principal', 'Department Head')):
            qs = qs.filter(Q(faculty_id=faculty_id) | Q(substitute_faculty_id=faculty_id))

        # Optional section / section_division filter
        section_param = request.query_params.get('section') or request.query_params.get('section_division')
        if section_param:
            qs = qs.filter(
                Q(course_offering__section__name__iexact=section_param) |
                Q(course_offering__section__isnull=True) |
                Q(course_offering__isnull=True)
            )

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

        # Optional date filter (calculates day of week automatically from date YYYY-MM-DD)
        date_param = request.query_params.get('date')
        if date_param:
            try:
                import datetime
                dt = datetime.date.fromisoformat(date_param)
                day_name = dt.strftime('%A')
                qs = qs.filter(day_of_week=day_name)
            except Exception:
                pass

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

        if not (is_saas_admin(user) or user_group in ('Management', 'Administrator', 'Department Head', 'Faculty')):
            return Response(
                {"error": "Only College Admins, Department Heads, or Faculty can create schedules."},
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
    permission_classes = [IsAuthenticated, IsFacultyOrAbove, RequiresModule("schedule")]

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
                "meeting_url": lecture.meeting_url or None,
                "meeting_provider": lecture.meeting_provider or None,
                "attendance_marked_count": marked_count,
                "attendance_pending": marked_count == 0,
            })

        return Response({"date": today.isoformat(), "periods": periods}, status=status.HTTP_200_OK)

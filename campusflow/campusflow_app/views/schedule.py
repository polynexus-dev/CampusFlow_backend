from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q

from ..models.schedule import Schedule
from ..serializers import ScheduleSerializer
from ..permissions import get_user_group, is_saas_admin
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
            qs = Schedule.objects.all().select_related('course', 'classroom', 'faculty')
        elif user_group == 'student':
            # Students see their department's schedules
            profile = getattr(user, 'student_profile', None)
            if profile and hasattr(profile, 'department') and profile.department:
                qs = Schedule.objects.filter(
                    course__department=profile.department
                ).select_related('course', 'classroom', 'faculty')
            else:
                # No department set — show all schedules (demo/testing mode)
                qs = Schedule.objects.all().select_related('course', 'classroom', 'faculty')
        elif user_group == 'Faculty':
            # Faculty see their own scheduled classes (including substitutions)
            qs = Schedule.objects.filter(
                Q(faculty=user) | Q(substitute_faculty=user)
            ).select_related('course', 'classroom', 'faculty')
        else:
            qs = Schedule.objects.none()

        # Optional day-of-week filter
        day = request.query_params.get('day_of_week')
        if day:
            qs = qs.filter(day_of_week=day)

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

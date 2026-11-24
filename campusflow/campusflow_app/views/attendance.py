"""
Attendance Views
================
Auth rules:

AttendanceMarkView (POST — manually mark someone else's attendance):
  - Only Faculty, Department Head, Administrator, Management, SaaS Admin
  - Students CANNOT manually mark attendance for other students

ViewAllAttendanceView (GET — view all attendance records):
  - Only Faculty and above (not students, not support staff)

LectureCheckinByCodeView (POST — mark attendance via Random Code):
  - Students mark their own attendance using a session-specific code.
"""

from rest_framework import generics, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from django.db import transaction
from django.db.models import Q
from campusflow_app.serializers import AttendanceSerializer
from ..models.attendance import Attendance
from ..models.location import Location
from ..utils import calculate_distance
from ..models.classroom import Classroom
from ..demo_guard import is_demo_tenant
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from ..models.lecture import Lecture
from ..models.schedule import Schedule
from ..serializers import AttendanceMarkSerializer, LectureAttendanceCodeSerializer
from ..permissions import (
    CanMarkAttendanceManually, IsFacultyOrAbove, RequiresModule,
    get_user_group, is_saas_admin
)
from rest_framework.views import APIView
from django.utils.timezone import now


class AttendanceMarkView(APIView):
    """
    Manually mark a student's attendance on their behalf.
    Only Faculty, Department Heads, and College Admins can do this.
    Students CANNOT manually mark other students' attendance.
    """
    permission_classes = [IsAuthenticated, CanMarkAttendanceManually, RequiresModule("attendance")]

    def post(self, request):
        serializer = AttendanceMarkSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        validated = serializer.validated_data
        single_student_id = validated.get('student_id')
        bulk_student_ids = validated.get('student_ids') or []
        student_ids_to_mark = bulk_student_ids if bulk_student_ids else ([single_student_id] if single_student_id else [])

        lecture_id = validated.get('lecture_id')
        schedule_id = validated.get('schedule_id')
        status_val = validated.get('status', 'present').lower()
        location_id = validated.get('location_id') or 'manual'

        lecture = Lecture.objects.filter(id=lecture_id).first() if lecture_id else None
        schedule = Schedule.objects.filter(id=schedule_id).first() if schedule_id else None

        # ── Handle Marking Absent (Unmarking Attendance) ──
        if status_val == 'absent':
            valid_students = []
            invalid_students = []
            students = User.objects.filter(id__in=student_ids_to_mark)
            student_map = {s.id: s for s in students}

            for sid in student_ids_to_mark:
                student = student_map.get(sid)
                s_group = student.groups.first().name if (student and student.groups.exists()) else None
                if not student or s_group != 'student':
                    invalid_students.append(sid)
                else:
                    valid_students.append(student)

            if not valid_students:
                return Response(
                    {"error": f"Invalid student ID(s): {invalid_students}"},
                    status=status.HTTP_400_BAD_REQUEST
                )

            filter_q = Q(user__in=valid_students)
            if lecture and schedule:
                filter_q &= (Q(lecture=lecture) | Q(schedule=schedule, check_in_time__date=now().date()))
            elif lecture:
                filter_q &= Q(lecture=lecture)
            elif schedule:
                filter_q &= Q(schedule=schedule, check_in_time__date=now().date())
            else:
                filter_q &= Q(check_in_time__date=now().date())

            deleted_count, _ = Attendance.objects.filter(filter_q).delete()

            return Response({
                "message": f"Successfully marked {len(valid_students)} student(s) absent.",
                "unmarked_count": deleted_count,
                "status": "absent",
                "invalid_student_ids": invalid_students if invalid_students else None
            }, status=status.HTTP_200_OK)

        # Resolve location if exists
        location = Location.objects.filter(location_id=location_id).first()

        marked_count = 0
        updated_count = 0
        invalid_students = []

        students = User.objects.filter(id__in=student_ids_to_mark)
        student_map = {s.id: s for s in students}

        for sid in student_ids_to_mark:
            student = student_map.get(sid)
            if not student:
                invalid_students.append(sid)
                continue

            # Ensure student role
            s_group = student.groups.first().name if student.groups.exists() else None
            if s_group != 'student':
                invalid_students.append(sid)
                continue

            if lecture is not None:
                att, created = Attendance.objects.get_or_create(
                    user=student,
                    lecture=lecture,
                    defaults={
                        'schedule': schedule,
                        'is_geofence_valid': True,
                        'verification_method': 'manual'
                    }
                )
                if not created:
                    att.is_geofence_valid = True
                    att.verification_method = 'manual'
                    if schedule and not att.schedule:
                        att.schedule = schedule
                    att.save(update_fields=['is_geofence_valid', 'verification_method', 'schedule'])
                    updated_count += 1
                else:
                    marked_count += 1

            elif schedule is not None:
                # Mark attendance linked directly to the schedule timetable slot
                att, created = Attendance.objects.get_or_create(
                    user=student,
                    schedule=schedule,
                    check_in_time__date=now().date(),
                    defaults={
                        'is_geofence_valid': True,
                        'verification_method': 'manual'
                    }
                )
                if not created:
                    att.is_geofence_valid = True
                    att.verification_method = 'manual'
                    att.save(update_fields=['is_geofence_valid', 'verification_method'])
                    updated_count += 1
                else:
                    marked_count += 1

            elif location and location.is_classroom_entry:
                Attendance.objects.create(user=student, is_geofence_valid=True, verification_method='manual')
                marked_count += 1
            elif location and location.is_premises_entry:
                Attendance.objects.create(user=student, is_geofence_valid=True, verification_method='manual')
                marked_count += 1
            else:
                # Default general manual attendance
                Attendance.objects.create(user=student, is_geofence_valid=True, verification_method='manual')
                marked_count += 1

        total_processed = marked_count + updated_count
        if total_processed == 0 and invalid_students:
            return Response(
                {"error": f"Invalid student ID(s): {invalid_students}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response({
            "message": f"Successfully marked attendance for {total_processed} student(s).",
            "marked_new": marked_count,
            "updated_existing": updated_count,
            "invalid_student_ids": invalid_students if invalid_students else None
        }, status=status.HTTP_201_CREATED if marked_count > 0 else status.HTTP_200_OK)

    def delete(self, request):
        """
        Delete/unmark attendance records (mark absent).
        Supports payload identical to POST with status='absent'.
        """
        data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        data['status'] = 'absent'
        request._full_data = data
        return self.post(request)


class AllAttendanceView(APIView):
    """
    View ALL attendance records (for reporting/admin purposes).
    Only Faculty and above can access this — students cannot see other students' records.
    Supports optional filtering by user_id and date.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove, RequiresModule("attendance")]

    def get(self, request):
        qs = Attendance.objects.all().select_related('user')

        # Optional filters
        user_id = request.query_params.get('user_id')
        date = request.query_params.get('date')

        if user_id:
            qs = qs.filter(user__id=user_id)
        if date:
            qs = qs.filter(check_in_time__date=date)

        # Cap unbounded growth by default (mirrors AuditLogListView) — this
        # table grows fastest (a row per student per lecture, every day), so
        # returning it in full on every call gets linearly slower over time.
        limit = int(request.query_params.get('limit', 200))
        qs = qs.order_by('-check_in_time')[:limit]

        serializer = AttendanceSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LectureCheckinByCodeView(APIView):
    """
    Students mark their attendance by entering the code provided by faculty.
    Validates the code and checks if the student is within the classroom's geofence.
    """
    permission_classes = [IsAuthenticated, RequiresModule("attendance")]

    def post(self, request):
        serializer = LectureAttendanceCodeSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        code = serializer.validated_data['code']
        check_in_lat = serializer.validated_data['latitude']
        check_in_lon = serializer.validated_data['longitude']

        # 1. Find the lecture with this code
        lecture = Lecture.objects.filter(code=code).first()
        if not lecture:
            return Response({"detail": "Invalid attendance code."}, status=status.HTTP_400_BAD_REQUEST)

        # 2. Check if student already marked attendance for this lecture
        if Attendance.objects.filter(user=request.user, lecture=lecture).exists():
            return Response({"detail": "You have already marked attendance for this lecture."}, status=status.HTTP_400_BAD_REQUEST)

        # --- SECURITY: DEVICE LOCKING & ANTI-PROXY ---
        device_id = request.data.get('device_id')
        if not device_id:
            return Response({"detail": "device_id is required to mark attendance."}, status=status.HTTP_400_BAD_REQUEST)

        profile = getattr(request.user, 'student_profile', None)
        if profile and not is_demo_tenant():
            # 2b. Auto-bind device on first attendance if not already bound at login
            if not profile.locked_device_id:
                profile.locked_device_id = device_id
                profile.save()

            # 2c. Enforce Device Locking
            if profile.locked_device_id != device_id:
                return Response(
                    {"detail": "Attendance can only be marked from your registered device. Please contact admin to reset your device lock."},
                    status=status.HTTP_403_FORBIDDEN
                )

        # 2d. Anti-Proxy Logic: Prevent different students from using the same device for the same lecture
        if Attendance.objects.filter(lecture=lecture, device_id=device_id).exclude(user=request.user).exists():
            return Response(
                {"detail": "This device has already been used to mark attendance for another student in this session."},
                status=status.HTTP_403_FORBIDDEN
            )

        # 3. Geofence validation
        lecture_lat = lecture.latitude
        lecture_lon = lecture.longitude
        
        if not lecture_lat or not lecture_lon:
             return Response({"detail": "This lecture does not have a geofence set by the faculty yet."}, status=status.HTTP_400_BAD_REQUEST)

        # Default geofence radius to 50 meters
        classroom = getattr(lecture, 'classroom', None)
        main_entry = getattr(classroom, 'main_entry_location', None)
        radius = main_entry.geofence_radius_meters if main_entry else 50

        distance = calculate_distance(
            float(check_in_lat), float(check_in_lon),
            float(lecture_lat), float(lecture_lon)
        )

        is_geofence_valid = distance <= radius

        if not is_geofence_valid:
            return Response(
                {
                    "detail": f"Geofence validation failed. You are {distance:.2f}m away from the classroom center.",
                    "distance": round(distance, 2),
                    "allowed_radius": radius
                },
                status=status.HTTP_403_FORBIDDEN
            )

        # 4. Create attendance record
        Attendance.objects.create(
            user=request.user,
            lecture=lecture,
            device_id=device_id,
            is_geofence_valid=True,
            verification_method='face_geofence'
        )

        return Response({"detail": "Attendance marked successfully!"}, status=status.HTTP_201_CREATED)


class StudentAttendanceSummaryView(APIView):
    """
    GET /api/student/attendance-summary/
    The logged-in student's attendance % for the current term (the same
    calculation the detention rule uses), plus the detention minimum when
    that rule is switched on. Returns percentage=None when there's no
    current term or no lectures held yet.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from ..models.academics import Term
        from ..services.detention import compute_attendance_rate, get_detention_settings

        profile = getattr(request.user, "student_profile", None)
        if profile is None:
            return Response({"error": "Only students have an attendance summary."}, status=status.HTTP_403_FORBIDDEN)

        term = Term.objects.filter(is_current=True).first()
        empty = {"percentage": None, "attended": 0, "held": 0, "term_name": term.name if term else None}
        if term is None or not profile.department_id:
            return Response({**empty, "minimum_required": None}, status=status.HTTP_200_OK)

        rate, attended, held = compute_attendance_rate(profile, term.start_date, term.end_date)
        detention = get_detention_settings()
        return Response({
            "percentage": round(rate, 1) if rate is not None else None,
            "attended": attended,
            "held": held,
            "term_name": term.name,
            "minimum_required": float(detention.minimum_attendance_percent) if detention.is_enabled else None,
        }, status=status.HTTP_200_OK)

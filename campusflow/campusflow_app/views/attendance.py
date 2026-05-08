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
from campusflow_app.serializers import AttendanceSerializer
from ..models.attendance import Attendance
from ..models.location import Location
from ..utils import calculate_distance
from ..models.classroom import Classroom
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404
from ..models.lecture import Lecture
from ..serializers import AttendanceMarkSerializer, LectureAttendanceCodeSerializer
from ..permissions import (
    CanMarkAttendanceManually, IsFacultyOrAbove,
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
    permission_classes = [IsAuthenticated, CanMarkAttendanceManually]

    def post(self, request):
        serializer = AttendanceMarkSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        student_id = serializer.validated_data['student_id']
        location_id = serializer.validated_data['location_id']
        latitude = serializer.validated_data['latitude']
        longitude = serializer.validated_data['longitude']
        lecture_id = serializer.validated_data.get('lecture_id', None)

        student = get_object_or_404(User, id=student_id)

        # Ensure the target is actually a student
        student_group = student.groups.first().name if student.groups.exists() else None
        if student_group != 'student':
            return Response(
                {"error": "The specified user is not a student."},
                status=status.HTTP_400_BAD_REQUEST
            )

        location = get_object_or_404(Location, location_id=location_id)

        if location.is_premises_entry:
            Attendance.objects.create(user=student, scanned_location=location, attendance_type='premises_entry', is_geofence_valid=True)
            return Response({'detail': 'Premises entry attendance marked.'}, status=status.HTTP_201_CREATED)
        elif location.is_classroom_entry:
            Attendance.objects.create(user=student, scanned_location=location, attendance_type='classroom_entry', is_geofence_valid=True)
            return Response({'detail': 'Classroom attendance marked.'}, status=status.HTTP_201_CREATED)
        elif lecture_id is not None:
            lecture = get_object_or_404(Lecture, id=lecture_id)
            Attendance.objects.create(user=student, scanned_location=location, attendance_type='lecture_attendance', lecture=lecture, is_geofence_valid=True)
            return Response({'detail': 'Lecture attendance marked.'}, status=status.HTTP_201_CREATED)

        return Response({'detail': 'Invalid attendance marking request.'}, status=status.HTTP_400_BAD_REQUEST)


class AllAttendanceView(APIView):
    """
    View ALL attendance records (for reporting/admin purposes).
    Only Faculty and above can access this — students cannot see other students' records.
    Supports optional filtering by user_id, date, and attendance_type.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request):
        qs = Attendance.objects.all().select_related('user', 'scanned_location')

        # Optional filters
        user_id = request.query_params.get('user_id')
        date = request.query_params.get('date')
        attendance_type = request.query_params.get('type')

        if user_id:
            qs = qs.filter(user__id=user_id)
        if date:
            qs = qs.filter(check_in_time__date=date)
        if attendance_type:
            qs = qs.filter(attendance_type=attendance_type)

        serializer = AttendanceSerializer(qs.order_by('-check_in_time'), many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class LectureCheckinByCodeView(APIView):
    """
    Students mark their attendance by entering the code provided by faculty.
    Validates the code and checks if the student is within the classroom's geofence.
    """
    permission_classes = [IsAuthenticated]

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
        if profile:
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

        # Get radius from classroom (fallback to 50m)
        radius = lecture.classroom.main_entry_location.geofence_radius_meters if (lecture.classroom.main_entry_location) else 50

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
            attendance_type='lecture_attendance'
        )

        return Response({"detail": "Attendance marked successfully!"}, status=status.HTTP_201_CREATED)

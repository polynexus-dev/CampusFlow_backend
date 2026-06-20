from django.utils import timezone
from datetime import timedelta
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.shortcuts import get_object_or_404
from django.contrib.auth.models import User

from ..models.lecture import Lecture
from ..models.attendance import Attendance
from ..models.attendance_session import AttendanceSession
from ..models.manual_attendance_request import ManualAttendanceRequest
from ..permissions import IsFacultyOrAbove

class IsFaculty(permissions.BasePermission):
    """
    Allow access to authenticated users who are teaching staff or faculty.
    """
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated and
            (hasattr(request.user, 'teaching_staff_profile') or request.user.is_superuser)
        )


class LecturerCheckInView(APIView):
    """
    POST /api/lecturer/check-in/
    Allows lecturer to check in. Sets the geofence coordinate center.
    """
    permission_classes = [permissions.IsAuthenticated, IsFaculty]

    def post(self, request):
        lecture_id = request.data.get("lecture_id")
        latitude = request.data.get("latitude")
        longitude = request.data.get("longitude")

        if not lecture_id or latitude is None or longitude is None:
            return Response(
                {"error": "lecture_id, latitude, and longitude are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        lecture = get_object_or_404(Lecture, id=lecture_id)

        # Ensure lecturer is assigned to this lecture
        if lecture.faculty != request.user and not request.user.is_superuser:
            return Response(
                {"error": "You are not assigned as the faculty for this lecture."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Bind coordinates to the lecture (dynamic classroom geofence center)
        lecture.latitude = latitude
        lecture.longitude = longitude
        lecture.save()

        # Record lecturer check-in
        Attendance.objects.get_or_create(
            user=request.user,
            lecture=lecture,
            defaults={
                "is_geofence_valid": True,
                "verification_method": "manual"
            }
        )

        return Response(
            {"message": "Check-in successful. Classroom coordinates set to your current location."},
            status=status.HTTP_200_OK
        )


class LecturerStartSessionView(APIView):
    """
    POST /api/lecturer/start-attendance/
    Starts a 3-minute student verify-in session.
    """
    permission_classes = [permissions.IsAuthenticated, IsFaculty]

    def post(self, request):
        lecture_id = request.data.get("lecture_id")
        
        if not lecture_id:
            return Response({"error": "lecture_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        lecture = get_object_or_404(Lecture, id=lecture_id)

        # Ensure lecturer is checked in first (which binds coordinates)
        if not lecture.latitude or not lecture.longitude:
            return Response(
                {"error": "You must check in to the classroom first to set coordinates."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Create/restart active attendance session (3 minutes)
        session, created = AttendanceSession.objects.update_or_create(
            lecture=lecture,
            defaults={
                "started_by": request.user,
                "started_at": timezone.now(),
                "duration_minutes": 3,
                "latitude": lecture.latitude,
                "longitude": lecture.longitude,
                "is_active": True
            }
        )

        return Response(
            {"message": "Attendance window started successfully for 3 minutes."},
            status=status.HTTP_201_CREATED
        )


class LecturerAttendanceStatusView(APIView):
    """
    GET /api/lecturer/status/?lecture_id=...
    Returns real-time session status, countdown, and student verify lists.
    """
    permission_classes = [permissions.IsAuthenticated, IsFaculty]

    def get(self, request):
        lecture_id = request.query_params.get("lecture_id")
        if not lecture_id:
            return Response({"error": "lecture_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        lecture = get_object_or_404(Lecture, id=lecture_id)

        # Checked in status
        is_checked_in = Attendance.objects.filter(user=request.user, lecture=lecture).exists()

        # Session active status & countdown
        session_active = False
        seconds_remaining = 0
        session = AttendanceSession.objects.filter(lecture=lecture).first()

        if session and session.is_active:
            elapsed = timezone.now() - session.started_at
            limit = timedelta(minutes=session.duration_minutes)
            if elapsed > limit:
                session.is_active = False
                session.save()
            else:
                session_active = True
                seconds_remaining = int((limit - elapsed).total_seconds())

        # List of students who marked attendance successfully
        verified_records = Attendance.objects.filter(lecture=lecture).exclude(user=lecture.faculty).select_related('user__student_profile')
        marked_students = []
        for record in verified_records:
            profile = getattr(record.user, 'student_profile', None)
            marked_students.append({
                "student_id": profile.student_id if profile else "N/A",
                "username": record.user.username,
                "full_name": record.user.get_full_name() or record.user.username,
                "timestamp": record.check_in_time
            })

        pending_requests_count = ManualAttendanceRequest.objects.filter(lecture=lecture, status='pending').count()

        return Response({
            "is_checked_in": is_checked_in,
            "session_active": session_active,
            "seconds_remaining": seconds_remaining,
            "marked_students_count": len(marked_students),
            "marked_students": marked_students,
            "pending_requests_count": pending_requests_count
        }, status=status.HTTP_200_OK)


class LecturerManualRequestsView(APIView):
    """
    GET /api/lecturer/manual-requests/?lecture_id=...
    Lists all pending manual requests for review.
    """
    permission_classes = [permissions.IsAuthenticated, IsFaculty]

    def get(self, request):
        lecture_id = request.query_params.get("lecture_id")
        if not lecture_id:
            return Response({"error": "lecture_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        lecture = get_object_or_404(Lecture, id=lecture_id)

        requests = ManualAttendanceRequest.objects.filter(lecture=lecture, status='pending').select_related('student__user')
        data = [{
            "id": r.id,
            "student_id": r.student.student_id,
            "username": r.student.user.username,
            "full_name": r.student.user.get_full_name() or r.student.user.username,
            "reason": r.reason,
            "requested_at": r.requested_at
        } for r in requests]

        return Response(data, status=status.HTTP_200_OK)


class LecturerApproveManualRequestView(APIView):
    """
    POST /api/lecturer/approve-manual-request/
    Approves or rejects a student's manual attendance request.
    """
    permission_classes = [permissions.IsAuthenticated, IsFaculty]

    def post(self, request):
        request_id = request.data.get("request_id")
        action = request.data.get("action")  # 'approve' or 'reject'

        if not request_id or action not in ['approve', 'reject']:
            return Response(
                {"error": "request_id and action ('approve' or 'reject') are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        req = get_object_or_404(ManualAttendanceRequest, id=request_id)

        if action == 'approve':
            req.status = 'approved'
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save()

            # Record standard attendance check-in record for student
            Attendance.objects.get_or_create(
                user=req.student.user,
                lecture=req.lecture,
                defaults={
                    "is_geofence_valid": True,
                    "verification_method": "manual",
                    "device_id": "Lecturer Approved"
                }
            )
            return Response({"message": "Request approved. Student attendance marked."}, status=status.HTTP_200_OK)
        else:
            req.status = 'rejected'
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save()
            return Response({"message": "Request rejected."}, status=status.HTTP_200_OK)


class LecturerConductedHistoryView(APIView):
    """
    GET /api/lecturer/conducted-history/
    Retrieves history of lectures conducted by the logged-in lecturer.
    Allows filtering by year, month, and day query parameters.
    """
    permission_classes = [permissions.IsAuthenticated, IsFaculty]

    def get(self, request):
        user = request.user
        year = request.query_params.get("year")
        month = request.query_params.get("month")
        day = request.query_params.get("day")

        # Query all check-in records for this lecturer
        # The lecturer's check-ins are Attendance records where user=user and lecture.faculty=user
        attendances = Attendance.objects.filter(
            user=user,
            lecture__faculty=user
        ).select_related('lecture', 'lecture__classroom')

        # Apply year/month/day filters if provided
        if year:
            try:
                attendances = attendances.filter(check_in_time__year=int(year))
            except ValueError:
                pass
        if month:
            try:
                attendances = attendances.filter(check_in_time__month=int(month))
            except ValueError:
                pass
        if day:
            try:
                attendances = attendances.filter(check_in_time__day=int(day))
            except ValueError:
                pass

        # Sort from most recent to oldest
        attendances = attendances.order_by('-check_in_time')

        # Format and serialize the response
        lectures_data = []
        for record in attendances:
            lec = record.lecture
            # Count how many students checked in/marked attendance for this lecture (excluding the lecturer)
            student_count = Attendance.objects.filter(lecture=lec).exclude(user=user).count()

            lectures_data.append({
                "id": lec.id,
                "name": lec.name,
                "subject": lec.subject,
                "classroom_name": lec.classroom.name if lec.classroom else "N/A",
                "start_time": lec.start_time,
                "end_time": lec.end_time,
                "lecturer_check_in": record.check_in_time,
                "student_count": student_count
            })

        # Calculate summary counts
        total_conducted = Attendance.objects.filter(user=user, lecture__faculty=user).count()

        return Response({
            "total_count": total_conducted,
            "filtered_count": len(lectures_data),
            "lectures": lectures_data
        }, status=status.HTTP_200_OK)


class LecturerBulkApproveManualRequestsView(APIView):
    """
    POST /api/lecturer/bulk-approve-manual-requests/
    Allows lecturer to bulk approve/reject multiple student manual requests.
    """
    permission_classes = [permissions.IsAuthenticated, IsFacultyOrAbove]

    def post(self, request):
        request_ids = request.data.get("request_ids", [])
        action = request.data.get("action")  # 'approve' or 'reject'

        if not isinstance(request_ids, list) or action not in ['approve', 'reject']:
            return Response(
                {"error": "request_ids (list of IDs) and action ('approve' or 'reject') are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        requests = ManualAttendanceRequest.objects.filter(id__in=request_ids, status='pending')
        updated_count = 0

        for req in requests:
            if action == 'approve':
                req.status = 'approved'
                req.reviewed_by = request.user
                req.reviewed_at = timezone.now()
                req.save()

                # Record standard attendance check-in record for student
                Attendance.objects.get_or_create(
                    user=req.student.user,
                    lecture=req.lecture,
                    defaults={
                        "is_geofence_valid": True,
                        "verification_method": "manual",
                        "device_id": "Lecturer Approved (Bulk)"
                    }
                )
            else:
                req.status = 'rejected'
                req.reviewed_by = request.user
                req.reviewed_at = timezone.now()
                req.save()
            updated_count += 1

        return Response(
            {"message": f"Successfully processed {updated_count} manual requests."},
            status=status.HTTP_200_OK
        )


class LecturerDeviceResetRequestsView(APIView):
    """
    GET /api/lecturer/device-resets/
    Lists all pending biometric/device reset requests.
    """
    permission_classes = [permissions.IsAuthenticated, IsFacultyOrAbove]

    def get(self, request):
        from ..models.device_reset import DeviceResetRequest
        
        # Get the lecturer's department if available
        user_profile = getattr(request.user, 'teaching_staff_profile', None) or getattr(request.user, 'department_head_profile', None)
        user_dept = user_profile.department if user_profile else None
        
        requests = DeviceResetRequest.objects.filter(status='pending').select_related('student__user')
        
        if user_dept:
            requests = requests.filter(student__department=user_dept)
            
        data = [{
            "id": r.id,
            "student_id": r.student.student_id,
            "username": r.student.user.username,
            "full_name": r.student.user.get_full_name() or r.student.user.username,
            "reason": r.reason,
            "requested_at": r.requested_at
        } for r in requests]

        return Response(data, status=status.HTTP_200_OK)


class LecturerApproveDeviceResetRequestView(APIView):
    """
    POST /api/lecturer/approve-device-reset/
    Approves or rejects a student's device reset request.
    """
    permission_classes = [permissions.IsAuthenticated, IsFacultyOrAbove]

    def post(self, request):
        from ..models.device_reset import DeviceResetRequest

        request_id = request.data.get("request_id")
        action = request.data.get("action")  # 'approve' or 'reject'

        if not request_id or action not in ['approve', 'reject']:
            return Response(
                {"error": "request_id and action ('approve' or 'reject') are required."},
                status=status.HTTP_400_BAD_REQUEST
            )

        req = get_object_or_404(DeviceResetRequest, id=request_id)

        if action == 'approve':
            req.status = 'approved'
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save()

            # Reset student's device lock and face registration status
            student = req.student
            student.locked_device_id = None
            student.is_face_registered = False
            student.save()

            return Response({"message": "Device reset approved successfully. Student can now re-register."}, status=status.HTTP_200_OK)
        else:
            req.status = 'rejected'
            req.reviewed_by = request.user
            req.reviewed_at = timezone.now()
            req.save()
            return Response({"message": "Device reset rejected."}, status=status.HTTP_200_OK)


class LecturerGenerateDynamicQRView(APIView):
    """
    GET /api/lecturer/generate-dynamic-qr/?lecture_id=...
    Generates a dynamic 15-second rotating QR code for the given lecture.
    Returns base64 PNG data URL.
    """
    permission_classes = [permissions.IsAuthenticated, IsFacultyOrAbove]

    def get(self, request):
        import hashlib
        import time
        import qrcode
        import base64
        import json
        from io import BytesIO
        from django.conf import settings

        lecture_id = request.query_params.get("lecture_id")
        if not lecture_id:
            return Response({"error": "lecture_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        lecture = get_object_or_404(Lecture, id=lecture_id)

        # Check if the session is currently active
        session = AttendanceSession.objects.filter(lecture=lecture, is_active=True).first()
        if not session:
            return Response({"error": "No active attendance session found for this lecture. Start verification first."}, status=status.HTTP_400_BAD_REQUEST)

        # Compute dynamic 15-second rotating code
        now_ts = time.time()
        interval = int(now_ts) // 15
        expires_in = 15 - (int(now_ts) % 15)

        # Cryptographic sign
        data_str = f"{lecture_id}-{interval}-{settings.SECRET_KEY}"
        token = hashlib.sha256(data_str.encode('utf-8')).hexdigest()[:16]

        # Render QR code image containing JSON payload
        qr_payload = {
            "lecture_id": int(lecture_id),
            "token": token
        }
        
        qr = qrcode.QRCode(box_size=8, border=1)
        qr.add_data(json.dumps(qr_payload))
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")

        buffered = BytesIO()
        img.save(buffered, format="PNG")
        qr_base64 = base64.b64encode(buffered.getvalue()).decode('utf-8')
        qr_image_data = f"data:image/png;base64,{qr_base64}"

        return Response({
            "qr_image": qr_image_data,
            "expires_in": expires_in
        }, status=status.HTTP_200_OK)


class StudentVerifyQRAttendanceView(APIView):
    """
    POST /api/student/verify-qr-attendance/
    Allows a student to scan the lecturer's rotating QR code to verify proximity.
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        import hashlib
        import time
        from django.conf import settings

        lecture_id = request.data.get("lecture_id")
        token = request.data.get("token")

        if not lecture_id or not token:
            return Response({"error": "lecture_id and token are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Verify the student has a student profile
        if not hasattr(request.user, 'student_profile'):
            return Response({"error": "Only students can mark attendance."}, status=status.HTTP_400_BAD_REQUEST)

        student_profile = request.user.student_profile
        lecture = get_object_or_404(Lecture, id=lecture_id)

        # Validate token against current and previous 15-second buckets
        now_ts = time.time()
        current_interval = int(now_ts) // 15
        is_token_valid = False

        for offset in [0, -1, 1]:  # check current, previous, and next (for minor clock drifts)
            interval = current_interval + offset
            data_str = f"{lecture_id}-{interval}-{settings.SECRET_KEY}"
            expected = hashlib.sha256(data_str.encode('utf-8')).hexdigest()[:16]
            if token == expected:
                is_token_valid = True
                break

        if not is_token_valid:
            return Response({"error": "The scanned QR code has expired or is invalid. Please scan the active QR code again."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if attendance was already marked
        existing = Attendance.objects.filter(user=request.user, lecture=lecture).exists()
        if existing:
            return Response({"message": "Attendance already marked for this lecture."}, status=status.HTTP_200_OK)

        # Mark attendance successfully under 'qr_fallback' verification method
        Attendance.objects.create(
            user=request.user,
            lecture=lecture,
            is_geofence_valid=True,
            verification_method='qr_fallback',
            device_id=request.data.get("device_id", "QR Scanned Fallback")
        )

        return Response({"message": "Attendance marked successfully via QR code scanner!"}, status=status.HTTP_200_OK)


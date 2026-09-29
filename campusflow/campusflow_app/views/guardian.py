import datetime
from django.db import connection
from django.db.models import Q
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from django.core.cache import cache

from ..throttling import AuthScopedRateThrottle

from ..models.profile import GuardianProfile, StudentProfile
from ..models.attendance import Attendance
from ..models.leave import LeaveRequest
from ..models.fees import StudentFeeInvoice
from ..models.exam import Exam, ExamType
from ..models.result import StudentExamResult
from ..models.assignment import Assignment
from ..models.submission import AssignmentSubmission
from ..models.bus_tracking import BusSubscription, BusLocation, BusRoute
from ..models.announcement import Announcement
from django.contrib.auth.models import User
from ..models.lecture import Lecture
from ..services.detention import compute_attendance_rate

# Linking by DOB/admission number is a guessable secret, so failed attempts are
# capped per guardian (on top of the per-IP 'parent_link' throttle).
LINK_MAX_FAILURES_PER_DAY = 5
LINK_FAILED_MESSAGE = "We couldn't verify that student. Check the student ID and date of birth or admission number."
# A BusLocation older than this isn't "live".
BUS_LIVE_WINDOW = datetime.timedelta(minutes=15)


def _class_display(student):
    parts = [p for p in (student.current_semester_year, student.section_division) if p]
    return "-".join(parts) or None


class ParentLinkChildView(APIView):
    """
    POST: Link a student profile to the authenticated parent/guardian user.
    Required fields: student_id, verification_key (can be date_of_birth or admission_number).
    """
    permission_classes = [IsAuthenticated]
    throttle_classes = [AuthScopedRateThrottle]
    throttle_scope = 'parent_link'

    def post(self, request):
        user = request.user
        guardian_profile = getattr(user, 'guardian_profile', None)
        if not guardian_profile:
            return Response({"error": "Only authenticated guardians can link children."}, status=status.HTTP_403_FORBIDDEN)

        student_id = request.data.get('student_id')
        verification_key = request.data.get('verification_key')  # DOB (YYYY-MM-DD) or admission_number

        if not student_id or not verification_key:
            return Response({"error": "student_id and verification_key (DOB or Admission Number) are required."}, status=status.HTTP_400_BAD_REQUEST)

        failures_key = f"parent_link_failures:{connection.schema_name}:{user.id}"
        failures = cache.get(failures_key) or 0
        if failures >= LINK_MAX_FAILURES_PER_DAY:
            return Response(
                {"error": "Too many failed attempts. Try again tomorrow or contact the college office."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
            )

        # Lookup student — "not found" and "wrong key" get the same reply so
        # this can't be used to probe which student IDs exist.
        student = StudentProfile.objects.filter(student_id=student_id).first()
        dob_match = False
        if student and student.date_of_birth:
            if isinstance(student.date_of_birth, datetime.date):
                dob_match = student.date_of_birth.strftime('%Y-%m-%d') == verification_key
            else:
                dob_match = str(student.date_of_birth) == verification_key

        admission_match = bool(student and student.admission_number and student.admission_number == verification_key)

        if not (dob_match or admission_match):
            cache.set(failures_key, failures + 1, timeout=24 * 3600)
            return Response({"error": LINK_FAILED_MESSAGE}, status=status.HTTP_400_BAD_REQUEST)
        cache.delete(failures_key)

        # Check if already linked
        if guardian_profile.students.filter(id=student.id).exists():
            return Response({"message": f"Student {student.user.get_full_name()} is already linked to your profile."}, status=status.HTTP_200_OK)

        # Link child
        guardian_profile.students.add(student)
        return Response({
            "message": f"Successfully linked {student.user.get_full_name() or student.student_id} to your account.",
            "child": {
                "id": student.id,
                "name": student.user.get_full_name(),
                "student_id": student.student_id,
                "class": _class_display(student),
            }
        }, status=status.HTTP_200_OK)


class ParentChildrenListView(APIView):
    """
    GET: List all children linked to this parent/guardian.
    Returns today's attendance, live bus ETA, fee banner, and announcement count for each child.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        guardian_profile = getattr(user, 'guardian_profile', None)
        if not guardian_profile:
            return Response({"error": "Only authenticated guardians can view linked children."}, status=status.HTTP_403_FORBIDDEN)

        today = datetime.date.today()
        children = guardian_profile.students.all()
        result = []

        for child in children:
            # 1. Today's Attendance status
            attendance_status = "Absent"
            att_record = Attendance.objects.filter(user=child.user, check_in_time__date=today).first()
            if att_record:
                attendance_status = "Present"
            else:
                # Check for approved leaves
                leave = LeaveRequest.objects.filter(
                    user=child.user,
                    start_date__lte=today,
                    end_date__gte=today,
                    status='approved'
                ).first()
                if leave:
                    attendance_status = "Leave"

            # 2. Live Bus tracking status
            bus_status = None
            bus_sub = BusSubscription.objects.filter(user=child.user, status='active').first()
            if bus_sub:
                # Live = a GPS update from the route's bus in the last few
                # minutes. (This used to return a hardcoded "ETA 7:48 AM".)
                is_live = BusLocation.objects.filter(
                    route=bus_sub.route, updated_at__gte=timezone.now() - BUS_LIVE_WINDOW,
                ).exists()
                bus_status = {
                    "route_name": bus_sub.route.name,
                    "boarding_stop": bus_sub.boarding_stop,
                    "is_live": is_live,
                    "status_message": "Bus is running" if is_live else "Bus route not started yet",
                    "eta": None,
                }

            # 3. Fee summary banner
            unpaid_invoices = StudentFeeInvoice.objects.filter(student=child.user, status__in=['unpaid', 'partially_paid'])
            total_due = sum(inv.remaining_balance for inv in unpaid_invoices)
            fee_due_banner = {
                "has_dues": total_due > 0,
                "amount_due": float(total_due),
                "due_date": unpaid_invoices.first().due_date.strftime('%Y-%m-%d') if unpaid_invoices.exists() else None,
                "message": f"Term fee due: ₹{total_due:,.2f}" if total_due > 0 else "No outstanding dues"
            }

            # 4. Unread announcement count
            # Find announcements targeted to student role or child's department
            dept_id = child.department_id if child.department else None
            announcements = Announcement.objects.filter(
                Q(target_roles__contains='student') | Q(target_roles=[])
            )
            if dept_id:
                announcements = announcements.filter(
                    Q(target_departments__id=dept_id) | Q(target_departments=None)
                )
            
            # Count recent announcements within last 7 days
            seven_days_ago = timezone.now() - datetime.timedelta(days=7) if hasattr(child, 'user') else datetime.datetime.now() - datetime.timedelta(days=7)
            announcements_count = announcements.filter(created_at__gte=seven_days_ago).count()

            # Child profile picture URL
            profile_pic = None
            if child.profile_picture:
                profile_pic = request.build_absolute_uri(child.profile_picture.url)

            result.append({
                "id": child.id,
                "name": child.user.get_full_name(),
                "student_id": child.student_id,
                "class_grade": child.current_semester_year or None,
                "section": child.section_division or None,
                "class_display": _class_display(child),
                "profile_picture": profile_pic,
                "attendance_status": attendance_status,
                "bus_tracking": bus_status,
                "fee_due_banner": fee_due_banner,
                "unread_announcements_count": announcements_count
            })

        return Response({"children": result}, status=status.HTTP_200_OK)


class ParentChildAttendanceView(APIView):
    """
    GET: Get monthly calendar logs and percentage ring for selected child.
    Path Parameter: student_id (StudentProfile PK).
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        user = request.user
        guardian_profile = getattr(user, 'guardian_profile', None)
        if not guardian_profile or not guardian_profile.students.filter(id=student_id).exists():
            return Response({"error": "Access denied or student not linked to this guardian."}, status=status.HTTP_403_FORBIDDEN)

        student = StudentProfile.objects.get(id=student_id)
        
        # Last 30 days, judged against lectures actually held for the child's
        # department (same basis as the detention rule), not a fixed 22-day
        # school month. A day with no lectures is a "Holiday".
        today = datetime.date.today()
        start = today - datetime.timedelta(days=29)
        attended_dates = set(
            Attendance.objects.filter(
                user=student.user, check_in_time__date__gte=start,
            ).values_list("check_in_time__date", flat=True)
        )
        lecture_dates = set()
        if student.department_id:
            lecture_dates = set(
                Lecture.objects.filter(
                    faculty__teaching_staff_profile__department_id=student.department_id,
                    start_time__date__gte=start, start_time__date__lte=today,
                ).exclude(code__isnull=True).exclude(code="").values_list("start_time__date", flat=True)
            )

        days = []
        present_count = 0
        for i in range(30):
            day_date = today - datetime.timedelta(days=i)
            if day_date in attended_dates:
                status_str = "Present"
                present_count += 1
            elif day_date not in lecture_dates:
                status_str = "Holiday"
            else:
                # Check leaves
                leave = LeaveRequest.objects.filter(
                    user=student.user,
                    start_date__lte=day_date,
                    end_date__gte=day_date,
                    status='approved'
                ).first()
                status_str = "Leave" if leave else "Absent"

            days.append({
                "date": day_date.strftime('%Y-%m-%d'),
                "day_name": day_date.strftime('%A'),
                "status": status_str
            })

        rate, _, held = (None, 0, 0)
        if student.department_id:
            rate, _, held = compute_attendance_rate(student, start, today)

        return Response({
            # Lecture-level %, None when no lectures were held in the window.
            "percentage": round(rate, 1) if rate is not None else None,
            "present_days": present_count,
            "total_days_evaluated": len(lecture_dates),
            "lectures_held": held,
            "calendar": days
        }, status=status.HTTP_200_OK)


class ParentChildFeesView(APIView):
    """
    GET: Get child's fee invoices, transaction details and receipt downloads.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        user = request.user
        guardian_profile = getattr(user, 'guardian_profile', None)
        if not guardian_profile or not guardian_profile.students.filter(id=student_id).exists():
            return Response({"error": "Access denied or student not linked to this guardian."}, status=status.HTTP_403_FORBIDDEN)

        student = StudentProfile.objects.get(id=student_id)
        invoices = StudentFeeInvoice.objects.filter(student=student.user)

        invoice_list = []
        for inv in invoices:
            invoice_list.append({
                "id": inv.id,
                "invoice_number": inv.invoice_number,
                "due_date": inv.due_date.strftime('%Y-%m-%d'),
                "total_amount": float(inv.total_amount),
                "discount_amount": float(inv.discount_amount),
                "paid_amount": float(inv.paid_amount),
                "remaining_balance": float(inv.remaining_balance),
                "status": inv.status,
                "items": [{
                    "category": item.category.name,
                    "amount": float(item.amount)
                } for item in inv.items.all()],
                "payments": [{
                    "receipt_number": payment.receipt_number,
                    "amount_paid": float(payment.amount_paid),
                    "payment_method": payment.get_payment_method_display(),
                    "payment_date": payment.payment_date.strftime('%Y-%m-%d %H:%M')
                } for payment in inv.payments.all()]
            })

        return Response({
            "invoices": invoice_list
        }, status=status.HTTP_200_OK)


class ParentChildExamsView(APIView):
    """
    GET: Get child's upcoming exam schedule & published term report cards.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        user = request.user
        guardian_profile = getattr(user, 'guardian_profile', None)
        if not guardian_profile or not guardian_profile.students.filter(id=student_id).exists():
            return Response({"error": "Access denied or student not linked to this guardian."}, status=status.HTTP_403_FORBIDDEN)

        student = StudentProfile.objects.get(id=student_id)
        
        # 1. Upcoming exams
        today = datetime.date.today()
        # Find exams matching student's department/grade
        dept_id = student.department_id if student.department else None
        exams = Exam.objects.filter(date__gte=today)
        if dept_id:
            exams = exams.filter(department_id=dept_id)

        schedule = []
        for exam in exams:
            schedule.append({
                "id": exam.id,
                "subject_name": exam.course.course_name,
                "subject_code": exam.course.course_code,
                "exam_type": exam.exam_type.name,
                "date": exam.date.strftime('%Y-%m-%d'),
                "time": f"{exam.start_time.strftime('%I:%M %p')} - {exam.end_time.strftime('%I:%M %p')}",
                "classroom": exam.classroom.room_number if exam.classroom else "Main Hall",
                "instructions": exam.instructions
            })

        # 2. Report Cards / Academic Results (grouped by Semester/Term)
        # Only published results are visible to parents — drafts stay internal
        # until the teacher publishes them (see ExamPublishResultsView).
        results = StudentExamResult.objects.filter(student=student, exam__results_published=True)
        
        term_results = {}
        for res in results:
            term = res.exam.semester or "Term 1" # map college Semester to school Term label
            if term not in term_results:
                term_results[term] = []
            
            term_results[term].append({
                "subject_name": res.exam.course.course_name,
                "subject_code": res.exam.course.course_code,
                "marks_obtained": float(res.marks_obtained),
                "total_marks": res.exam.total_marks,
                "grade": res.grade or "A",
                "is_pass": res.is_pass,
                "remarks": res.remarks
            })

        report_cards = []
        for term, sub_list in term_results.items():
            total_obtained = sum(s["marks_obtained"] for s in sub_list)
            total_max = sum(s["total_marks"] for s in sub_list)
            percentage = round((total_obtained / total_max) * 100, 1) if total_max > 0 else 0.0
            
            report_cards.append({
                "term_name": term,
                "total_obtained": total_obtained,
                "total_max": total_max,
                "percentage": percentage,
                "subjects": sub_list
            })

        return Response({
            "exam_schedule": schedule,
            "report_cards": report_cards
        }, status=status.HTTP_200_OK)


class ParentChildAssignmentsView(APIView):
    """
    GET: Get homework/assignments with submission statuses for the selected child.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, student_id):
        user = request.user
        guardian_profile = getattr(user, 'guardian_profile', None)
        if not guardian_profile or not guardian_profile.students.filter(id=student_id).exists():
            return Response({"error": "Access denied or student not linked to this guardian."}, status=status.HTTP_403_FORBIDDEN)

        student = StudentProfile.objects.get(id=student_id)
        
        # Get assignments matching student's department/grade
        dept_id = student.department_id if student.department else None
        assignments = Assignment.objects.all()
        if dept_id:
            assignments = assignments.filter(department_id=dept_id)

        # Get submissions of this student
        submissions = AssignmentSubmission.objects.filter(student=student.user)
        sub_map = {sub.assignment_id: sub for sub in submissions}

        assignment_list = []
        for ass in assignments:
            sub = sub_map.get(ass.id)
            submission_status = "Pending"
            grade = None
            feedback = None
            submitted_at = None

            if sub:
                submission_status = "Submitted" if sub.status == 'submitted' else "Graded"
                grade = sub.grade
                feedback = sub.feedback
                submitted_at = sub.submitted_at.strftime('%Y-%m-%d %H:%M')

            assignment_list.append({
                "id": ass.id,
                "title": ass.title,
                "description": ass.description,
                "subject": ass.course.course_name,
                "due_date": ass.due_date.strftime('%Y-%m-%d %H:%M'),
                "teacher_name": ass.created_by.get_full_name(),
                "submission_status": submission_status,
                "graded_marks": grade,
                "feedback": feedback,
                "submitted_at": submitted_at
            })

        return Response({
            "assignments": assignment_list
        }, status=status.HTTP_200_OK)

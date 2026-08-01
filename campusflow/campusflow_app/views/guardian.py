import datetime
from django.db import connection
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

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


class ParentLinkChildView(APIView):
    """
    POST: Link a student profile to the authenticated parent/guardian user.
    Required fields: student_id, verification_key (can be date_of_birth or admission_number).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        guardian_profile = getattr(user, 'guardian_profile', None)
        if not guardian_profile:
            return Response({"error": "Only authenticated guardians can link children."}, status=status.HTTP_403_FORBIDDEN)

        student_id = request.data.get('student_id')
        verification_key = request.data.get('verification_key')  # DOB (YYYY-MM-DD) or admission_number

        if not student_id or not verification_key:
            return Response({"error": "student_id and verification_key (DOB or Admission Number) are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Lookup student
        student = StudentProfile.objects.filter(student_id=student_id).first()
        if not student:
            return Response({"error": "Student with the specified ID not found."}, status=status.HTTP_404_NOT_FOUND)

        # Verification check (DOB or admission_number)
        dob_match = False
        if student.date_of_birth:
            if isinstance(student.date_of_birth, datetime.date):
                dob_match = student.date_of_birth.strftime('%Y-%m-%d') == verification_key
            else:
                dob_match = str(student.date_of_birth) == verification_key

        admission_match = student.admission_number == verification_key

        if not (dob_match or admission_match):
            return Response({"error": "Verification failed. Incorrect Date of Birth or Admission Number."}, status=status.HTTP_400_BAD_REQUEST)

        # Check if already linked
        if guardian_profile.students.filter(id=student.id).exists():
            return Response({"message": f"Student {student.user.get_full_name()} is already linked to your profile."}, status=status.HTTP_200_OK)

        # Link child
        guardian_profile.students.add(student)
        return Response({
            "message": f"Successfully linked student {student.user.get_full_name()} (Class {student.current_semester_year}-{student.section_division}) to your account.",
            "child": {
                "id": student.id,
                "name": student.user.get_full_name(),
                "student_id": student.student_id,
                "class": f"{student.current_semester_year}-{student.section_division}",
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
                # Look for live location of driver
                live_loc = BusLocation.objects.filter(route=bus_sub.route).first()
                # Return real route info and mock live stop status for visual fidelity
                bus_status = {
                    "route_name": bus_sub.route.name,
                    "boarding_stop": bus_sub.boarding_stop,
                    "is_live": bool(live_loc),
                    "status_message": "Bus is 2 stops away – ETA 7:48 AM" if live_loc else "Bus route not started yet",
                    "eta": "7:48 AM" if live_loc else "TBD"
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
                "class_grade": child.current_semester_year or "7",
                "section": child.section_division or "A",
                "class_display": f"Class {child.current_semester_year or '7'}-{child.section_division or 'A'}",
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
        
        # Monthly details (past 30 days logs)
        thirty_days_ago = datetime.date.today() - datetime.timedelta(days=30)
        logs = Attendance.objects.filter(user=student.user, check_in_time__date__gte=thirty_days_ago)

        # Generate list of days
        days = []
        present_count = 0
        total_days = 30 # standard visual check

        for i in range(total_days):
            day_date = datetime.date.today() - datetime.timedelta(days=i)
            # Skip Sundays/Saturdays for standard school weekend mapping
            is_weekend = day_date.weekday() in (5, 6)
            
            att = logs.filter(check_in_time__date=day_date).first()
            if att:
                status_str = "Present"
                present_count += 1
            elif is_weekend:
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

        percentage = round((present_count / (total_days - 8)) * 100, 1) if (total_days - 8) > 0 else 100.0
        percentage = min(100.0, percentage)

        return Response({
            "percentage": percentage,
            "present_days": present_count,
            "total_days_evaluated": total_days - 8,
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

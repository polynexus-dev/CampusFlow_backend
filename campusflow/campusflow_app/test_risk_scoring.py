"""
Tests for the dropout/at-risk prediction feature: the four rule-based
signal functions in services/risk_scoring.py, compute_risk_score's
weighted/graceful-degradation composite, the recompute_risk_scores
management command, and the AtRiskStudentsView API endpoint.
"""

import datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models.academics import AcademicYear, Term
from .models.assignment import Assignment
from .models.attendance import Attendance
from .models.classroom import Classroom
from .models.course import Course
from .models.department import Department
from .models.exam import Exam, ExamType
from .models.fees import StudentFeeInvoice
from .models.grading import TermGradeSheet
from .models.lecture import Lecture
from .models.profile import StudentProfile, TeachingStaffProfile
from .models.result import StudentExamResult
from .models.risk_score import StudentRiskScore
from .models.submission import AssignmentSubmission
from .services import risk_scoring


class _RiskFixtureMixin:
    def _department(self, code="RISK"):
        return Department.objects.create(name=f"Dept {code}", code=code)

    def _teaching_user(self, department, suffix="fac"):
        user = User.objects.create_user(username=f"faculty_{suffix}", email=f"faculty_{suffix}@test.com")
        TeachingStaffProfile.objects.create(user=user, employee_id=f"EMP_{suffix}", department=department)
        return user

    def _student(self, department, suffix="stu", academic_status="active"):
        user = User.objects.create_user(username=f"student_{suffix}", email=f"student_{suffix}@test.com")
        return StudentProfile.objects.create(
            user=user, student_id=f"STU_{suffix}", department=department, academic_status=academic_status,
        )

    def _lecture(self, faculty_user, suffix, days_ago=5, code_suffix=""):
        classroom = Classroom.objects.create(name=f"Room {suffix}", code=f"R{suffix}{code_suffix}")
        start = timezone.now() - datetime.timedelta(days=days_ago)
        return Lecture.objects.create(
            name=f"Lecture {suffix}", subject="Test Subject", faculty=faculty_user, classroom=classroom,
            start_time=start, end_time=start + datetime.timedelta(hours=1), code=f"LEC-{suffix}",
        )


class RiskScoringSignalTests(_RiskFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.department = self._department()
            self.faculty_user = self._teaching_user(self.department)
            self.student = self._student(self.department)

    def test_attendance_signal_none_when_no_lectures_in_window(self):
        with schema_context(self.tenant.schema_name):
            self.assertIsNone(risk_scoring._attendance_signal(self.student))

    def test_attendance_signal_computes_rate_and_concern(self):
        with schema_context(self.tenant.schema_name):
            attended = [self._lecture(self.faculty_user, f"a{i}") for i in range(5)]
            missed = [self._lecture(self.faculty_user, f"m{i}") for i in range(5)]
            for lecture in attended:
                Attendance.objects.create(user=self.student.user, lecture=lecture)

            concern, rate = risk_scoring._attendance_signal(self.student)
            self.assertAlmostEqual(rate, 50.0)
            self.assertAlmostEqual(concern, 50.0)

    def test_attendance_signal_half_day_gets_half_credit(self):
        with schema_context(self.tenant.schema_name):
            lectures = [self._lecture(self.faculty_user, f"h{i}") for i in range(4)]
            Attendance.objects.create(user=self.student.user, lecture=lectures[0], is_half_day=True)
            Attendance.objects.create(user=self.student.user, lecture=lectures[1])

            concern, rate = risk_scoring._attendance_signal(self.student)
            # 1.5 credit / 4 expected = 37.5%
            self.assertAlmostEqual(rate, 37.5)

    def test_fee_signal_zero_when_nothing_overdue(self):
        with schema_context(self.tenant.schema_name):
            concern, amount, count = risk_scoring._fee_signal(self.student)
            self.assertEqual(concern, 0.0)
            self.assertEqual(amount, 0)
            self.assertEqual(count, 0)

    def test_fee_signal_scales_with_days_overdue(self):
        with schema_context(self.tenant.schema_name):
            today = timezone.now().date()
            StudentFeeInvoice.objects.create(
                student=self.student.user, due_date=today - datetime.timedelta(days=10),
                total_amount=Decimal("5000"), status=StudentFeeInvoice.STATUS_UNPAID,
            )
            concern, amount, count = risk_scoring._fee_signal(self.student)
            self.assertEqual(concern, 40.0)
            self.assertEqual(amount, Decimal("5000"))
            self.assertEqual(count, 1)

    def test_fee_signal_two_overdue_invoices_is_max_concern(self):
        with schema_context(self.tenant.schema_name):
            today = timezone.now().date()
            for i in range(2):
                StudentFeeInvoice.objects.create(
                    student=self.student.user, due_date=today - datetime.timedelta(days=5),
                    total_amount=Decimal("1000"), status=StudentFeeInvoice.STATUS_UNPAID,
                )
            concern, amount, count = risk_scoring._fee_signal(self.student)
            self.assertEqual(concern, 100.0)
            self.assertEqual(count, 2)

    def test_assignment_signal_none_when_nothing_assigned(self):
        with schema_context(self.tenant.schema_name):
            self.assertIsNone(risk_scoring._assignment_signal(self.student))

    def test_assignment_signal_computes_submission_rate(self):
        with schema_context(self.tenant.schema_name):
            course = Course.objects.create(course_code="CS1", course_name="CS 1", department=self.department)
            now = timezone.now()
            assignments = [
                Assignment.objects.create(
                    title=f"A{i}", description="desc", department=self.department, course=course,
                    due_date=now - datetime.timedelta(days=i), created_by=self.faculty_user,
                )
                for i in range(4)
            ]
            for assignment in assignments[:1]:
                AssignmentSubmission.objects.create(assignment=assignment, student=self.student.user)

            concern, rate = risk_scoring._assignment_signal(self.student)
            self.assertAlmostEqual(rate, 25.0)
            self.assertAlmostEqual(concern, 75.0)

    def test_exam_trend_signal_none_with_insufficient_history(self):
        with schema_context(self.tenant.schema_name):
            self.assertIsNone(risk_scoring._exam_trend_signal(self.student))

    def test_exam_trend_signal_uses_gradesheet_sgpa_drop(self):
        with schema_context(self.tenant.schema_name):
            year = AcademicYear.objects.create(
                name="2024-2025", start_date=datetime.date(2024, 7, 1), end_date=datetime.date(2025, 6, 30),
            )
            term1 = Term.objects.create(
                academic_year=year, name="Sem 1", sequence=1,
                start_date=datetime.date(2024, 7, 1), end_date=datetime.date(2024, 12, 1),
            )
            term2 = Term.objects.create(
                academic_year=year, name="Sem 2", sequence=2,
                start_date=datetime.date(2025, 1, 1), end_date=datetime.date(2025, 6, 1),
            )
            TermGradeSheet.objects.create(
                student=self.student, term=term1, semester_number=1,
                sgpa=Decimal("8.00"), is_published=True,
            )
            TermGradeSheet.objects.create(
                student=self.student, term=term2, semester_number=2,
                sgpa=Decimal("6.00"), is_published=True,
            )

            concern, display_score = risk_scoring._exam_trend_signal(self.student)
            self.assertAlmostEqual(concern, (2.0 / risk_scoring.SGPA_DROP_MAX_CONCERN) * 100)
            self.assertAlmostEqual(display_score, 6.0)

    def test_exam_trend_signal_zero_concern_when_improving(self):
        with schema_context(self.tenant.schema_name):
            year = AcademicYear.objects.create(
                name="2023-2024", start_date=datetime.date(2023, 7, 1), end_date=datetime.date(2024, 6, 30),
            )
            term1 = Term.objects.create(
                academic_year=year, name="Sem 1", sequence=1,
                start_date=datetime.date(2023, 7, 1), end_date=datetime.date(2023, 12, 1),
            )
            term2 = Term.objects.create(
                academic_year=year, name="Sem 2", sequence=2,
                start_date=datetime.date(2024, 1, 1), end_date=datetime.date(2024, 6, 1),
            )
            TermGradeSheet.objects.create(
                student=self.student, term=term1, semester_number=1,
                sgpa=Decimal("6.00"), is_published=True,
            )
            TermGradeSheet.objects.create(
                student=self.student, term=term2, semester_number=2,
                sgpa=Decimal("8.00"), is_published=True,
            )
            concern, display_score = risk_scoring._exam_trend_signal(self.student)
            self.assertEqual(concern, 0.0)

    def test_compute_risk_score_graceful_degradation_excludes_missing_signals(self):
        """A student with only fee data (everything else has no data yet) is
        scored purely on that signal, not diluted by treating missing
        signals as risk-free zeros."""
        with schema_context(self.tenant.schema_name):
            today = timezone.now().date()
            StudentFeeInvoice.objects.create(
                student=self.student.user, due_date=today - datetime.timedelta(days=70),
                total_amount=Decimal("2000"), status=StudentFeeInvoice.STATUS_UNPAID,
            )
            result = risk_scoring.compute_risk_score(self.student)
            # Only the fee signal fired (concern 100, weight 0.25) — re-normalized
            # over just that weight, the composite score should equal the fee
            # concern itself, not 100 * 0.25 diluted by absent signals.
            self.assertAlmostEqual(result["risk_score"], 100.0)
            self.assertEqual(result["risk_tier"], StudentRiskScore.TIER_HIGH)
            self.assertIsNone(result["attendance_rate"])
            self.assertIsNone(result["exam_trend_score"])
            self.assertIsNone(result["assignment_submission_rate"])

    def test_compute_risk_score_no_signals_is_low_risk_with_a_note(self):
        with schema_context(self.tenant.schema_name):
            result = risk_scoring.compute_risk_score(self.student)
            self.assertEqual(result["risk_score"], 0.0)
            self.assertEqual(result["risk_tier"], StudentRiskScore.TIER_LOW)
            self.assertIn("No risk signals", result["notes"])


class RecomputeRiskScoresCommandTests(_RiskFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.department = self._department(code="CMD")
            self.active_student = self._student(self.department, suffix="active")
            self.dropped_student = self._student(self.department, suffix="dropped", academic_status="dropped")

    def test_command_scores_active_students_and_skips_dropped(self):
        with schema_context(self.tenant.schema_name):
            call_command("recompute_risk_scores", tenant=self.tenant.schema_name)

            self.assertTrue(StudentRiskScore.objects.filter(student=self.active_student).exists())
            self.assertFalse(StudentRiskScore.objects.filter(student=self.dropped_student).exists())

    def test_command_is_idempotent_via_update_or_create(self):
        with schema_context(self.tenant.schema_name):
            call_command("recompute_risk_scores", tenant=self.tenant.schema_name)
            call_command("recompute_risk_scores", tenant=self.tenant.schema_name)
            self.assertEqual(StudentRiskScore.objects.filter(student=self.active_student).count(), 1)


class AtRiskStudentsAPITests(_RiskFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ("Faculty", "student"):
                Group.objects.get_or_create(name=role)

            self.department = self._department(code="API")
            self.other_department = self._department(code="API2")
            self.student = self._student(self.department, suffix="api")

            faculty_user = User.objects.create_user(
                username="risk_faculty", email="risk_faculty@test.com", password="pw12345!",
            )
            faculty_user.groups.add(Group.objects.get(name="Faculty"))
            self.faculty_token = RefreshToken.for_user(faculty_user)
            self.faculty_token["tenant_schema"] = self.tenant.schema_name

            student_login_user = User.objects.create_user(
                username="risk_student", email="risk_student@test.com", password="pw12345!",
            )
            student_login_user.groups.add(Group.objects.get(name="student"))
            self.student_token = RefreshToken.for_user(student_login_user)
            self.student_token["tenant_schema"] = self.tenant.schema_name

            self.score = StudentRiskScore.objects.create(
                student=self.student, risk_score=72.0, risk_tier=StudentRiskScore.TIER_HIGH,
                attendance_rate=40.0, notes="Attendance 40%.",
            )

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

    def test_students_cannot_view_at_risk_list(self):
        response = self.client.get(reverse("analytics-at-risk-students"), **self._auth(self.student_token))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_faculty_sees_scores_ordered_by_risk(self):
        with schema_context(self.tenant.schema_name):
            other_student = self._student(self.other_department, suffix="api2")
            StudentRiskScore.objects.create(
                student=other_student, risk_score=20.0, risk_tier=StudentRiskScore.TIER_LOW,
            )

        response = self.client.get(reverse("analytics-at-risk-students"), **self._auth(self.faculty_token))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)
        self.assertEqual(response.data[0]["risk_tier"], "high")

    def test_filter_by_department(self):
        with schema_context(self.tenant.schema_name):
            other_student = self._student(self.other_department, suffix="api3")
            StudentRiskScore.objects.create(student=other_student, risk_score=10.0, risk_tier=StudentRiskScore.TIER_LOW)

        response = self.client.get(
            reverse("analytics-at-risk-students"), {"department_id": self.department.id},
            **self._auth(self.faculty_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["student_number"], self.student.student_id)

    def test_filter_by_tier(self):
        response = self.client.get(
            reverse("analytics-at-risk-students"), {"tier": "medium"},
            **self._auth(self.faculty_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 0)

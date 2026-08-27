"""
Tests for Phase 4 of the compliance roadmap: university exam administration
layer (closes gap #18).

- is_student_detained (services/detention.py): term-windowed, department-
  scoped attendance check, disabled by default, mirroring is_student_cleared's
  "not configured = not blocking" shape.
- The student exam list's new is_detained flag, alongside the existing
  is_clearance_blocked.
- RevaluationRequest / MigrationRequest / ConvocationRequest: the same
  pending -> approved/rejected + reviewed_by/reviewed_at shape as
  ResultCorrectionRequest, including the final-exit clearance gate on
  migration/convocation approval (with its override escape hatch).
"""
import datetime
import json

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models.academics import AcademicYear, Term
from .models.attendance import Attendance
from .models.classroom import Classroom
from .models.clearance import ClearanceDesk
from .models.course import Course
from .models.department import Department
from .models.exam import Exam, ExamType
from .models.exam_administration import (
    AttendanceDetentionSettings, ConvocationRequest, MigrationRequest, RevaluationRequest,
)
from .models.lecture import Lecture
from .models.profile import StudentProfile, TeachingStaffProfile
from .models.result import StudentExamResult
from .services.detention import is_student_detained


class _Phase4FixtureMixin:
    def _build_fixture(self):
        for role in ("Administrator",):
            Group.objects.get_or_create(name=role)

        self.dept = Department.objects.create(name="Computer Science", code="CSE")
        self.admin_user = User.objects.create_user(username="admin1", password="pw12345!")
        self.admin_user.groups.add(Group.objects.get(name="Administrator"))

        faculty_user = User.objects.create_user(username="fac1", email="fac1@test.com")
        TeachingStaffProfile.objects.create(user=faculty_user, employee_id="EMP001", department=self.dept)
        self.faculty_user = faculty_user

        student_user = User.objects.create_user(username="stu1", password="pw12345!", email="stu1@test.com")
        self.student = StudentProfile.objects.create(user=student_user, student_id="STU001", department=self.dept)

        self.academic_year = AcademicYear.objects.create(
            name="2026-2027", start_date=datetime.date(2026, 4, 1), end_date=datetime.date(2027, 3, 31),
        )
        self.term = Term.objects.create(
            academic_year=self.academic_year, name="Semester 1", sequence=1,
            start_date=datetime.date(2026, 4, 1), end_date=datetime.date(2026, 9, 30),
        )

        course = Course.objects.create(
            course_code="CS101", course_name="Intro to CS", department=self.dept, semester_number=1, credits=4,
        )
        exam_type = ExamType.objects.create(name="End Semester", code="ENDX")
        self.exam = Exam.objects.create(
            name="CS101 Endsem", exam_type=exam_type, department=self.dept, course=course,
            date=datetime.date(2026, 9, 25), start_time="09:00", end_time="12:00",
            term=self.term, results_published=True,
        )
        self.result = StudentExamResult.objects.create(exam=self.exam, student=self.student, marks_obtained=40)

    def _lecture(self, suffix, days_offset=0):
        classroom = Classroom.objects.create(name=f"Room {suffix}", code=f"R{suffix}")
        start = timezone.make_aware(
            datetime.datetime.combine(self.term.start_date, datetime.time(9, 0)),
        ) + datetime.timedelta(days=days_offset)
        return Lecture.objects.create(
            name=f"Lecture {suffix}", subject="CS101", faculty=self.faculty_user, classroom=classroom,
            start_time=start, end_time=start + datetime.timedelta(hours=1), code=f"LEC-{suffix}",
        )

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}


class DetentionServiceTests(_Phase4FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build_fixture()

    def test_disabled_by_default_does_not_block(self):
        with schema_context(self.tenant.schema_name):
            for i in range(4):
                self._lecture(f"a{i}", days_offset=i)
            is_detained, rate = is_student_detained(self.student, self.exam)
            self.assertFalse(is_detained)
            self.assertIsNone(rate)

    def test_blocks_below_threshold_once_enabled(self):
        with schema_context(self.tenant.schema_name):
            AttendanceDetentionSettings.objects.create(pk=1, is_enabled=True, minimum_attendance_percent=75)
            lectures = [self._lecture(f"b{i}", days_offset=i) for i in range(4)]
            Attendance.objects.create(user=self.student.user, lecture=lectures[0])  # 1 of 4 = 25%

            is_detained, rate = is_student_detained(self.student, self.exam)
            self.assertTrue(is_detained)
            self.assertAlmostEqual(rate, 25.0)

    def test_does_not_block_above_threshold(self):
        with schema_context(self.tenant.schema_name):
            AttendanceDetentionSettings.objects.create(pk=1, is_enabled=True, minimum_attendance_percent=75)
            lectures = [self._lecture(f"c{i}", days_offset=i) for i in range(4)]
            for lecture in lectures:
                Attendance.objects.create(user=self.student.user, lecture=lecture)

            is_detained, rate = is_student_detained(self.student, self.exam)
            self.assertFalse(is_detained)
            self.assertAlmostEqual(rate, 100.0)

    def test_no_term_on_exam_means_no_block(self):
        with schema_context(self.tenant.schema_name):
            AttendanceDetentionSettings.objects.create(pk=1, is_enabled=True, minimum_attendance_percent=75)
            self.exam.term = None
            self.exam.save(update_fields=["term"])

            is_detained, rate = is_student_detained(self.student, self.exam)
            self.assertFalse(is_detained)
            self.assertIsNone(rate)


class ExamListDetentionFlagTests(_Phase4FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build_fixture()
            self.tenant.subscribed_modules = ["exams"]
            self.tenant.save(update_fields=["subscribed_modules"])
            from django.contrib.auth.models import Group as G
            G.objects.get_or_create(name="student")
            self.student.user.groups.add(G.objects.get(name="student"))

    def test_is_detained_flag_on_student_exam_list(self):
        with schema_context(self.tenant.schema_name):
            AttendanceDetentionSettings.objects.create(pk=1, is_enabled=True, minimum_attendance_percent=75)
            self._lecture("d0", days_offset=0)
            self._lecture("d1", days_offset=1)
            # No attendance recorded at all -> 0% -> detained.

        response = self.client.get(reverse("exam-list-create"), **self._auth(self.student.user))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        exam_row = next(e for e in response.data if e["id"] == self.exam.id)
        self.assertTrue(exam_row["is_detained"])


class RevaluationRequestTests(_Phase4FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build_fixture()

    def test_student_creates_and_admin_approves_with_revised_marks(self):
        create_response = self.client.post(
            reverse("revaluationrequest-create"),
            {"result_id": self.result.id, "reason": "Believe I deserve more on Q3."},
            format="json", **self._auth(self.student.user),
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        req_id = create_response.data["id"]

        duplicate_response = self.client.post(
            reverse("revaluationrequest-create"),
            {"result_id": self.result.id, "reason": "Again."},
            format="json", **self._auth(self.student.user),
        )
        self.assertEqual(duplicate_response.status_code, status.HTTP_400_BAD_REQUEST)

        action_response = self.client.post(
            reverse("revaluationrequest-action", args=[req_id]),
            json.dumps({"action": "approve", "revised_marks": 55}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(action_response.status_code, status.HTTP_200_OK, action_response.data)
        self.assertEqual(action_response.data["status"], "approved")
        self.assertEqual(action_response.data["revised_marks"], 55.0)

        with schema_context(self.tenant.schema_name):
            self.result.refresh_from_db()
            self.assertEqual(self.result.marks_obtained, 55)

    def test_reject_leaves_marks_untouched(self):
        with schema_context(self.tenant.schema_name):
            req = RevaluationRequest.objects.create(result=self.result, requested_by=self.student.user, reason="x")

        response = self.client.post(
            reverse("revaluationrequest-action", args=[req.id]),
            json.dumps({"action": "reject"}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["status"], "rejected")
        with schema_context(self.tenant.schema_name):
            self.result.refresh_from_db()
            self.assertEqual(self.result.marks_obtained, 40)


class MigrationAndConvocationTests(_Phase4FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build_fixture()

    def test_migration_approval_blocked_without_clearance_then_overridable(self):
        with schema_context(self.tenant.schema_name):
            group, _ = Group.objects.get_or_create(name="Librarian")
            ClearanceDesk.objects.create(name="Library", code="library", responsible_group=group)

        create_response = self.client.post(
            reverse("migrationrequest-create"),
            {"destination_institution": "Other University"},
            format="json", **self._auth(self.student.user),
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        req_id = create_response.data["id"]

        blocked_response = self.client.post(
            reverse("migrationrequest-action", args=[req_id]),
            json.dumps({"action": "approve", "certificate_number": "MIG-001"}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(blocked_response.status_code, status.HTTP_409_CONFLICT, blocked_response.data)

        override_response = self.client.post(
            reverse("migrationrequest-action", args=[req_id]),
            json.dumps({"action": "approve", "certificate_number": "MIG-001", "override": True}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(override_response.status_code, status.HTTP_200_OK, override_response.data)
        self.assertEqual(override_response.data["status"], "approved")
        self.assertEqual(override_response.data["certificate_number"], "MIG-001")

    def test_convocation_one_per_student_per_year_and_clearance_gate(self):
        first_response = self.client.post(
            reverse("convocationrequest-create"),
            {"academic_year_id": self.academic_year.id},
            format="json", **self._auth(self.student.user),
        )
        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED, first_response.data)

        duplicate_response = self.client.post(
            reverse("convocationrequest-create"),
            {"academic_year_id": self.academic_year.id},
            format="json", **self._auth(self.student.user),
        )
        self.assertEqual(duplicate_response.status_code, status.HTTP_400_BAD_REQUEST)

        # No clearance desks configured at all -> is_student_cleared returns True (nothing to clear).
        approve_response = self.client.post(
            reverse("convocationrequest-action", args=[first_response.data["id"]]),
            json.dumps({"action": "approve"}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(approve_response.status_code, status.HTTP_200_OK, approve_response.data)
        self.assertEqual(approve_response.data["status"], "approved")

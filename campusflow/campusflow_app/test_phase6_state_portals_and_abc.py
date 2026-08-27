"""
Tests for the (demand-confirmed) state-portal-shaped regulatory submissions
and the ABC/APAAR internal modeling:

- FeeRegulatingAuthoritySubmission (#9): draft -> submitted -> decision,
  wrapping data the ledger module already produces.
- SeatMatrix / CAPRound / CAPApplicant / CAPAllotment (#10): the second,
  state-run admissions pipeline, including conversion to a real
  StudentProfile mirroring LeadConvertToStudentView.
- AffiliationApplication / TeacherApprovalProposal / FacultyWorkloadStatement
  / ReservationRosterEntry (#4): university affiliation & LIC, built from
  scratch.
- ABCCreditEntry (#14, internal-modeling-only half): the credit-upload
  pipeline trigger point fired from ExamPublishResultsView, and the sync
  stub.
"""
import datetime
import json

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models.abc_credit import ABCCreditEntry
from .models.academics import AcademicYear, Program, Regulation
from .models.course import Course
from .models.department import Department
from .models.dte_cet_admissions import CAPAllotment, CAPApplicant, CAPRound, SeatMatrix
from .models.exam import Exam, ExamType
from .models.fees import FeeCategory, FeeStructure, FeeStructureItem
from .models.fra import FeeRegulatingAuthoritySubmission
from .models.profile import StudentProfile, TeachingStaffProfile
from .models.result import StudentExamResult
from .models.university_affiliation import (
    AffiliationApplication, FacultyWorkloadStatement, ReservationRosterEntry, TeacherApprovalProposal,
)
from .services.academics import get_default_grading_scheme
from .services.abc_credit import record_credit_entry


class _SharedFixtureMixin:
    def _build_fixture(self):
        for role in ("Administrator", "Faculty", "Department Head"):
            Group.objects.get_or_create(name=role)

        self.dept = Department.objects.create(name="Computer Science", code="CSE")

        self.admin_user = User.objects.create_user(username="admin1", password="pw12345!")
        self.admin_user.groups.add(Group.objects.get(name="Administrator"))

        self.faculty_user = User.objects.create_user(username="fac1", password="pw12345!", email="fac1@test.com")
        self.faculty_user.groups.add(Group.objects.get(name="Faculty"))
        self.faculty_profile = TeachingStaffProfile.objects.create(
            user=self.faculty_user, employee_id="EMP001", department=self.dept,
        )

        self.hod_user = User.objects.create_user(username="hod1", password="pw12345!")
        self.hod_user.groups.add(Group.objects.get(name="Department Head"))

        self.program = Program.objects.create(name="B.Tech CSE", code="BTCSE", department=self.dept)
        self.academic_year = AcademicYear.objects.create(
            name="2026-2027", start_date=datetime.date(2026, 4, 1), end_date=datetime.date(2027, 3, 31),
        )

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}


class FeeRegulatingAuthorityTests(_SharedFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.tenant.subscribed_modules = ["fees"]
            self.tenant.save(update_fields=["subscribed_modules"])
            self._build_fixture()

    def test_draft_submit_and_approve_lifecycle(self):
        create_response = self.client.post(
            reverse("frasubmission-list"),
            {"program": self.program.id, "academic_year": self.academic_year.id, "proposed_fee_amount": 85000},
            format="json", **self._auth(self.admin_user),
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        submission_id = create_response.data["id"]
        self.assertEqual(create_response.data["status"], "draft")

        submit_response = self.client.post(
            reverse("frasubmission-submit", args=[submission_id]), **self._auth(self.admin_user),
        )
        self.assertEqual(submit_response.status_code, status.HTTP_200_OK, submit_response.data)
        self.assertEqual(submit_response.data["status"], "submitted")

        decision_response = self.client.post(
            reverse("frasubmission-record-decision", args=[submission_id]),
            json.dumps({"decision": "approved", "sanctioned_fee_amount": 80000, "fra_order_number": "FRA/2026/001"}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(decision_response.status_code, status.HTTP_200_OK, decision_response.data)
        self.assertEqual(decision_response.data["status"], "approved")
        self.assertEqual(float(decision_response.data["sanctioned_fee_amount"]), 80000.0)

    def test_duplicate_program_year_rejected(self):
        with schema_context(self.tenant.schema_name):
            FeeRegulatingAuthoritySubmission.objects.create(
                program=self.program, academic_year=self.academic_year, proposed_fee_amount=85000,
            )
        response = self.client.post(
            reverse("frasubmission-list"),
            {"program": self.program.id, "academic_year": self.academic_year.id, "proposed_fee_amount": 90000},
            format="json", **self._auth(self.admin_user),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_faculty_cannot_create_submission(self):
        response = self.client.post(
            reverse("frasubmission-list"),
            {"program": self.program.id, "academic_year": self.academic_year.id, "proposed_fee_amount": 85000},
            format="json", **self._auth(self.faculty_user),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_approve_requires_sanctioned_amount(self):
        with schema_context(self.tenant.schema_name):
            submission = FeeRegulatingAuthoritySubmission.objects.create(
                program=self.program, academic_year=self.academic_year, proposed_fee_amount=85000,
            )
            submission.submit()
        response = self.client.post(
            reverse("frasubmission-record-decision", args=[submission.id]),
            json.dumps({"decision": "approved"}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class DTECETAdmissionsTests(_SharedFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.tenant.subscribed_modules = ["admissions"]
            self.tenant.save(update_fields=["subscribed_modules"])
            self._build_fixture()

    def test_seat_matrix_uniqueness(self):
        with schema_context(self.tenant.schema_name):
            SeatMatrix.objects.create(
                program=self.program, academic_year=self.academic_year, quota_category="open", total_seats=60,
            )
            with self.assertRaises(Exception):
                SeatMatrix.objects.create(
                    program=self.program, academic_year=self.academic_year, quota_category="open", total_seats=10,
                )

    def test_full_allotment_confirm_and_convert_to_student(self):
        with schema_context(self.tenant.schema_name):
            cap_round = CAPRound.objects.create(
                academic_year=self.academic_year, round_number=1, name="CAP Round 1",
                start_date=datetime.date(2026, 6, 1), end_date=datetime.date(2026, 6, 15),
            )
            applicant = CAPApplicant.objects.create(
                application_number="MH-CET-0001", first_name="Asha", last_name="Verma",
                email="asha.cap@test.com", cet_percentile=92.5, category="open",
                guardian_name="Sunita Verma", guardian_email="sunita.verma@test.com",
            )
            allotment = CAPAllotment.objects.create(
                applicant=applicant, cap_round=cap_round, program=self.program, quota_category="open",
            )

        confirm_response = self.client.post(
            reverse("capallotment-confirm", args=[allotment.id]), **self._auth(self.admin_user),
        )
        self.assertEqual(confirm_response.status_code, status.HTTP_200_OK, confirm_response.data)
        self.assertEqual(confirm_response.data["status"], "confirmed")

        convert_response = self.client.post(
            reverse("capallotment-convert", args=[allotment.id]), **self._auth(self.admin_user),
        )
        self.assertEqual(convert_response.status_code, status.HTTP_201_CREATED, convert_response.data)
        self.assertIn("admission_number", convert_response.data)

        with schema_context(self.tenant.schema_name):
            allotment.refresh_from_db()
            self.assertIsNotNone(allotment.converted_student)
            self.assertEqual(allotment.converted_student.department_id, self.dept.id)

    def test_cannot_convert_before_confirmed(self):
        with schema_context(self.tenant.schema_name):
            cap_round = CAPRound.objects.create(
                academic_year=self.academic_year, round_number=2, name="CAP Round 2",
                start_date=datetime.date(2026, 6, 16), end_date=datetime.date(2026, 6, 30),
            )
            applicant = CAPApplicant.objects.create(
                application_number="MH-CET-0002", first_name="Ravi", email="ravi.cap@test.com",
                guardian_email="ravi.guardian@test.com",
            )
            allotment = CAPAllotment.objects.create(
                applicant=applicant, cap_round=cap_round, program=self.program, quota_category="open",
            )
        response = self.client.post(reverse("capallotment-convert", args=[allotment.id]), **self._auth(self.admin_user))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cancel_allotment(self):
        with schema_context(self.tenant.schema_name):
            cap_round = CAPRound.objects.create(
                academic_year=self.academic_year, round_number=3, name="CAP Round 3",
                start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2026, 7, 10),
            )
            applicant = CAPApplicant.objects.create(
                application_number="MH-CET-0003", first_name="Meera", email="meera.cap@test.com",
            )
            allotment = CAPAllotment.objects.create(
                applicant=applicant, cap_round=cap_round, program=self.program, quota_category="obc",
            )
        response = self.client.post(
            reverse("capallotment-cancel", args=[allotment.id]),
            json.dumps({"reason": "Candidate did not report."}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["status"], "cancelled")


class UniversityAffiliationTests(_SharedFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.tenant.subscribed_modules = ["compliance-center"]
            self.tenant.save(update_fields=["subscribed_modules"])
            self._build_fixture()
            from .models.module_permissions import TenantModulePermission
            TenantModulePermission.objects.update_or_create(
                group_name="Department Head", defaults={"allowed_modules": ["compliance-center"]},
            )

    def test_affiliation_application_full_lifecycle(self):
        create_response = self.client.post(
            reverse("affiliationapplication-list"),
            {"program": self.program.id, "academic_year": self.academic_year.id},
            format="json", **self._auth(self.admin_user),
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        app_id = create_response.data["id"]

        submit_response = self.client.post(
            reverse("affiliationapplication-submit", args=[app_id]), **self._auth(self.admin_user),
        )
        self.assertEqual(submit_response.status_code, status.HTTP_200_OK, submit_response.data)
        self.assertEqual(submit_response.data["status"], "submitted")

        # Decision before LIC visit is rejected.
        early_decision = self.client.post(
            reverse("affiliationapplication-record-decision", args=[app_id]),
            json.dumps({"decision": "approved"}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(early_decision.status_code, status.HTTP_400_BAD_REQUEST)

        lic_response = self.client.post(
            reverse("affiliationapplication-record-lic-visit", args=[app_id]),
            json.dumps({"visit_date": "2026-09-01", "observations": "Infrastructure adequate.", "compliance_status": "compliant"}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(lic_response.status_code, status.HTTP_200_OK, lic_response.data)
        self.assertEqual(lic_response.data["status"], "lic_visit_scheduled")

        decision_response = self.client.post(
            reverse("affiliationapplication-record-decision", args=[app_id]),
            json.dumps({"decision": "approved", "university_reference_number": "UNIV/AFF/2026/007"}),
            content_type="application/json", **self._auth(self.admin_user),
        )
        self.assertEqual(decision_response.status_code, status.HTTP_200_OK, decision_response.data)
        self.assertEqual(decision_response.data["status"], "approved")

    def test_teacher_approval_faculty_cannot_self_approve(self):
        with schema_context(self.tenant.schema_name):
            proposal = TeacherApprovalProposal.objects.create(
                faculty=self.faculty_profile, academic_year=self.academic_year,
            )
        faculty_attempt = self.client.post(
            reverse("teacherapprovalproposal-record-decision", args=[proposal.id]),
            json.dumps({"decision": "approved"}),
            content_type="application/json", **self._auth(self.faculty_user),
        )
        self.assertEqual(faculty_attempt.status_code, status.HTTP_403_FORBIDDEN)

        hod_response = self.client.post(
            reverse("teacherapprovalproposal-record-decision", args=[proposal.id]),
            json.dumps({"decision": "approved", "university_approval_number": "TA/2026/55"}),
            content_type="application/json", **self._auth(self.hod_user),
        )
        self.assertEqual(hod_response.status_code, status.HTTP_200_OK, hod_response.data)
        self.assertEqual(hod_response.data["status"], "approved")

    def test_workload_statement_and_roster_entry_uniqueness(self):
        from django.db import transaction as db_transaction

        with schema_context(self.tenant.schema_name):
            FacultyWorkloadStatement.objects.create(
                faculty=self.faculty_profile, academic_year=self.academic_year, teaching_hours_per_week=16,
            )
            with self.assertRaises(Exception):
                with db_transaction.atomic():
                    FacultyWorkloadStatement.objects.create(
                        faculty=self.faculty_profile, academic_year=self.academic_year, teaching_hours_per_week=10,
                    )

            ReservationRosterEntry.objects.create(
                department=self.dept, post_designation="Assistant Professor", roster_point_number=1, category="ur",
            )
            with self.assertRaises(Exception):
                with db_transaction.atomic():
                    ReservationRosterEntry.objects.create(
                        department=self.dept, post_designation="Assistant Professor", roster_point_number=1, category="sc",
                    )


class ABCCreditEntryTests(_SharedFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.tenant.subscribed_modules = ["compliance-center", "exams"]
            self.tenant.save(update_fields=["subscribed_modules"])
            self._build_fixture()

    def _exam_with_term(self, term=None, suffix=""):
        regulation = Regulation.objects.create(
            program=self.program, code=f"R2026{suffix}", effective_from_year=2026,
            grading_scheme=get_default_grading_scheme(),
        )
        course = Course.objects.create(
            course_code=f"CS101{suffix}", course_name="Intro to CS", department=self.dept,
            regulation=regulation, semester_number=1, credits=4,
        )
        exam_type = ExamType.objects.create(name="Endsem", code=f"ABCEX{suffix}")
        return Exam.objects.create(
            name="CS101 Endsem", exam_type=exam_type, department=self.dept, course=course,
            date=datetime.date(2026, 11, 1), start_time="09:00", end_time="12:00", term=term,
        )

    def test_record_credit_entry_requires_term(self):
        with schema_context(self.tenant.schema_name):
            from .models.academics import Term
            term = Term.objects.create(
                academic_year=self.academic_year, name="Sem 1", sequence=1,
                start_date=datetime.date(2026, 4, 1), end_date=datetime.date(2026, 9, 30),
            )
            exam_with_term = self._exam_with_term(term=term, suffix="A")
            exam_without_term = self._exam_with_term(term=None, suffix="B")

            student_user = User.objects.create_user(username="stuabc1", email="stuabc1@test.com")
            student = StudentProfile.objects.create(user=student_user, student_id="STUABC1", department=self.dept)

            result_with_term = StudentExamResult.objects.create(
                exam=exam_with_term, student=student, marks_obtained=80,
            )
            result_without_term = StudentExamResult.objects.create(
                exam=exam_without_term, student=student, marks_obtained=80,
            )

            entry = record_credit_entry(result_with_term)
            self.assertIsNotNone(entry)
            self.assertEqual(entry.sync_status, ABCCreditEntry.SYNC_PENDING)
            self.assertEqual(float(entry.credits_earned), 4.0)

            self.assertIsNone(record_credit_entry(result_without_term))

    def test_publish_results_creates_credit_entry_idempotently(self):
        with schema_context(self.tenant.schema_name):
            from .models.academics import Term
            term = Term.objects.create(
                academic_year=self.academic_year, name="Sem 2", sequence=2,
                start_date=datetime.date(2026, 4, 1), end_date=datetime.date(2026, 9, 30),
            )
            exam = self._exam_with_term(term=term)
            student_user = User.objects.create_user(username="stuabc2", email="stuabc2@test.com")
            student = StudentProfile.objects.create(user=student_user, student_id="STUABC2", department=self.dept)
            result = StudentExamResult.objects.create(exam=exam, student=student, marks_obtained=90)

        publish_response = self.client.post(
            reverse("exam-publish-results", args=[exam.id]), **self._auth(self.faculty_user),
        )
        self.assertEqual(publish_response.status_code, status.HTTP_200_OK, publish_response.data)

        with schema_context(self.tenant.schema_name):
            self.assertEqual(ABCCreditEntry.objects.filter(student=student, course=exam.course).count(), 1)
            entry = ABCCreditEntry.objects.get(student=student, course=exam.course)
            self.assertEqual(entry.grade, result.grade)

    def test_sync_stub_flips_status(self):
        with schema_context(self.tenant.schema_name):
            from .models.academics import Term
            term = Term.objects.create(
                academic_year=self.academic_year, name="Sem 3", sequence=1,
                start_date=datetime.date(2026, 4, 1), end_date=datetime.date(2026, 9, 30),
            )
            course = Course.objects.create(
                course_code="CS102", course_name="Discrete Math", department=self.dept,
                regulation=Regulation.objects.create(
                    program=self.program, code="R2027", effective_from_year=2027,
                    grading_scheme=get_default_grading_scheme(),
                ),
                semester_number=1, credits=3,
            )
            student_user = User.objects.create_user(username="stuabc3", email="stuabc3@test.com")
            student = StudentProfile.objects.create(user=student_user, student_id="STUABC3", department=self.dept)
            entry = ABCCreditEntry.objects.create(
                student=student, course=course, academic_year=self.academic_year, credits_earned=3, grade="A",
            )

        response = self.client.post(reverse("abccreditentry-sync", args=[entry.id]), **self._auth(self.admin_user))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["sync_status"], "synced")

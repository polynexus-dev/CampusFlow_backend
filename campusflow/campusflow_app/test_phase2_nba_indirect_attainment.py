"""
Tests for Phase 2 of the compliance roadmap: NBA indirect attainment
(plausibly closes gap #6 to fully built).

- OutcomeIndirectSurvey / OutcomeIndirectSurveyResponse: the survey/response
  model pair for the four NBA indirect channels (course-exit, programme-exit,
  employer, alumni).
- compute_program_outcome_indirect_attainment: 1-5 Likert -> percentage,
  equal-weighted across whichever channels have responses.
- compute_program_outcome_attainment: blends direct + indirect at NBA's
  standard 80:20 ratio, falling back to direct-only when no survey data
  exists yet (mirrors the existing NBAAttainmentRollupTests in tests.py,
  which predate indirect attainment and must keep passing unchanged).
- The collection endpoint: bulk PO-rating submission, validation, and the
  closed-survey / unknown-PO-code / out-of-range-rating rejections.
"""
import datetime
import json

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Department
from .models.academics import AcademicYear, Program, Regulation
from .models.course import Course
from .models.indirect_attainment import OutcomeIndirectSurvey, OutcomeIndirectSurveyResponse
from .models.outcomes import CourseOutcome, POCOMapping, ProgramOutcome
from .services.academics import get_default_grading_scheme
from .services.outcome_attainment import (
    compute_program_outcome_attainment, compute_program_outcome_indirect_attainment,
)


class _Phase2FixtureMixin:
    def _build_fixture(self):
        for role in ("Faculty", "Management"):
            Group.objects.get_or_create(name=role)

        self.dept = Department.objects.create(name="Electronics", code="ECE")
        program = Program.objects.create(name="B.Tech Electronics", code="BTECE", department=self.dept)
        regulation = Regulation.objects.create(
            program=program, code="R2026NBA", effective_from_year=2026,
            grading_scheme=get_default_grading_scheme(),
        )
        course = Course.objects.create(
            course_code="EC401", course_name="Control Systems", department=self.dept,
            regulation=regulation, semester_number=4, credits=4,
        )
        academic_year = AcademicYear.objects.create(
            name="2026-2027", start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2027, 6, 30),
        )

        faculty_user = User.objects.create_user(username="faculty1", password="pw12345!")
        faculty_user.groups.add(Group.objects.get(name="Faculty"))

        student_user = User.objects.create_user(username="plainstudent1", password="pw12345!")

        return {
            "program": program, "course": course, "academic_year": academic_year,
            "faculty_user": faculty_user, "student_user": student_user,
        }

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}


class OutcomeIndirectSurveyModelTests(_Phase2FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_course_exit_survey_requires_a_course(self):
        with schema_context(self.tenant.schema_name):
            survey = OutcomeIndirectSurvey(
                program=self.fixture["program"], academic_year=self.fixture["academic_year"],
                survey_type=OutcomeIndirectSurvey.TYPE_COURSE_EXIT,
            )
            with self.assertRaises(Exception):
                survey.full_clean()

    def test_non_course_exit_survey_rejects_a_course(self):
        with schema_context(self.tenant.schema_name):
            survey = OutcomeIndirectSurvey(
                program=self.fixture["program"], course=self.fixture["course"],
                academic_year=self.fixture["academic_year"], survey_type=OutcomeIndirectSurvey.TYPE_EMPLOYER,
            )
            with self.assertRaises(Exception):
                survey.full_clean()

    def test_duplicate_survey_scope_is_rejected(self):
        with schema_context(self.tenant.schema_name):
            OutcomeIndirectSurvey.objects.create(
                program=self.fixture["program"], course=self.fixture["course"],
                academic_year=self.fixture["academic_year"], survey_type=OutcomeIndirectSurvey.TYPE_COURSE_EXIT,
            )
            with self.assertRaises(Exception):
                OutcomeIndirectSurvey.objects.create(
                    program=self.fixture["program"], course=self.fixture["course"],
                    academic_year=self.fixture["academic_year"], survey_type=OutcomeIndirectSurvey.TYPE_COURSE_EXIT,
                )


class IndirectAttainmentComputationTests(_Phase2FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()
            self.po1 = ProgramOutcome.objects.create(
                program=self.fixture["program"], code="PO1", statement="Engineering knowledge",
            )

    def test_single_channel_average_converts_to_percent(self):
        with schema_context(self.tenant.schema_name):
            survey = OutcomeIndirectSurvey.objects.create(
                program=self.fixture["program"], course=self.fixture["course"],
                academic_year=self.fixture["academic_year"], survey_type=OutcomeIndirectSurvey.TYPE_COURSE_EXIT,
            )
            OutcomeIndirectSurveyResponse.objects.create(survey=survey, program_outcome=self.po1, rating=4)
            OutcomeIndirectSurveyResponse.objects.create(survey=survey, program_outcome=self.po1, rating=5)
            # average rating 4.5 / 5 * 100 = 90.0
            result = compute_program_outcome_indirect_attainment(self.fixture["program"].id)
            self.assertAlmostEqual(result[self.po1.id]["indirect_attainment_percent"], 90.0, delta=0.01)
            self.assertEqual(
                result[self.po1.id]["channel_breakdown"]["course_exit"]["response_count"], 2,
            )

    def test_two_channels_are_equally_weighted_regardless_of_response_count(self):
        with schema_context(self.tenant.schema_name):
            course_exit_survey = OutcomeIndirectSurvey.objects.create(
                program=self.fixture["program"], course=self.fixture["course"],
                academic_year=self.fixture["academic_year"], survey_type=OutcomeIndirectSurvey.TYPE_COURSE_EXIT,
            )
            employer_survey = OutcomeIndirectSurvey.objects.create(
                program=self.fixture["program"], academic_year=self.fixture["academic_year"],
                survey_type=OutcomeIndirectSurvey.TYPE_EMPLOYER,
            )
            # course-exit: 10 respondents all rating 5 -> 100%.
            for _ in range(10):
                OutcomeIndirectSurveyResponse.objects.create(
                    survey=course_exit_survey, program_outcome=self.po1, rating=5,
                )
            # employer: 1 respondent rating 3 -> 60%.
            OutcomeIndirectSurveyResponse.objects.create(survey=employer_survey, program_outcome=self.po1, rating=3)

            result = compute_program_outcome_indirect_attainment(self.fixture["program"].id)
            # Equal-weighted across channels, NOT response-count-weighted: (100 + 60) / 2 = 80.0.
            self.assertAlmostEqual(result[self.po1.id]["indirect_attainment_percent"], 80.0, delta=0.01)


class BlendedAttainmentTests(_Phase2FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def _co_po_with_direct_attainment(self, direct_target_hit):
        """Sets up one CO fully mapped (strength irrelevant with a single CO)
        to one PO, with exactly one evaluated student either clearing or
        missing the CO's threshold, so direct attainment is a clean 100 or 0."""
        from django.utils import timezone

        from .models.exam import Exam, ExamType
        from .models.profile import StudentProfile, TeachingStaffProfile
        from .models.valuation import ScannedPaper, ValuationSession

        co = CourseOutcome.objects.create(
            course=self.fixture["course"], code="CO1", statement="Design controllers",
            target_attainment_percent=50, target_student_percent=50,
        )
        po = ProgramOutcome.objects.create(program=self.fixture["program"], code="PO1", statement="Engg knowledge")
        POCOMapping.objects.create(course_outcome=co, program_outcome=po, strength=2)

        student_user = User.objects.create_user(username="directstu1", email="directstu1@test.com")
        student = StudentProfile.objects.create(user=student_user, student_id="NBA-D1", department=self.dept)

        exam_type = ExamType.objects.create(name="Mid", code="P2NBA")
        exam = Exam.objects.create(
            name="Indirect-Blend Exam", exam_type=exam_type, department=self.dept, course=self.fixture["course"],
            date="2026-11-01", start_time="09:00", end_time="12:00",
            question_structure={"Q1": {"marks": 10, "course_outcome": "CO1"}},
        )
        evaluator_user = User.objects.create_user(username="p2eval1", email="p2eval1@test.com")
        evaluator = TeachingStaffProfile.objects.create(user=evaluator_user, employee_id="P2EMP1", department=self.dept)
        session = ValuationSession.objects.create(exam=exam, evaluator=evaluator)
        obtained = 10 if direct_target_hit else 0
        ScannedPaper.objects.create(
            session=session, student=student, scanned_file_url="s3://x",
            status="Evaluated", evaluated_at=timezone.now(), question_scores={"Q1": obtained},
        )
        return po

    def test_falls_back_to_direct_only_when_no_indirect_data(self):
        with schema_context(self.tenant.schema_name):
            po = self._co_po_with_direct_attainment(direct_target_hit=True)
            results = compute_program_outcome_attainment(self.fixture["program"].id)
            po1_result = next(r for r in results if r["code"] == "PO1")
            self.assertEqual(po1_result["direct_attainment_percent"], 100.0)
            self.assertIsNone(po1_result["indirect_attainment_percent"])
            self.assertEqual(po1_result["attainment_percent"], 100.0)

    def test_blends_direct_and_indirect_at_80_20(self):
        with schema_context(self.tenant.schema_name):
            po = self._co_po_with_direct_attainment(direct_target_hit=True)  # direct = 100.0
            survey = OutcomeIndirectSurvey.objects.create(
                program=self.fixture["program"], course=self.fixture["course"],
                academic_year=self.fixture["academic_year"], survey_type=OutcomeIndirectSurvey.TYPE_COURSE_EXIT,
            )
            OutcomeIndirectSurveyResponse.objects.create(survey=survey, program_outcome=po, rating=3)  # 60%

            results = compute_program_outcome_attainment(self.fixture["program"].id)
            po1_result = next(r for r in results if r["code"] == "PO1")
            self.assertEqual(po1_result["direct_attainment_percent"], 100.0)
            self.assertAlmostEqual(po1_result["indirect_attainment_percent"], 60.0, delta=0.01)
            # 0.8*100 + 0.2*60 = 92.0
            self.assertAlmostEqual(po1_result["attainment_percent"], 92.0, delta=0.01)


class IndirectSurveyEndpointTests(_Phase2FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()
            self.po1 = ProgramOutcome.objects.create(
                program=self.fixture["program"], code="PO1", statement="Engineering knowledge",
            )
            self.po2 = ProgramOutcome.objects.create(
                program=self.fixture["program"], code="PO2", statement="Problem analysis",
            )

    def test_faculty_can_create_survey_and_submit_bulk_ratings(self):
        create_response = self.client.post(
            reverse("indirect-survey-list", args=[self.fixture["program"].id]),
            {
                "survey_type": "employer",
                "academic_year_id": self.fixture["academic_year"].id,
            },
            format="json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        survey_id = create_response.data["id"]

        submit_response = self.client.post(
            reverse("indirect-survey-response-list", args=[survey_id]),
            json.dumps({"respondent_label": "Acme Corp", "ratings": {"PO1": 5, "PO2": 4}}),
            content_type="application/json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(submit_response.status_code, status.HTTP_201_CREATED, submit_response.data)
        self.assertEqual(submit_response.data["created"], 2)

        with schema_context(self.tenant.schema_name):
            self.assertEqual(OutcomeIndirectSurveyResponse.objects.filter(survey_id=survey_id).count(), 2)

    def test_plain_student_cannot_create_survey(self):
        response = self.client.post(
            reverse("indirect-survey-list", args=[self.fixture["program"].id]),
            {"survey_type": "alumni", "academic_year_id": self.fixture["academic_year"].id},
            format="json", **self._auth(self.fixture["student_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_program_outcome_code_is_rejected(self):
        with schema_context(self.tenant.schema_name):
            survey = OutcomeIndirectSurvey.objects.create(
                program=self.fixture["program"], academic_year=self.fixture["academic_year"],
                survey_type=OutcomeIndirectSurvey.TYPE_ALUMNI,
            )
        response = self.client.post(
            reverse("indirect-survey-response-list", args=[survey.id]),
            json.dumps({"ratings": {"PO99": 4}}),
            content_type="application/json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("PO99", response.data["error"])

    def test_out_of_range_rating_is_rejected(self):
        with schema_context(self.tenant.schema_name):
            survey = OutcomeIndirectSurvey.objects.create(
                program=self.fixture["program"], academic_year=self.fixture["academic_year"],
                survey_type=OutcomeIndirectSurvey.TYPE_ALUMNI,
            )
        response = self.client.post(
            reverse("indirect-survey-response-list", args=[survey.id]),
            json.dumps({"ratings": {"PO1": 7}}),
            content_type="application/json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("1-5", response.data["error"])

    def test_closed_survey_rejects_new_responses(self):
        with schema_context(self.tenant.schema_name):
            survey = OutcomeIndirectSurvey.objects.create(
                program=self.fixture["program"], academic_year=self.fixture["academic_year"],
                survey_type=OutcomeIndirectSurvey.TYPE_ALUMNI, is_open=False,
            )
        response = self.client.post(
            reverse("indirect-survey-response-list", args=[survey.id]),
            json.dumps({"ratings": {"PO1": 4}}),
            content_type="application/json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("closed", response.data["error"])

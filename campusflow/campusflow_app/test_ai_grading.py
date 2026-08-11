"""
Tests for the AI-assisted valuation feature: ai_grading.py's pure-Python
prompt/parsing logic, the run_ai_grading_suggestion Celery task, and the
ai-suggest/apply/reject API endpoints. The Ollama HTTP call is always
mocked — these never make a real network call or need `ollama serve`
running.
"""

import datetime
import json
from decimal import Decimal
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from django.test import TestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .ai_grading import AIGradingError, _build_system_prompt, fetch_scanned_image, grade_scanned_paper
from .models.ai_grading import AIGradingSuggestion
from .models.course import Course
from .models.department import Department
from .models.exam import Exam, ExamType
from .models.profile import StudentProfile, TeachingStaffProfile
from .models.valuation import ScannedPaper, ValuationSession
from .tasks import run_ai_grading_suggestion


class AIGradingUnitTests(TestCase):
    """Pure-Python tests for ai_grading.py — no DB, no tenant, no network."""

    def test_build_system_prompt_includes_structure_and_rubric(self):
        prompt = _build_system_prompt(
            {"Q1": 10}, {"Q1": {"max_marks": 10, "rubric": "Award full marks for a correct derivation."}},
        )
        self.assertIn('"Q1": 10', prompt)
        self.assertIn("Award full marks for a correct derivation.", prompt)

    @patch("campusflow_app.ai_grading.requests.get")
    def test_fetch_scanned_image_rejects_non_image_content_type(self, mock_get):
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.raise_for_status.return_value = None
        mock_get.return_value = mock_response

        with self.assertRaises(AIGradingError):
            fetch_scanned_image("https://example.com/not-an-image")

    @patch("campusflow_app.ai_grading.requests.get")
    def test_fetch_scanned_image_enforces_size_cap(self, mock_get):
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "image/png"}
        mock_response.raise_for_status.return_value = None
        mock_response.iter_content.return_value = [b"x" * 1024 for _ in range(20)]
        mock_get.return_value = mock_response

        with self.settings(AI_GRADING_MAX_IMAGE_BYTES=1024):
            with self.assertRaises(AIGradingError):
                fetch_scanned_image("https://example.com/huge.png")

    @patch("campusflow_app.ai_grading.requests.get")
    def test_fetch_scanned_image_returns_bytes_and_normalized_media_type(self, mock_get):
        mock_response = MagicMock()
        mock_response.headers = {"Content-Type": "image/png; charset=binary"}
        mock_response.raise_for_status.return_value = None
        mock_response.iter_content.return_value = [b"chunk1", b"chunk2"]
        mock_get.return_value = mock_response

        image_bytes, media_type = fetch_scanned_image("https://example.com/paper.png")
        self.assertEqual(image_bytes, b"chunk1chunk2")
        self.assertEqual(media_type, "image/png")

    @patch("campusflow_app.ai_grading.requests.post")
    def test_grade_scanned_paper_parses_structured_response(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "done_reason": "stop",
            "message": {"content": json.dumps({
                "questions": [{"key": "Q1", "score": 8, "max_marks": 10, "rationale": "Good work.", "confidence": 0.9}],
                "overall_confidence": 0.85,
                "overall_notes": "Looks solid.",
            })},
        }
        mock_post.return_value = mock_response

        result = grade_scanned_paper(b"fakeimage", {"Q1": 10}, {})
        self.assertEqual(result["questions"][0]["score"], 8)
        self.assertEqual(result["overall_confidence"], 0.85)

    @patch("campusflow_app.ai_grading.requests.post")
    def test_grade_scanned_paper_raises_on_truncated_output(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"done_reason": "length", "message": {"content": ""}}
        mock_post.return_value = mock_response

        with self.assertRaises(AIGradingError):
            grade_scanned_paper(b"fakeimage", {"Q1": 10}, {})

    @patch("campusflow_app.ai_grading.requests.post")
    def test_grade_scanned_paper_raises_on_connection_error(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("refused")

        with self.assertRaises(AIGradingError):
            grade_scanned_paper(b"fakeimage", {"Q1": 10}, {})

    @patch("campusflow_app.ai_grading.requests.post")
    def test_grade_scanned_paper_raises_on_invalid_json(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"done_reason": "stop", "message": {"content": "not valid json"}}
        mock_post.return_value = mock_response

        with self.assertRaises(AIGradingError):
            grade_scanned_paper(b"fakeimage", {"Q1": 10}, {})


class _ValuationFixtureMixin:
    """Shared fixture builder for AI-grading DB/task/API tests."""

    def _build_exam(self, dept_code="CS", answer_key=None):
        department = Department.objects.create(name=f"Dept {dept_code}", code=dept_code)
        course = Course.objects.create(
            course_code=f"{dept_code}101", course_name=f"{dept_code} 101", department=department,
        )
        exam_type = ExamType.objects.create(name="Mid Term", code=f"MID-{dept_code}")
        return Exam.objects.create(
            name=f"{dept_code} Mid Term", exam_type=exam_type, department=department, course=course,
            date=datetime.date(2026, 3, 1), start_time=datetime.time(10, 0), end_time=datetime.time(12, 0),
            question_structure={"Q1": 10, "Q2": 10}, answer_key=answer_key or {},
        )

    def _build_paper(self, exam, suffix=""):
        evaluator_user = User.objects.create_user(
            username=f"faculty{suffix}", email=f"faculty{suffix}@test.com", password="pw12345!",
        )
        evaluator = TeachingStaffProfile.objects.create(user=evaluator_user, employee_id=f"EMP{suffix}")
        student_user = User.objects.create_user(
            username=f"student{suffix}", email=f"student{suffix}@test.com", password="pw12345!",
        )
        student = StudentProfile.objects.create(user=student_user, student_id=f"STU{suffix}")
        session = ValuationSession.objects.create(exam=exam, evaluator=evaluator)
        paper = ScannedPaper.objects.create(
            session=session, student=student, scanned_file_url="https://example.com/scan.png",
        )
        return paper, evaluator_user, student_user


class RunAIGradingSuggestionTaskTests(_ValuationFixtureMixin, TenantTestCase):
    """
    Calls the Celery task directly (not via .delay()) — @shared_task-wrapped
    functions are plain callables that run in-process, so this needs no
    broker/worker.
    """

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            exam = self._build_exam(answer_key={"Q1": {"max_marks": 10, "rubric": "Newton's laws."}})
            self.paper, _, _ = self._build_paper(exam, suffix="_task")
            self.suggestion = AIGradingSuggestion.objects.create(scanned_paper=self.paper)

    @patch("campusflow_app.ai_grading.grade_scanned_paper")
    @patch("campusflow_app.ai_grading.fetch_scanned_image")
    def test_task_success_populates_suggestion(self, mock_fetch, mock_grade):
        mock_fetch.return_value = (b"fakebytes", "image/png")
        mock_grade.return_value = {
            "questions": [{"key": "Q1", "score": 9, "max_marks": 10, "rationale": "Great.", "confidence": 0.95}],
            "overall_confidence": 0.9,
            "overall_notes": "Looks great.",
        }

        run_ai_grading_suggestion(self.tenant.schema_name, self.suggestion.id)

        with schema_context(self.tenant.schema_name):
            suggestion = AIGradingSuggestion.objects.get(pk=self.suggestion.id)
            self.assertEqual(suggestion.status, "pending")  # only "apply" sets it to applied
            self.assertEqual(suggestion.question_scores_suggested["Q1"]["score"], 9)
            self.assertEqual(suggestion.overall_confidence, 0.9)
            self.assertEqual(suggestion.overall_notes, "Looks great.")

    @patch("campusflow_app.ai_grading.fetch_scanned_image")
    def test_task_records_failure_on_ai_grading_error(self, mock_fetch):
        mock_fetch.side_effect = AIGradingError("could not fetch image")

        run_ai_grading_suggestion(self.tenant.schema_name, self.suggestion.id)

        with schema_context(self.tenant.schema_name):
            suggestion = AIGradingSuggestion.objects.get(pk=self.suggestion.id)
            self.assertEqual(suggestion.status, "failed")
            self.assertIn("could not fetch image", suggestion.error_message)

    def test_task_no_op_when_suggestion_missing(self):
        # Should not raise even if the row is gone by the time the task runs.
        run_ai_grading_suggestion(self.tenant.schema_name, self.suggestion.id + 9999)


class AIGradingSuggestionAPITests(_ValuationFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ("Faculty", "student", "Management"):
                Group.objects.get_or_create(name=role)

            self.exam = self._build_exam()
            self.paper, self.evaluator_user, self.student_user = self._build_paper(self.exam, suffix="_api")
            self.evaluator_user.groups.add(Group.objects.get(name="Faculty"))
            self.student_user.groups.add(Group.objects.get(name="student"))

            self.faculty_token = RefreshToken.for_user(self.evaluator_user)
            self.faculty_token["tenant_schema"] = self.tenant.schema_name
            self.student_token = RefreshToken.for_user(self.student_user)
            self.student_token["tenant_schema"] = self.tenant.schema_name

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

    def test_ai_suggest_requires_answer_key(self):
        response = self.client.post(
            reverse("scannedpaper-ai-suggest", args=[self.paper.id]),
            format="json", **self._auth(self.faculty_token),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("campusflow_app.views.valuation.run_ai_grading_suggestion.delay")
    def test_ai_suggest_queues_task_when_rubric_present(self, mock_delay):
        with schema_context(self.tenant.schema_name):
            self.exam.answer_key = {"Q1": {"max_marks": 10, "rubric": "Full marks for correct derivation."}}
            self.exam.save(update_fields=["answer_key"])

        response = self.client.post(
            reverse("scannedpaper-ai-suggest", args=[self.paper.id]),
            format="json", **self._auth(self.faculty_token),
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once()
        with schema_context(self.tenant.schema_name):
            self.assertEqual(AIGradingSuggestion.objects.filter(scanned_paper=self.paper).count(), 1)

    def test_student_cannot_trigger_ai_suggest(self):
        with schema_context(self.tenant.schema_name):
            self.exam.answer_key = {"Q1": {"max_marks": 10}}
            self.exam.save(update_fields=["answer_key"])

        response = self.client.post(
            reverse("scannedpaper-ai-suggest", args=[self.paper.id]),
            format="json", **self._auth(self.student_token),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_apply_suggestion_updates_paper_and_marks_evaluated(self):
        with schema_context(self.tenant.schema_name):
            suggestion = AIGradingSuggestion.objects.create(
                scanned_paper=self.paper,
                question_scores_suggested={
                    "Q1": {"score": 8, "max_marks": 10, "rationale": "Good.", "confidence": 0.9},
                    "Q2": {"score": 7, "max_marks": 10, "rationale": "Ok.", "confidence": 0.7},
                },
                overall_confidence=0.8,
            )

        response = self.client.post(
            reverse("ai-suggestion-apply", args=[suggestion.id]),
            format="json", **self._auth(self.faculty_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        with schema_context(self.tenant.schema_name):
            paper = ScannedPaper.objects.get(pk=self.paper.id)
            suggestion.refresh_from_db()
            self.assertEqual(paper.status, "Evaluated")
            self.assertEqual(paper.question_scores, {"Q1": 8, "Q2": 7})
            self.assertEqual(paper.allocated_marks, Decimal("15"))
            self.assertEqual(paper.evaluated_by_id, self.evaluator_user.id)
            self.assertEqual(suggestion.status, "applied")
            self.assertEqual(suggestion.applied_by_id, self.evaluator_user.id)

    def test_apply_already_evaluated_paper_requires_force(self):
        with schema_context(self.tenant.schema_name):
            self.paper.status = "Evaluated"
            self.paper.save(update_fields=["status"])
            suggestion = AIGradingSuggestion.objects.create(
                scanned_paper=self.paper,
                question_scores_suggested={"Q1": {"score": 5, "max_marks": 10, "rationale": "x", "confidence": 0.5}},
            )

        blocked = self.client.post(
            reverse("ai-suggestion-apply", args=[suggestion.id]),
            format="json", **self._auth(self.faculty_token),
        )
        self.assertEqual(blocked.status_code, status.HTTP_409_CONFLICT)

        forced = self.client.post(
            reverse("ai-suggestion-apply", args=[suggestion.id]) + "?force=true",
            format="json", **self._auth(self.faculty_token),
        )
        self.assertEqual(forced.status_code, status.HTTP_200_OK)

    def test_apply_non_pending_suggestion_rejected(self):
        with schema_context(self.tenant.schema_name):
            suggestion = AIGradingSuggestion.objects.create(scanned_paper=self.paper, status="rejected")

        response = self.client.post(
            reverse("ai-suggestion-apply", args=[suggestion.id]),
            format="json", **self._auth(self.faculty_token),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_suggestion(self):
        with schema_context(self.tenant.schema_name):
            suggestion = AIGradingSuggestion.objects.create(scanned_paper=self.paper)

        response = self.client.post(
            reverse("ai-suggestion-reject", args=[suggestion.id]),
            format="json", **self._auth(self.faculty_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        with schema_context(self.tenant.schema_name):
            suggestion.refresh_from_db()
            self.assertEqual(suggestion.status, "rejected")

    def test_reject_non_pending_suggestion_rejected(self):
        with schema_context(self.tenant.schema_name):
            suggestion = AIGradingSuggestion.objects.create(scanned_paper=self.paper, status="applied")

        response = self.client.post(
            reverse("ai-suggestion-reject", args=[suggestion.id]),
            format="json", **self._auth(self.faculty_token),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

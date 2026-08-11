"""
Tests for the NAAC/NBA accreditation narrative-drafting feature:
ai_narrative.py's pure-Python prompt/parsing logic, the
run_accreditation_narrative_draft Celery task, and the
narrative-draft/apply/reject API endpoints plus SSRExportView's narrative
inclusion. The Ollama HTTP call is always mocked.
"""

import datetime
import json
from unittest.mock import MagicMock, patch

import requests
from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from django.test import TestCase
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .ai_narrative import NarrativeDraftError, build_criterion_narrative
from .models.accreditation_narrative import AccreditationNarrativeDraft
from .models.compliance import AccreditationCriterion, EvidenceItem
from .models.department import Department
from .models.finance import FinancialYear
from .tasks import run_accreditation_narrative_draft


class AINarrativeUnitTests(TestCase):
    """Pure-Python tests for ai_narrative.py — no tenant, no network."""

    @patch("campusflow_app.ai_narrative.requests.post")
    def test_build_criterion_narrative_parses_structured_response(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "done_reason": "stop",
            "message": {"content": json.dumps({
                "narrative": "The institution has established robust processes for...",
                "caveats": "No evidence found for sub-metric 1.1.3.",
            })},
        }
        mock_post.return_value = mock_response

        criterion = MagicMock(spec=AccreditationCriterion)
        criterion.get_body_display.return_value = "NAAC"
        criterion.code = "1.1"
        criterion.title = "Curricular Planning"
        criterion.evidence.filter.return_value.select_related.return_value = []
        financial_year = MagicMock(label="2025-2026")

        result = build_criterion_narrative(criterion, financial_year)
        self.assertIn("robust processes", result["narrative"])
        self.assertIn("1.1.3", result["caveats"])

    @patch("campusflow_app.ai_narrative.requests.post")
    def test_build_criterion_narrative_raises_on_connection_error(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("refused")

        criterion = MagicMock(spec=AccreditationCriterion)
        criterion.get_body_display.return_value = "NAAC"
        criterion.evidence.filter.return_value.select_related.return_value = []
        financial_year = MagicMock(label="2025-2026")

        with self.assertRaises(NarrativeDraftError):
            build_criterion_narrative(criterion, financial_year)

    @patch("campusflow_app.ai_narrative.requests.post")
    def test_build_criterion_narrative_raises_on_invalid_json(self, mock_post):
        mock_response = MagicMock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {"done_reason": "stop", "message": {"content": "not valid json"}}
        mock_post.return_value = mock_response

        criterion = MagicMock(spec=AccreditationCriterion)
        criterion.get_body_display.return_value = "NAAC"
        criterion.evidence.filter.return_value.select_related.return_value = []
        financial_year = MagicMock(label="2025-2026")

        with self.assertRaises(NarrativeDraftError):
            build_criterion_narrative(criterion, financial_year)


class _NarrativeFixtureMixin:
    def _criterion(self, code="1.1", body="NAAC"):
        return AccreditationCriterion.objects.create(body=body, code=code, title=f"Criterion {code}")

    def _financial_year(self, label="2025-2026"):
        return FinancialYear.objects.create(
            label=label, start_date=datetime.date(2025, 4, 1), end_date=datetime.date(2026, 3, 31),
        )

    def _evidence(self, criterion, financial_year, department=None, description="Some evidence."):
        return EvidenceItem.objects.create(
            criterion=criterion, financial_year=financial_year, department=department, description=description,
        )


class RunAccreditationNarrativeDraftTaskTests(_NarrativeFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.criterion = self._criterion()
            self.financial_year = self._financial_year()
            self._evidence(self.criterion, self.financial_year)
            self.draft = AccreditationNarrativeDraft.objects.create(
                criterion=self.criterion, financial_year=self.financial_year,
            )

    @patch("campusflow_app.ai_narrative.build_criterion_narrative")
    def test_task_success_populates_draft(self, mock_build):
        mock_build.return_value = {"narrative": "Drafted narrative text.", "caveats": "None."}

        run_accreditation_narrative_draft(self.tenant.schema_name, self.draft.id)

        with schema_context(self.tenant.schema_name):
            draft = AccreditationNarrativeDraft.objects.get(pk=self.draft.id)
            self.assertEqual(draft.status, "pending")  # only "apply" flips this
            self.assertEqual(draft.narrative_text, "Drafted narrative text.")
            self.assertEqual(draft.caveats, "None.")
            self.assertTrue(draft.model_used)

    @patch("campusflow_app.ai_narrative.build_criterion_narrative")
    def test_task_records_failure_on_narrative_draft_error(self, mock_build):
        mock_build.side_effect = NarrativeDraftError("drafting service unavailable")

        run_accreditation_narrative_draft(self.tenant.schema_name, self.draft.id)

        with schema_context(self.tenant.schema_name):
            draft = AccreditationNarrativeDraft.objects.get(pk=self.draft.id)
            self.assertEqual(draft.status, "failed")
            self.assertIn("drafting service unavailable", draft.error_message)

    def test_task_no_op_when_draft_missing(self):
        run_accreditation_narrative_draft(self.tenant.schema_name, self.draft.id + 9999)


class AccreditationNarrativeAPITests(_NarrativeFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ("Management", "Faculty"):
                Group.objects.get_or_create(name=role)

            self.criterion = self._criterion()
            self.financial_year = self._financial_year()

            admin_user = User.objects.create_user(
                username="iqac_admin", email="iqac_admin@test.com", password="pw12345!",
            )
            admin_user.groups.add(Group.objects.get(name="Management"))
            self.admin_token = RefreshToken.for_user(admin_user)
            self.admin_token["tenant_schema"] = self.tenant.schema_name

            faculty_user = User.objects.create_user(
                username="plain_faculty", email="plain_faculty@test.com", password="pw12345!",
            )
            faculty_user.groups.add(Group.objects.get(name="Faculty"))
            self.faculty_token = RefreshToken.for_user(faculty_user)
            self.faculty_token["tenant_schema"] = self.tenant.schema_name

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

    def test_faculty_cannot_trigger_draft(self):
        response = self.client.post(
            reverse("accreditationcriterion-narrative-draft", args=[self.criterion.id]),
            {"financial_year": self.financial_year.id}, format="json", **self._auth(self.faculty_token),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_trigger_requires_financial_year_param(self):
        response = self.client.post(
            reverse("accreditationcriterion-narrative-draft", args=[self.criterion.id]),
            format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_trigger_requires_at_least_one_evidence_item(self):
        response = self.client.post(
            f"{reverse('accreditationcriterion-narrative-draft', args=[self.criterion.id])}?financial_year={self.financial_year.id}",
            format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("campusflow_app.views.compliance.run_accreditation_narrative_draft.delay")
    def test_trigger_queues_task_when_evidence_present(self, mock_delay):
        with schema_context(self.tenant.schema_name):
            self._evidence(self.criterion, self.financial_year)

        response = self.client.post(
            f"{reverse('accreditationcriterion-narrative-draft', args=[self.criterion.id])}?financial_year={self.financial_year.id}",
            format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        mock_delay.assert_called_once()
        with schema_context(self.tenant.schema_name):
            self.assertEqual(
                AccreditationNarrativeDraft.objects.filter(criterion=self.criterion).count(), 1,
            )

    def test_apply_and_reject_lifecycle(self):
        with schema_context(self.tenant.schema_name):
            draft = AccreditationNarrativeDraft.objects.create(
                criterion=self.criterion, financial_year=self.financial_year, narrative_text="Draft text.",
            )

        applied = self.client.post(
            reverse("narrativedraft-apply", args=[draft.id]), format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(applied.status_code, status.HTTP_200_OK)
        self.assertEqual(applied.data["status"], "applied")

        # Already-applied cannot be applied again.
        reapplied = self.client.post(
            reverse("narrativedraft-apply", args=[draft.id]), format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(reapplied.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reject_pending_draft(self):
        with schema_context(self.tenant.schema_name):
            draft = AccreditationNarrativeDraft.objects.create(
                criterion=self.criterion, financial_year=self.financial_year,
            )
        response = self.client.post(
            reverse("narrativedraft-reject", args=[draft.id]), format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        with schema_context(self.tenant.schema_name):
            draft.refresh_from_db()
            self.assertEqual(draft.status, "rejected")

    def test_patch_edits_narrative_text(self):
        with schema_context(self.tenant.schema_name):
            draft = AccreditationNarrativeDraft.objects.create(
                criterion=self.criterion, financial_year=self.financial_year, narrative_text="AI draft.",
            )
        response = self.client.patch(
            reverse("narrativedraft-detail", args=[draft.id]),
            {"narrative_text": "Reviewer-edited text."}, format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        with schema_context(self.tenant.schema_name):
            draft.refresh_from_db()
            self.assertEqual(draft.narrative_text, "Reviewer-edited text.")

    def test_ssr_export_includes_applied_narrative_when_year_scoped(self):
        with schema_context(self.tenant.schema_name):
            self._evidence(self.criterion, self.financial_year)
            AccreditationNarrativeDraft.objects.create(
                criterion=self.criterion, financial_year=self.financial_year,
                narrative_text="The final applied narrative.", status="applied",
            )

        response = self.client.get(
            f"{reverse('compliance-center-ssr-export')}?financial_year={self.financial_year.id}",
            **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entry = next(e for e in response.data["criteria"] if e["criterion"]["id"] == self.criterion.id)
        self.assertEqual(entry["narrative"], "The final applied narrative.")

    def test_ssr_export_omits_narrative_key_without_financial_year(self):
        response = self.client.get(reverse("compliance-center-ssr-export"), **self._auth(self.admin_token))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        entry = next(e for e in response.data["criteria"] if e["criterion"]["id"] == self.criterion.id)
        self.assertNotIn("narrative", entry)

"""
Tests for the Admissions/CRM module: services/lead_scoring.py's pure
signal/composite logic, Lead's stage-transition methods, and the full
Lead pipeline API including the convert-to-student hand-off into
views/enrollment.py's account-creation primitives.

campusflow_app is a TENANT_APP (django-tenants) — every DB operation below
runs inside schema_context(self.tenant.schema_name), matching the
convention already established in test_risk_scoring.py/test_ai_grading.py.
"""

import datetime

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models.admissions import Lead, LeadActivity
from .models.department import Department
from .models.profile import StudentProfile
from .services import lead_scoring


def _make_lead(**overrides):
    defaults = dict(first_name="Asha", last_name="Rao", email="asha@example.com", source=Lead.SOURCE_WEBSITE)
    defaults.update(overrides)
    return Lead.objects.create(**defaults)


class LeadScoringUnitTests(TenantTestCase):
    """Tests against lead_scoring.py's signal functions."""

    def test_engagement_signal_scales_with_activity_count_up_to_saturation(self):
        with schema_context(self.tenant.schema_name):
            lead = _make_lead()
            self.assertEqual(lead_scoring._engagement_signal(lead), 0.0)

            for _ in range(3):
                LeadActivity.objects.create(lead=lead, activity_type=LeadActivity.TYPE_CALL)
            self.assertAlmostEqual(lead_scoring._engagement_signal(lead), (3 / 5) * 100)

            for _ in range(10):
                LeadActivity.objects.create(lead=lead, activity_type=LeadActivity.TYPE_CALL)
            self.assertEqual(lead_scoring._engagement_signal(lead), 100.0)

    def test_recency_signal_tiers_by_days_since_last_activity(self):
        with schema_context(self.tenant.schema_name):
            lead = _make_lead()
            Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - datetime.timedelta(days=20))
            lead.refresh_from_db()
            self.assertEqual(lead_scoring._recency_signal(lead), 10.0)  # stale, no activity at all

            activity = LeadActivity.objects.create(lead=lead, activity_type=LeadActivity.TYPE_CALL)
            LeadActivity.objects.filter(pk=activity.pk).update(created_at=timezone.now() - datetime.timedelta(days=2))
            self.assertEqual(lead_scoring._recency_signal(lead), 100.0)

            LeadActivity.objects.filter(pk=activity.pk).update(created_at=timezone.now() - datetime.timedelta(days=5))
            self.assertEqual(lead_scoring._recency_signal(lead), 70.0)

            LeadActivity.objects.filter(pk=activity.pk).update(created_at=timezone.now() - datetime.timedelta(days=10))
            self.assertEqual(lead_scoring._recency_signal(lead), 40.0)

    def test_completeness_signal_counts_filled_fields(self):
        with schema_context(self.tenant.schema_name):
            department = Department.objects.create(name="CS", code="CS1")
            bare_lead = _make_lead(email="bare@example.com")
            self.assertEqual(lead_scoring._completeness_signal(bare_lead), 0.0)

            full_lead = _make_lead(email="full@example.com", phone="9999999999", interested_department=department)
            self.assertAlmostEqual(lead_scoring._completeness_signal(full_lead), (2 / 3) * 100)

    def test_source_signal_uses_static_weights(self):
        with schema_context(self.tenant.schema_name):
            referral = _make_lead(email="referral@example.com", source=Lead.SOURCE_REFERRAL)
            website = _make_lead(email="website@example.com", source=Lead.SOURCE_WEBSITE)
            self.assertGreater(lead_scoring._source_signal(referral), lead_scoring._source_signal(website))

    def test_compute_priority_score_tier_thresholds(self):
        with schema_context(self.tenant.schema_name):
            lead = _make_lead(source=Lead.SOURCE_REFERRAL, phone="9999999999")
            for _ in range(6):
                LeadActivity.objects.create(lead=lead, activity_type=LeadActivity.TYPE_CALL)

            result = lead_scoring.compute_priority_score(lead)
            self.assertGreaterEqual(result["priority_score"], lead_scoring.TIER_HOT_THRESHOLD)
            self.assertEqual(result["priority_tier"], Lead.TIER_HOT)

    def test_cold_lead_with_no_signals(self):
        with schema_context(self.tenant.schema_name):
            lead = _make_lead(source=Lead.SOURCE_OTHER)
            Lead.objects.filter(pk=lead.pk).update(created_at=timezone.now() - datetime.timedelta(days=30))
            lead.refresh_from_db()

            result = lead_scoring.compute_priority_score(lead)
            self.assertEqual(result["priority_tier"], Lead.TIER_COLD)


class LeadStageTransitionTests(TenantTestCase):
    def test_happy_path_progression(self):
        with schema_context(self.tenant.schema_name):
            lead = _make_lead(email="ravi@example.com")
            lead.mark_contacted()
            self.assertEqual(lead.status, Lead.STATUS_CONTACTED)
            self.assertIsNotNone(lead.contacted_at)

            lead.submit_application()
            self.assertEqual(lead.status, Lead.STATUS_APPLICATION_SUBMITTED)

            lead.admit()
            self.assertEqual(lead.status, Lead.STATUS_ADMITTED)
            self.assertIsNotNone(lead.admitted_at)

    def test_cannot_skip_stages(self):
        with schema_context(self.tenant.schema_name):
            lead = _make_lead(email="ravi2@example.com")
            with self.assertRaises(ValueError):
                lead.submit_application()  # still inquiry, hasn't been contacted
            with self.assertRaises(ValueError):
                lead.admit()

    def test_close_from_any_active_status(self):
        with schema_context(self.tenant.schema_name):
            lead = _make_lead(email="ravi3@example.com")
            lead.close(Lead.STATUS_REJECTED, reason="Not eligible.")
            self.assertEqual(lead.status, Lead.STATUS_REJECTED)
            self.assertEqual(lead.close_reason, "Not eligible.")
            self.assertIsNotNone(lead.closed_at)

    def test_cannot_close_already_closed_lead(self):
        with schema_context(self.tenant.schema_name):
            lead = _make_lead(email="ravi4@example.com")
            lead.close(Lead.STATUS_WITHDRAWN)
            with self.assertRaises(ValueError):
                lead.close(Lead.STATUS_REJECTED)

    def test_close_rejects_invalid_outcome(self):
        with schema_context(self.tenant.schema_name):
            lead = _make_lead(email="ravi5@example.com")
            with self.assertRaises(ValueError):
                lead.close(Lead.STATUS_ADMITTED)


class AdmissionsAPITests(TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ("Management", "Faculty"):
                Group.objects.get_or_create(name=role)

            self.department = Department.objects.create(name="Computer Science", code="CSE")

            admin_user = User.objects.create_user(
                username="admissions_admin", email="admissions_admin@test.com", password="pw12345!",
            )
            admin_user.groups.add(Group.objects.get(name="Management"))
            self.admin_token = RefreshToken.for_user(admin_user)
            self.admin_token["tenant_schema"] = self.tenant.schema_name

            faculty_user = User.objects.create_user(
                username="plain_faculty2", email="plain_faculty2@test.com", password="pw12345!",
            )
            faculty_user.groups.add(Group.objects.get(name="Faculty"))
            self.faculty_token = RefreshToken.for_user(faculty_user)
            self.faculty_token["tenant_schema"] = self.tenant.schema_name

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

    def test_faculty_cannot_access_leads(self):
        response = self.client.get(reverse("lead-list"), **self._auth(self.faculty_token))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_create_lead_computes_initial_priority_score(self):
        response = self.client.post(
            reverse("lead-list"),
            {
                "first_name": "Priya", "last_name": "Shah", "email": "priya@example.com",
                "source": Lead.SOURCE_REFERRAL, "interested_department": self.department.id,
            },
            format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIsNotNone(response.data["priority_computed_at"])
        with schema_context(self.tenant.schema_name):
            lead = Lead.objects.get(pk=response.data["id"])
            self.assertGreater(lead.priority_score, 0)

    def test_logging_activity_rescoring_lead(self):
        with schema_context(self.tenant.schema_name):
            lead = Lead.objects.create(first_name="Kiran", last_name="Patel", email="kiran@example.com")
            initial_score = lead.priority_score

        response = self.client.post(
            reverse("leadactivity-list"),
            {"lead": lead.id, "activity_type": LeadActivity.TYPE_CALL, "notes": "First call."},
            format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        with schema_context(self.tenant.schema_name):
            lead.refresh_from_db()
            self.assertGreater(lead.priority_score, initial_score)

    def test_stage_transition_endpoints(self):
        with schema_context(self.tenant.schema_name):
            lead = Lead.objects.create(first_name="Neha", last_name="Joshi", email="neha@example.com")

        contacted = self.client.post(reverse("lead-mark-contacted", args=[lead.id]), **self._auth(self.admin_token))
        self.assertEqual(contacted.status_code, status.HTTP_200_OK)
        self.assertEqual(contacted.data["status"], Lead.STATUS_CONTACTED)

        # Wrong-stage transition is rejected, not silently applied.
        bad = self.client.post(reverse("lead-admit", args=[lead.id]), **self._auth(self.admin_token))
        self.assertEqual(bad.status_code, status.HTTP_400_BAD_REQUEST)

        submitted = self.client.post(reverse("lead-submit-application", args=[lead.id]), **self._auth(self.admin_token))
        self.assertEqual(submitted.status_code, status.HTTP_200_OK)

        admitted = self.client.post(reverse("lead-admit", args=[lead.id]), **self._auth(self.admin_token))
        self.assertEqual(admitted.status_code, status.HTTP_200_OK)
        self.assertEqual(admitted.data["status"], Lead.STATUS_ADMITTED)

    def test_close_endpoint(self):
        with schema_context(self.tenant.schema_name):
            lead = Lead.objects.create(first_name="Sam", last_name="Iyer", email="sam@example.com")

        response = self.client.post(
            reverse("lead-close", args=[lead.id]),
            {"outcome": "rejected", "reason": "Did not meet eligibility."},
            format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "rejected")

    def test_convert_requires_admitted_status(self):
        with schema_context(self.tenant.schema_name):
            lead = Lead.objects.create(
                first_name="Om", last_name="Desai", email="om@example.com",
                interested_department=self.department, guardian_email="guardian_om@example.com",
                guardian_name="Desai Sr.",
            )
        response = self.client.post(reverse("lead-convert", args=[lead.id]), **self._auth(self.admin_token))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_convert_requires_department_and_guardian_email(self):
        with schema_context(self.tenant.schema_name):
            lead = Lead.objects.create(
                first_name="No", last_name="Dept", email="nodept@example.com", status=Lead.STATUS_ADMITTED,
            )

        response = self.client.post(reverse("lead-convert", args=[lead.id]), **self._auth(self.admin_token))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("interested_department", response.data["error"])

    def test_convert_creates_student_guardian_and_consents(self):
        with schema_context(self.tenant.schema_name):
            lead = Lead.objects.create(
                first_name="Meera", last_name="Nair", email="meera_admitted@example.com",
                interested_department=self.department,
                guardian_name="Nair Sr.", guardian_email="guardian_meera@example.com", guardian_phone="9876543210",
                status=Lead.STATUS_ADMITTED,
            )

        response = self.client.post(
            reverse("lead-convert", args=[lead.id]),
            {"current_semester_year": "1", "section_division": "A"},
            format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["guardian"]["email"], "guardian_meera@example.com")

        with schema_context(self.tenant.schema_name):
            self.assertTrue(User.objects.filter(email="meera_admitted@example.com").exists())
            student = StudentProfile.objects.get(user__email="meera_admitted@example.com")
            self.assertEqual(student.department_id, self.department.id)
            self.assertEqual(student.consents.count(), 3)

            lead.refresh_from_db()
            self.assertEqual(lead.status, Lead.STATUS_ENROLLED)
            self.assertEqual(lead.converted_student_id, student.id)

    def test_convert_rejects_when_email_already_a_user(self):
        with schema_context(self.tenant.schema_name):
            User.objects.create_user(username="dupe", email="dupe@example.com", password="pw12345!")
            lead = Lead.objects.create(
                first_name="Dupe", last_name="Lead", email="dupe@example.com",
                interested_department=self.department, guardian_email="guardian_dupe@example.com",
                status=Lead.STATUS_ADMITTED,
            )
        response = self.client.post(reverse("lead-convert", args=[lead.id]), **self._auth(self.admin_token))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filter_leads_by_status(self):
        with schema_context(self.tenant.schema_name):
            Lead.objects.create(first_name="A", last_name="A", email="a@example.com", status=Lead.STATUS_INQUIRY)
            Lead.objects.create(first_name="B", last_name="B", email="b@example.com", status=Lead.STATUS_CONTACTED)

        response = self.client.get(
            reverse("lead-list"), {"status": Lead.STATUS_CONTACTED}, **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]["status"], Lead.STATUS_CONTACTED)

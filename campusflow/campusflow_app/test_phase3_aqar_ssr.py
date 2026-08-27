"""
Tests for Phase 3 of the compliance roadmap: AQAR/SSR content completeness
(closes remaining gaps in #1 AQAR, #2 SSR/DVV).

- FacultyResearchOutput: real publication/grant/patent records.
- StudentFeedback: filing open to any authenticated user, review/action
  gated to Faculty+, mirroring CommitteeComplaint's create-open-else-gated
  split (including that a filer can't browse their own submission back).
- InstitutionalEvent: logged-as-it-happens event records.
- AccreditationSubmission: IIQA / DVV clarification, reusing EvidenceItem's
  exact draft -> submitted -> signed_off workflow shape.
- AuditedFinancialsCoverageView: trailing-5-year missing-audit detection
  using only the existing certificate vault (no new model).
- A smoke test that build_naac_document() still renders with all five new
  sections populated, without raising.
"""
import datetime
import json

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Department, StudentProfile, TeachingStaffProfile
from .models.aqar_ssr import (
    AccreditationSubmission, FacultyResearchOutput, InstitutionalEvent, StudentFeedback,
)
from .models.compliance import ComplianceCertificate, ComplianceCertificateType
from .models.finance import FinancialYear
from .models.module_permissions import TenantModulePermission


class _Phase3FixtureMixin:
    def _build_fixture(self):
        self.tenant.subscribed_modules = ["compliance-center"]
        self.tenant.save(update_fields=["subscribed_modules"])

        for role in ("Administrator", "Faculty", "Department Head"):
            Group.objects.get_or_create(name=role)

        self.dept = Department.objects.create(name="Computer Science", code="CSE")

        admin_user = User.objects.create_user(username="admin1", password="pw12345!")
        admin_user.groups.add(Group.objects.get(name="Administrator"))

        faculty_user = User.objects.create_user(username="faculty1", password="pw12345!", first_name="Priya", last_name="Rao")
        faculty_user.groups.add(Group.objects.get(name="Faculty"))
        faculty_profile = TeachingStaffProfile.objects.create(
            user=faculty_user, employee_id="EMP001", department=self.dept,
        )

        hod_user = User.objects.create_user(username="hod1", password="pw12345!")
        hod_user.groups.add(Group.objects.get(name="Department Head"))
        # RequiresModule("compliance-center") checks per-role module grants,
        # not just tenant.subscribed_modules — a real College Admin would
        # explicitly grant this to Department Head before HOD sign-off works.
        TenantModulePermission.objects.update_or_create(
            group_name="Department Head", defaults={"allowed_modules": ["compliance-center"]},
        )

        student_user = User.objects.create_user(username="stu1", password="pw12345!")
        student_profile = StudentProfile.objects.create(user=student_user, student_id="STU001", department=self.dept)

        financial_year = FinancialYear.objects.create(
            label="2026-2027", start_date=datetime.date(2026, 4, 1), end_date=datetime.date(2027, 3, 31),
        )

        return {
            "admin_user": admin_user, "faculty_user": faculty_user, "faculty_profile": faculty_profile,
            "hod_user": hod_user, "student_user": student_user, "student_profile": student_profile,
            "financial_year": financial_year,
        }

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}


class FacultyResearchOutputTests(_Phase3FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_faculty_can_create_publication_record(self):
        response = self.client.post(
            reverse("facultyresearchoutput-list"),
            {
                "faculty": self.fixture["faculty_profile"].id,
                "financial_year": self.fixture["financial_year"].id,
                "output_type": "publication",
                "title": "Deep Learning for Signal Processing",
                "journal_or_venue": "IEEE Transactions",
                "is_peer_reviewed": True,
            },
            format="json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        with schema_context(self.tenant.schema_name):
            self.assertEqual(FacultyResearchOutput.objects.count(), 1)
            output = FacultyResearchOutput.objects.first()
            self.assertEqual(output.output_type, "publication")
            self.assertTrue(output.is_peer_reviewed)

    def test_plain_student_cannot_create_research_output(self):
        response = self.client.post(
            reverse("facultyresearchoutput-list"),
            {
                "faculty": self.fixture["faculty_profile"].id,
                "financial_year": self.fixture["financial_year"].id,
                "output_type": "patent",
                "title": "A Widget",
            },
            format="json", **self._auth(self.fixture["student_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class StudentFeedbackTests(_Phase3FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_student_can_file_feedback_and_it_links_their_profile(self):
        response = self.client.post(
            reverse("studentfeedback-list"),
            {
                "financial_year": self.fixture["financial_year"].id,
                "category": "Curriculum",
                "feedback_text": "More electives needed.",
            },
            format="json", **self._auth(self.fixture["student_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)

        with schema_context(self.tenant.schema_name):
            feedback = StudentFeedback.objects.get(pk=response.data["id"])
            self.assertEqual(feedback.student_id, self.fixture["student_profile"].id)
            self.assertEqual(feedback.status, StudentFeedback.STATUS_RECEIVED)

    def test_anonymous_feedback_has_no_student_link(self):
        response = self.client.post(
            reverse("studentfeedback-list"),
            {
                "financial_year": self.fixture["financial_year"].id,
                "is_anonymous": True,
                "feedback_text": "Anonymous complaint about mess food.",
            },
            format="json", **self._auth(self.fixture["student_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        with schema_context(self.tenant.schema_name):
            feedback = StudentFeedback.objects.get(pk=response.data["id"])
            self.assertIsNone(feedback.student_id)

    def test_student_cannot_list_feedback(self):
        response = self.client.get(
            reverse("studentfeedback-list"), **self._auth(self.fixture["student_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_faculty_can_record_action_taken(self):
        with schema_context(self.tenant.schema_name):
            feedback = StudentFeedback.objects.create(
                financial_year=self.fixture["financial_year"], feedback_text="Library hours too short.",
            )
        response = self.client.post(
            reverse("studentfeedback-record-action", args=[feedback.id]),
            json.dumps({"action_taken": "Extended library hours to 9pm."}),
            content_type="application/json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["status"], StudentFeedback.STATUS_ACTION_TAKEN)
        self.assertIsNotNone(response.data["action_taken_date"])

    def test_action_taken_report_counts_by_status(self):
        with schema_context(self.tenant.schema_name):
            StudentFeedback.objects.create(
                financial_year=self.fixture["financial_year"], feedback_text="A", status=StudentFeedback.STATUS_RECEIVED,
            )
            StudentFeedback.objects.create(
                financial_year=self.fixture["financial_year"], feedback_text="B", status=StudentFeedback.STATUS_CLOSED,
                action_taken="Resolved.",
            )
        response = self.client.get(
            reverse("compliance-center-student-feedback-report"),
            {"financial_year": self.fixture["financial_year"].id},
            **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["status_counts"]["received"], 1)
        self.assertEqual(response.data["status_counts"]["closed"], 1)
        self.assertEqual(response.data["total"], 2)


class InstitutionalEventTests(_Phase3FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_faculty_can_log_an_event(self):
        response = self.client.post(
            reverse("institutionalevent-list"),
            {
                "title": "AI Workshop",
                "event_type": "Workshop",
                "financial_year": self.fixture["financial_year"].id,
                "event_date": "2026-08-15",
                "participants_count": 40,
            },
            format="json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        with schema_context(self.tenant.schema_name):
            event = InstitutionalEvent.objects.get(pk=response.data["id"])
            self.assertEqual(event.created_by_id, self.fixture["faculty_user"].id)


class AccreditationSubmissionTests(_Phase3FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_faculty_cannot_create_accreditation_submission(self):
        response = self.client.post(
            reverse("accreditationsubmission-list"),
            {"submission_type": "iiqa", "financial_year": self.fixture["financial_year"].id},
            format="json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_full_draft_submit_signoff_lifecycle(self):
        create_response = self.client.post(
            reverse("accreditationsubmission-list"),
            {
                "submission_type": "dvv_clarification", "financial_year": self.fixture["financial_year"].id,
                "query_text": "Clarify Metric 3.4.2 publication count.",
                "content": "Publication count verified against Scopus IDs; revised list attached.",
            },
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(create_response.status_code, status.HTTP_201_CREATED, create_response.data)
        self.assertEqual(create_response.data["status"], "draft")
        submission_id = create_response.data["id"]

        submit_response = self.client.post(
            reverse("accreditationsubmission-submit", args=[submission_id]), **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(submit_response.status_code, status.HTTP_200_OK, submit_response.data)
        self.assertEqual(submit_response.data["status"], "submitted")

        # Faculty (not HM-or-above) cannot sign off.
        faculty_signoff = self.client.post(
            reverse("accreditationsubmission-sign-off", args=[submission_id]), **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(faculty_signoff.status_code, status.HTTP_403_FORBIDDEN)

        hod_signoff = self.client.post(
            reverse("accreditationsubmission-sign-off", args=[submission_id]), **self._auth(self.fixture["hod_user"]),
        )
        self.assertEqual(hod_signoff.status_code, status.HTTP_200_OK, hod_signoff.data)
        self.assertEqual(hod_signoff.data["status"], "signed_off")

        with schema_context(self.tenant.schema_name):
            submission = AccreditationSubmission.objects.get(pk=submission_id)
            self.assertEqual(submission.signed_off_by_id, self.fixture["hod_user"].id)
            self.assertIsNotNone(submission.signed_off_at)


class AuditedFinancialsCoverageTests(_Phase3FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_flags_missing_years_and_reports_covered_ones(self):
        with schema_context(self.tenant.schema_name):
            cert_type = ComplianceCertificateType.objects.create(name="Audited Financial Statement")
            covered_fy = self.fixture["financial_year"]
            missing_fy = FinancialYear.objects.create(
                label="2025-2026", start_date=datetime.date(2025, 4, 1), end_date=datetime.date(2026, 3, 31),
            )
            ComplianceCertificate.objects.create(
                certificate_type=cert_type, file="compliance_certificates/audit_2026.pdf",
                financial_year=covered_fy,
            )

        response = self.client.get(
            reverse("compliance-center-audited-financials-coverage"), **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        by_year = {y["financial_year_label"]: y for y in response.data["years"]}
        self.assertTrue(by_year["2026-2027"]["has_audited_statement"])
        self.assertFalse(by_year["2025-2026"]["has_audited_statement"])
        self.assertIn("2025-2026", response.data["missing_years"])
        self.assertFalse(response.data["fully_covered"])


class NAACDocumentBuildSmokeTests(_Phase3FixtureMixin, TenantTestCase):
    """Confirms build_naac_document() still renders end-to-end with all five
    new AQAR/SSR sections populated — a regression guard for the docx
    generator, not a content-correctness check (that's the section-level
    query logic already covered by the API tests above)."""

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_build_naac_document_with_all_new_sections_populated(self):
        from .services.naac_ssr_export import build_naac_document

        with schema_context(self.tenant.schema_name):
            FacultyResearchOutput.objects.create(
                faculty=self.fixture["faculty_profile"], financial_year=self.fixture["financial_year"],
                output_type="grant", title="Seed Grant", funding_agency="DST", grant_amount_lakhs=5,
            )
            StudentFeedback.objects.create(
                financial_year=self.fixture["financial_year"], feedback_text="Feedback", status="closed",
                action_taken="Done",
            )
            InstitutionalEvent.objects.create(
                title="Tech Fest", financial_year=self.fixture["financial_year"], event_date=datetime.date(2026, 8, 1),
            )
            AccreditationSubmission.objects.create(
                submission_type="iiqa", financial_year=self.fixture["financial_year"], content="IIQA content",
            )
            buffer = build_naac_document(financial_year=self.fixture["financial_year"])
            self.assertGreater(len(buffer.getvalue()), 0)

            ssr_buffer = build_naac_document(financial_year=None)
            self.assertGreater(len(ssr_buffer.getvalue()), 0)

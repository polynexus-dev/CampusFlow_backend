"""
Tests for the NATS apprenticeship layer (closes roadmap gap #15).

- ApprenticeshipContract: extends a selected PlacementApplication with
  employer/stipend/proof-of-employment details.
- StipendClaim: one row per month, pending -> approved/rejected +
  reviewed_by/reviewed_at, mirroring ResultCorrectionRequest/
  RevaluationRequest's shape.
- IsTPOStaffOrAbove: filing is open to the apprentice, approval is not —
  the one new permission this phase needed, since a plain "any tpo-module
  user" bar (like RecruitmentDriveViewSet's) would let an apprentice
  approve their own stipend.
"""
import datetime
import json

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models.apprenticeship import ApprenticeshipContract, StipendClaim
from .models.department import Department
from .models.profile import StudentProfile
from .models.tpo import PlacementApplication, RecruitmentDrive


class _Phase5FixtureMixin:
    def _build_fixture(self):
        self.tenant.subscribed_modules = ["tpo"]
        self.tenant.save(update_fields=["subscribed_modules"])

        for role in ("Placement Officer",):
            Group.objects.get_or_create(name=role)
        student_group, _ = Group.objects.get_or_create(name="student")

        self.dept = Department.objects.create(name="Computer Science", code="CSE")

        student_user = User.objects.create_user(username="stu1", password="pw12345!", email="stu1@test.com")
        student_user.groups.add(student_group)
        self.student = StudentProfile.objects.create(user=student_user, student_id="STU001", department=self.dept)

        other_student_user = User.objects.create_user(username="stu2", password="pw12345!", email="stu2@test.com")
        other_student_user.groups.add(student_group)
        self.other_student = StudentProfile.objects.create(
            user=other_student_user, student_id="STU002", department=self.dept,
        )

        po_user = User.objects.create_user(username="po1", password="pw12345!")
        po_user.groups.add(Group.objects.get(name="Placement Officer"))
        self.po_user = po_user

        drive = RecruitmentDrive.objects.create(
            company_name="Acme Corp", job_title="Apprentice Engineer",
            package_lpa=4, drive_date=datetime.date(2026, 6, 1), status="Completed",
        )
        self.application = PlacementApplication.objects.create(
            drive=drive, student=self.student, status="Selected",
        )
        self.contract = ApprenticeshipContract.objects.create(
            placement_application=self.application, employer_name="Acme Corp",
            start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2027, 6, 30),
            monthly_stipend_amount=15000,
        )

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}


class ApprenticeshipContractTests(_Phase5FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build_fixture()

    def test_po_can_create_contract_for_a_selected_application(self):
        with schema_context(self.tenant.schema_name):
            drive2 = RecruitmentDrive.objects.create(
                company_name="Beta Ltd", job_title="Intern", package_lpa=3,
                drive_date=datetime.date(2026, 6, 15), status="Completed",
            )
            application2 = PlacementApplication.objects.create(
                drive=drive2, student=self.other_student, status="Selected",
            )

        response = self.client.post(
            reverse("apprenticeshipcontract-list"),
            {
                "placement_application": application2.id, "employer_name": "Beta Ltd",
                "start_date": "2026-08-01", "end_date": "2027-07-31", "monthly_stipend_amount": 12000,
            },
            format="json", **self._auth(self.po_user),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        with schema_context(self.tenant.schema_name):
            self.assertEqual(ApprenticeshipContract.objects.count(), 2)


class StipendClaimTests(_Phase5FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build_fixture()

    def test_apprentice_files_claim_for_own_contract(self):
        response = self.client.post(
            reverse("stipendclaim-create"),
            {"contract_id": self.contract.id, "month": 7, "year": 2026, "claimed_amount": 15000, "attendance_percent": 95},
            format="json", **self._auth(self.student.user),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["status"], "pending")

        with schema_context(self.tenant.schema_name):
            self.assertEqual(StipendClaim.objects.count(), 1)

    def test_duplicate_month_claim_is_rejected(self):
        with schema_context(self.tenant.schema_name):
            StipendClaim.objects.create(contract=self.contract, month=7, year=2026, claimed_amount=15000)

        response = self.client.post(
            reverse("stipendclaim-create"),
            {"contract_id": self.contract.id, "month": 7, "year": 2026, "claimed_amount": 15000},
            format="json", **self._auth(self.student.user),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_cannot_file_claim_for_someone_elses_contract(self):
        response = self.client.post(
            reverse("stipendclaim-create"),
            {"contract_id": self.contract.id, "month": 8, "year": 2026, "claimed_amount": 15000},
            format="json", **self._auth(self.other_student.user),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_placement_officer_can_approve_but_student_cannot(self):
        with schema_context(self.tenant.schema_name):
            claim = StipendClaim.objects.create(contract=self.contract, month=7, year=2026, claimed_amount=15000)

        student_attempt = self.client.post(
            reverse("stipendclaim-action", args=[claim.id]),
            json.dumps({"action": "approve"}),
            content_type="application/json", **self._auth(self.student.user),
        )
        self.assertEqual(student_attempt.status_code, status.HTTP_403_FORBIDDEN)

        po_response = self.client.post(
            reverse("stipendclaim-action", args=[claim.id]),
            json.dumps({"action": "approve"}),
            content_type="application/json", **self._auth(self.po_user),
        )
        self.assertEqual(po_response.status_code, status.HTTP_200_OK, po_response.data)
        self.assertEqual(po_response.data["status"], "approved")

        with schema_context(self.tenant.schema_name):
            claim.refresh_from_db()
            self.assertEqual(claim.reviewed_by_id, self.po_user.id)
            self.assertIsNotNone(claim.reviewed_at)

    def test_pending_list_only_shows_placement_officer(self):
        with schema_context(self.tenant.schema_name):
            StipendClaim.objects.create(contract=self.contract, month=7, year=2026, claimed_amount=15000)

        student_attempt = self.client.get(
            reverse("stipendclaim-list"), **self._auth(self.student.user),
        )
        self.assertEqual(student_attempt.status_code, status.HTTP_403_FORBIDDEN)

        po_response = self.client.get(reverse("stipendclaim-list"), **self._auth(self.po_user))
        self.assertEqual(po_response.status_code, status.HTTP_200_OK, po_response.data)
        self.assertEqual(len(po_response.data["results"]), 1)

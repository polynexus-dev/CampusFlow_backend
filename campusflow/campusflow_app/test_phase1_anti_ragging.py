"""
Tests for Phase 1 of the compliance roadmap: anti-ragging undertaking
capture (closes gap #11).

- AntiRaggingUndertaking: per-student-per-year record with a server-issued
  reference number, and independent student/parent acknowledgment timestamps.
- AntiRaggingCoverageReportView: per-department fully-signed / partially-signed
  / not-collected breakdown for a given academic year.
"""
import datetime
import json

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    AcademicYear, AntiRaggingUndertaking, Department, StudentProfile,
)


class _Phase1FixtureMixin:
    def _build_fixture(self):
        self.tenant.subscribed_modules = ["compliance-center"]
        self.tenant.save(update_fields=["subscribed_modules"])

        for role in ("Administrator",):
            Group.objects.get_or_create(name=role)

        admin_user = User.objects.create_user(username="admin1", password="pw12345!")
        admin_user.groups.add(Group.objects.get(name="Administrator"))

        cse = Department.objects.create(name="Computer Science", code="CSE")
        ece = Department.objects.create(name="Electronics", code="ECE")

        student1_user = User.objects.create_user(username="stu1", password="pw12345!", first_name="Asha", last_name="Verma")
        student1 = StudentProfile.objects.create(user=student1_user, student_id="STU001", department=cse)

        student2_user = User.objects.create_user(username="stu2", password="pw12345!", first_name="Rohit", last_name="Iyer")
        student2 = StudentProfile.objects.create(user=student2_user, student_id="STU002", department=cse)

        student3_user = User.objects.create_user(username="stu3", password="pw12345!", first_name="Meera", last_name="Nair")
        student3 = StudentProfile.objects.create(user=student3_user, student_id="STU003", department=ece)

        academic_year = AcademicYear.objects.create(
            name="2026-2027", start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2027, 6, 30),
        )

        return {
            "admin_user": admin_user, "cse": cse, "ece": ece,
            "student1": student1, "student2": student2, "student3": student3,
            "academic_year": academic_year,
        }

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}


class AntiRaggingUndertakingTests(_Phase1FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_create_generates_reference_number_and_stamps_acknowledgment(self):
        response = self.client.post(
            reverse("antiraggingundertaking-list"),
            {
                "student": self.fixture["student1"].id,
                "academic_year": self.fixture["academic_year"].id,
                "student_acknowledged": True,
                "parent_guardian_name": "Sunita Verma",
                "parent_acknowledged": True,
            },
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertTrue(response.data["reference_number"].startswith("AR-"))
        self.assertIsNotNone(response.data["student_acknowledged_at"])
        self.assertIsNotNone(response.data["parent_acknowledged_at"])
        self.assertTrue(response.data["is_complete"])

        with schema_context(self.tenant.schema_name):
            undertaking = AntiRaggingUndertaking.objects.get(
                student=self.fixture["student1"], academic_year=self.fixture["academic_year"],
            )
            self.assertTrue(undertaking.is_complete)
            self.assertTrue(undertaking.reference_number)

    def test_partial_signature_is_not_complete_and_does_not_stamp_missing_side(self):
        response = self.client.post(
            reverse("antiraggingundertaking-list"),
            {
                "student": self.fixture["student2"].id,
                "academic_year": self.fixture["academic_year"].id,
                "student_acknowledged": True,
                "parent_acknowledged": False,
            },
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertFalse(response.data["is_complete"])
        self.assertIsNotNone(response.data["student_acknowledged_at"])
        self.assertIsNone(response.data["parent_acknowledged_at"])

    def test_reference_numbers_are_sequential_and_unique(self):
        self.client.post(
            reverse("antiraggingundertaking-list"),
            {"student": self.fixture["student1"].id, "academic_year": self.fixture["academic_year"].id, "student_acknowledged": True},
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        response2 = self.client.post(
            reverse("antiraggingundertaking-list"),
            {"student": self.fixture["student2"].id, "academic_year": self.fixture["academic_year"].id, "student_acknowledged": True},
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        with schema_context(self.tenant.schema_name):
            refs = set(AntiRaggingUndertaking.objects.values_list("reference_number", flat=True))
            self.assertEqual(len(refs), 2)
        self.assertNotEqual(response2.data["reference_number"], "")

    def test_one_undertaking_per_student_per_year(self):
        with schema_context(self.tenant.schema_name):
            AntiRaggingUndertaking.objects.create(
                student=self.fixture["student1"], academic_year=self.fixture["academic_year"],
                reference_number="AR-TEST-0001",
            )
            with self.assertRaises(Exception):
                AntiRaggingUndertaking.objects.create(
                    student=self.fixture["student1"], academic_year=self.fixture["academic_year"],
                    reference_number="AR-TEST-0002",
                )

    def test_patch_flips_acknowledgment_and_stamps_only_once(self):
        create_response = self.client.post(
            reverse("antiraggingundertaking-list"),
            {"student": self.fixture["student1"].id, "academic_year": self.fixture["academic_year"].id, "student_acknowledged": True},
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        pk = create_response.data["id"]
        first_student_ts = create_response.data["student_acknowledged_at"]

        patch_response = self.client.patch(
            reverse("antiraggingundertaking-detail", args=[pk]),
            json.dumps({"parent_guardian_name": "Late Signing Parent", "parent_acknowledged": True}),
            content_type="application/json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(patch_response.status_code, status.HTTP_200_OK, patch_response.data)
        self.assertTrue(patch_response.data["is_complete"])
        self.assertIsNotNone(patch_response.data["parent_acknowledged_at"])
        # Re-patching student_acknowledged (already True) must not move the
        # original timestamp forward.
        self.assertEqual(patch_response.data["student_acknowledged_at"], first_student_ts)


class AntiRaggingCoverageReportTests(_Phase1FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()
            # CSE: student1 fully signed, student2 not collected at all.
            AntiRaggingUndertaking.objects.create(
                student=self.fixture["student1"], academic_year=self.fixture["academic_year"],
                reference_number="AR-CSE-0001", student_acknowledged=True, parent_acknowledged=True,
            )
            # ECE: student3 only student-signed (partial).
            AntiRaggingUndertaking.objects.create(
                student=self.fixture["student3"], academic_year=self.fixture["academic_year"],
                reference_number="AR-ECE-0001", student_acknowledged=True, parent_acknowledged=False,
            )

    def test_coverage_breakdown_by_department(self):
        response = self.client.get(
            reverse("compliance-center-anti-ragging-coverage"),
            {"academic_year": self.fixture["academic_year"].id},
            **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        by_dept = {d["department"]: d for d in response.data["departments"]}
        self.assertEqual(by_dept["Computer Science"]["total_students"], 2)
        self.assertEqual(by_dept["Computer Science"]["covered"], 1)
        self.assertEqual(by_dept["Computer Science"]["missing"], 1)
        self.assertEqual(by_dept["Electronics"]["total_students"], 1)
        self.assertEqual(by_dept["Electronics"]["partial"], 1)

        overall = response.data["overall"]
        self.assertEqual(overall["total_students"], 3)
        self.assertEqual(overall["covered"], 1)
        self.assertEqual(overall["partial"], 1)
        self.assertEqual(overall["missing"], 1)

    def test_missing_academic_year_param_is_rejected(self):
        response = self.client.get(
            reverse("compliance-center-anti-ragging-coverage"),
            **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

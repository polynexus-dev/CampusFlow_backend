"""
Tests for Phase 0 of the compliance roadmap: foundational field completeness.

- TeachingStaffProfile.aicte_faculty_id / aicte_cadre + AICTEDisclosureView's
  cadre-wise breakdown (closes a gap in AICTE EOA / Mandatory Disclosure).
- InstitutionProfile.aishe_code, surfaced on the AISHE annual return.
- Payslip's own pf/esi/tds snapshot, and the fix to PayrollStatutorySummaryView
  so it sums actual historical Payslip amounts instead of re-deriving
  current-rate x months-paid (which silently misstates any FY with a
  mid-year pay change).
- StatutoryCommittee's new SC/ST, OBC, minority, and women's cell types.
"""

import datetime

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    AuditEngagement, AuditorProfile, Department, FinancialYear,
    InstitutionProfile, Payslip, SalaryStructure, StatutoryCommittee,
    TeachingStaffProfile, AcademicYear,
)


class _Phase0FixtureMixin:
    def _build_fixture(self):
        self.tenant.subscribed_modules = ["compliance-center", "audit-portal", "payroll"]
        self.tenant.save(update_fields=["subscribed_modules"])

        department = Department.objects.create(name="Computer Science", code="CSE")

        for role in ("Administrator", "CA"):
            Group.objects.get_or_create(name=role)

        admin_user = User.objects.create_user(username="admin1", password="pw12345!")
        admin_user.groups.add(Group.objects.get(name="Administrator"))

        faculty_user = User.objects.create_user(username="prof1", password="pw12345!", first_name="Priya", last_name="Rao")
        faculty = TeachingStaffProfile.objects.create(
            user=faculty_user, employee_id="EMP001", department=department,
            designation="Professor", aicte_faculty_id="AICTE-F-001",
            aicte_cadre=TeachingStaffProfile.CADRE_PROFESSOR,
        )

        assistant_user = User.objects.create_user(username="asst1", password="pw12345!", first_name="Ravi", last_name="Nair")
        assistant = TeachingStaffProfile.objects.create(
            user=assistant_user, employee_id="EMP002", department=department,
            designation="Assistant Professor", aicte_cadre=TeachingStaffProfile.CADRE_ASSISTANT_PROFESSOR,
        )

        academic_year = AcademicYear.objects.create(
            name="2026-2027", start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2027, 6, 30),
        )

        return {
            "department": department, "admin_user": admin_user,
            "faculty_user": faculty_user, "faculty": faculty,
            "assistant_user": assistant_user, "assistant": assistant,
            "academic_year": academic_year,
        }

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}


class AICTEFacultyFieldsTests(_Phase0FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_aicte_disclosure_includes_faculty_id_and_cadre_breakdown(self):
        response = self.client.get(reverse("compliance-center-aicte"), **self._auth(self.fixture["admin_user"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        faculty_by_employee_id = {f["employee_id"]: f for f in response.data["faculty"]}
        self.assertEqual(faculty_by_employee_id["EMP001"]["aicte_faculty_id"], "AICTE-F-001")
        self.assertEqual(faculty_by_employee_id["EMP001"]["aicte_cadre"], "Professor")
        self.assertIsNone(faculty_by_employee_id["EMP002"]["aicte_faculty_id"])

        cadre_counts = response.data["cadre_wise_faculty_count"]
        self.assertEqual(cadre_counts["Professor"], 1)
        self.assertEqual(cadre_counts["Assistant Professor"], 1)
        self.assertEqual(cadre_counts["Associate Professor"], 0)

    def test_aicte_faculty_id_is_unique(self):
        with schema_context(self.tenant.schema_name):
            dup_user = User.objects.create_user(username="prof2", password="pw12345!")
            with self.assertRaises(Exception):
                TeachingStaffProfile.objects.create(
                    user=dup_user, employee_id="EMP003",
                    aicte_faculty_id="AICTE-F-001",  # duplicate of fixture's faculty
                )


class InstitutionProfileTests(_Phase0FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_get_or_create_singleton(self):
        with schema_context(self.tenant.schema_name):
            profile1 = InstitutionProfile.objects.get_or_create(pk=1)[0]
            profile2 = InstitutionProfile.objects.get_or_create(pk=1)[0]
            self.assertEqual(profile1.id, profile2.id)

    def test_set_and_read_aishe_code(self):
        import json
        response = self.client.patch(
            reverse("compliance-center-institution-profile"), json.dumps({"aishe_code": "C-12345"}),
            content_type="application/json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["aishe_code"], "C-12345")

        response = self.client.get(reverse("compliance-center-aishe"), **self._auth(self.fixture["admin_user"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["aishe_code"], "C-12345")


class PayslipStatutorySplitTests(_Phase0FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_generate_payslip_snapshots_pf_esi_tds(self):
        with schema_context(self.tenant.schema_name):
            SalaryStructure.objects.create(
                user=self.fixture["faculty_user"], basic_pay=50000,
                pf_deduction=1800, esi_deduction=400, tds_deduction=2000,
            )

        response = self.client.post(
            reverse("generate-payslip"),
            {"user_id": self.fixture["faculty_user"].id, "month": 7, "year": 2026},
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        with schema_context(self.tenant.schema_name):
            payslip = Payslip.objects.get(user=self.fixture["faculty_user"], month=7, year=2026)
            self.assertEqual(payslip.pf_deduction, 1800)
            self.assertEqual(payslip.esi_deduction, 400)
            self.assertEqual(payslip.tds_deduction, 2000)

    def test_statutory_summary_uses_historical_payslip_amounts_not_current_rate(self):
        """
        The bug this closes: multiplying the *current* SalaryStructure rate by
        months-paid silently misstates any FY where pay changed mid-year. Here
        the employee is paid Rs. 1800 PF in month 1, then gets a raise to
        Rs. 2200 PF before month 2's payslip. The correct FY total is
        1800 + 2200 = 4000 — never 2 x 2200 (the old buggy formula) or
        2 x 1800.
        """
        with schema_context(self.tenant.schema_name):
            fy = FinancialYear.objects.create(
                label="2026-2027", start_date=datetime.date(2026, 4, 1), end_date=datetime.date(2027, 3, 31),
            )
            salary = SalaryStructure.objects.create(
                user=self.fixture["faculty_user"], basic_pay=50000,
                pf_deduction=1800, esi_deduction=400, tds_deduction=2000,
            )

        self.client.post(
            reverse("generate-payslip"),
            {"user_id": self.fixture["faculty_user"].id, "month": 4, "year": 2026},
            format="json", **self._auth(self.fixture["admin_user"]),
        )

        with schema_context(self.tenant.schema_name):
            salary.pf_deduction = 2200
            salary.save(update_fields=["pf_deduction"])

        self.client.post(
            reverse("generate-payslip"),
            {"user_id": self.fixture["faculty_user"].id, "month": 5, "year": 2026},
            format="json", **self._auth(self.fixture["admin_user"]),
        )

        with schema_context(self.tenant.schema_name):
            auditor_user = User.objects.create_user(username="ca_user1", password="pw12345!")
            auditor_user.groups.add(Group.objects.get(name="CA"))
            auditor_profile = AuditorProfile.objects.create(user=auditor_user, firm_name="Test & Co")
            AuditEngagement.objects.create(
                auditor=auditor_profile, financial_year=fy,
                access_start=datetime.date.today() - datetime.timedelta(days=1),
                access_end=datetime.date.today() + datetime.timedelta(days=30),
            )

        response = self.client.get(
            reverse("audit-portal-payroll-statutory-summary"),
            {"financial_year": fy.id}, **self._auth(auditor_user),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(float(response.data["totals"]["pf"]), 4000.0)
        self.assertEqual(response.data["employees"][0]["months_paid"], 2)


class StatutoryCommitteeNewTypesTests(_Phase0FixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_can_create_committee_with_each_new_type(self):
        with schema_context(self.tenant.schema_name):
            for committee_type in [
                StatutoryCommittee.TYPE_SC_ST_CELL,
                StatutoryCommittee.TYPE_OBC_CELL,
                StatutoryCommittee.TYPE_MINORITY_CELL,
                StatutoryCommittee.TYPE_WOMENS_CELL,
            ]:
                committee = StatutoryCommittee.objects.create(
                    committee_type=committee_type,
                    academic_year=self.fixture["academic_year"],
                    formed_date=datetime.date(2026, 7, 1),
                )
                self.assertEqual(committee.committee_type, committee_type)

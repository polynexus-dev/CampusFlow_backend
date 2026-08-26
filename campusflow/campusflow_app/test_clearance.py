"""
Tests for the Clearance (No-Dues) workflow: models/clearance.py,
services/clearance.py, and views/clearance.py.
"""

import datetime

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    AcademicYear, ClearanceDesk, ClearanceItem, ClearanceRequest, ClearanceSettings,
    Department, PromotionRecord, StudentProfile, Term,
)
from .services.academics import set_current_term
from .services.clearance import is_student_cleared


class _ClearanceFixtureMixin:
    def _build_fixture(self):
        # "clearance" is a PREMIUM_MODULES entry, so a fresh tenant must opt
        # in explicitly, same as every other premium module in this suite.
        self.tenant.subscribed_modules = ["clearance", "exams"]
        self.tenant.save(update_fields=["subscribed_modules"])

        department = Department.objects.create(name="Computer Science", code="CSE")

        academic_year = AcademicYear.objects.create(
            name="2026-2027", start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2027, 6, 30),
        )
        today = datetime.date.today()
        term = Term.objects.create(
            academic_year=academic_year, name="Odd Semester", kind=Term.KIND_ODD, sequence=1,
            start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=90),
        )
        set_current_term(term)

        for role in ("Management", "Administrator", "Librarian", "Fee Counter"):
            Group.objects.get_or_create(name=role)

        admin_user = User.objects.create_user(username="admin1", password="pw12345!")
        admin_user.groups.add(Group.objects.get(name="Administrator"))

        librarian_user = User.objects.create_user(username="librarian1", password="pw12345!")
        librarian_user.groups.add(Group.objects.get(name="Librarian"))

        fee_counter_user = User.objects.create_user(username="feecounter1", password="pw12345!")
        fee_counter_user.groups.add(Group.objects.get(name="Fee Counter"))

        Group.objects.get_or_create(name="student")
        student_user = User.objects.create_user(username="student1", password="pw12345!")
        student_user.groups.add(Group.objects.get(name="student"))
        student = StudentProfile.objects.create(
            user=student_user, student_id="CSE001", department=department, academic_status="active",
        )

        library_desk = ClearanceDesk.objects.create(
            name="Library", code="library", responsible_group=Group.objects.get(name="Librarian"),
            linked_module="library", order=1,
        )
        fees_desk = ClearanceDesk.objects.create(
            name="Fees", code="fees", responsible_group=Group.objects.get(name="Fee Counter"),
            linked_module="fees", order=2,
        )

        return {
            "department": department, "term": term, "academic_year": academic_year,
            "admin_user": admin_user, "librarian_user": librarian_user, "fee_counter_user": fee_counter_user,
            "student_user": student_user, "student": student,
            "library_desk": library_desk, "fees_desk": fees_desk,
        }

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}


class ClearanceModelTests(_ClearanceFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_no_active_desks_means_not_gated(self):
        with schema_context(self.tenant.schema_name):
            ClearanceDesk.objects.all().delete()
            is_cleared, request_obj = is_student_cleared(self.fixture["student"])
            self.assertTrue(is_cleared)
            self.assertIsNone(request_obj)

    def test_no_request_yet_means_not_cleared(self):
        with schema_context(self.tenant.schema_name):
            is_cleared, request_obj = is_student_cleared(self.fixture["student"])
            self.assertFalse(is_cleared)
            self.assertIsNone(request_obj)

    def test_status_aggregation_all_cleared(self):
        with schema_context(self.tenant.schema_name):
            req = ClearanceRequest.objects.create(student=self.fixture["student"], term=self.fixture["term"])
            item1 = ClearanceItem.objects.create(request=req, desk=self.fixture["library_desk"])
            item2 = ClearanceItem.objects.create(request=req, desk=self.fixture["fees_desk"])

            item1.status = ClearanceItem.STATUS_CLEARED
            item1.save(update_fields=["status"])
            req.recompute_status()
            req.refresh_from_db()
            self.assertEqual(req.status, ClearanceRequest.STATUS_PENDING)

            item2.status = ClearanceItem.STATUS_CLEARED
            item2.save(update_fields=["status"])
            req.recompute_status()
            req.refresh_from_db()
            self.assertEqual(req.status, ClearanceRequest.STATUS_CLEARED)
            self.assertIsNotNone(req.completed_at)

    def test_status_aggregation_any_rejected_wins(self):
        with schema_context(self.tenant.schema_name):
            req = ClearanceRequest.objects.create(student=self.fixture["student"], term=self.fixture["term"])
            item1 = ClearanceItem.objects.create(
                request=req, desk=self.fixture["library_desk"], status=ClearanceItem.STATUS_CLEARED,
            )
            ClearanceItem.objects.create(
                request=req, desk=self.fixture["fees_desk"], status=ClearanceItem.STATUS_REJECTED,
            )
            req.recompute_status()
            req.refresh_from_db()
            self.assertEqual(req.status, ClearanceRequest.STATUS_REJECTED)


class ClearanceAPITests(_ClearanceFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_desk_crud_is_admin_only(self):
        response = self.client.post(
            reverse("clearance-desk-list"),
            {"name": "Hostel", "code": "hostel", "responsible_group": "Librarian", "linked_module": "hostel"},
            format="json", **self._auth(self.fixture["librarian_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.post(
            reverse("clearance-desk-list"),
            {"name": "Hostel", "code": "hostel", "responsible_group": "Librarian", "linked_module": "hostel"},
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_deleting_a_desk_with_history_soft_deactivates_instead_of_erroring(self):
        self.client.post(
            reverse("clearance-bulk-generate"), {"term_id": self.fixture["term"].id},
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        library_desk_id = self.fixture["library_desk"].id

        response = self.client.delete(
            reverse("clearance-desk-detail", args=[library_desk_id]), **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        with schema_context(self.tenant.schema_name):
            desk = ClearanceDesk.objects.get(id=library_desk_id)
            self.assertFalse(desk.is_active)
            # The desk row and its historical ClearanceItem link both survive.
            self.assertTrue(ClearanceItem.objects.filter(desk=desk).exists())

    def test_bulk_generate_creates_one_request_per_active_desk_and_is_idempotent(self):
        response = self.client.post(
            reverse("clearance-bulk-generate"),
            {"term_id": self.fixture["term"].id},
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["created"], 1)

        with schema_context(self.tenant.schema_name):
            req = ClearanceRequest.objects.get(student=self.fixture["student"], term=self.fixture["term"])
            self.assertEqual(req.items.count(), 2)

        response = self.client.post(
            reverse("clearance-bulk-generate"),
            {"term_id": self.fixture["term"].id},
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.data["created"], 0)
        self.assertEqual(response.data["skipped_existing"], 1)

    def test_desk_owner_can_clear_own_desk_only(self):
        self.client.post(
            reverse("clearance-bulk-generate"), {"term_id": self.fixture["term"].id},
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        with schema_context(self.tenant.schema_name):
            req = ClearanceRequest.objects.get(student=self.fixture["student"], term=self.fixture["term"])
            fees_item = req.items.get(desk=self.fixture["fees_desk"])
            library_item = req.items.get(desk=self.fixture["library_desk"])

        # Librarian cannot clear the Fees item.
        response = self.client.post(
            reverse("clearance-item-clear", args=[fees_item.id]),
            {}, format="json", **self._auth(self.fixture["librarian_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        # Librarian can clear the Library item.
        response = self.client.post(
            reverse("clearance-item-clear", args=[library_item.id]),
            {}, format="json", **self._auth(self.fixture["librarian_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], ClearanceItem.STATUS_CLEARED)

        # College Admin can override and clear the Fees item too.
        response = self.client.post(
            reverse("clearance-item-clear", args=[fees_item.id]),
            {}, format="json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        with schema_context(self.tenant.schema_name):
            req.refresh_from_db()
            self.assertEqual(req.status, ClearanceRequest.STATUS_CLEARED)

    def test_reject_requires_remarks(self):
        self.client.post(
            reverse("clearance-bulk-generate"), {"term_id": self.fixture["term"].id},
            format="json", **self._auth(self.fixture["admin_user"]),
        )
        with schema_context(self.tenant.schema_name):
            req = ClearanceRequest.objects.get(student=self.fixture["student"], term=self.fixture["term"])
            library_item = req.items.get(desk=self.fixture["library_desk"])

        response = self.client.post(
            reverse("clearance-item-reject", args=[library_item.id]),
            {}, format="json", **self._auth(self.fixture["librarian_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.post(
            reverse("clearance-item-reject", args=[library_item.id]),
            {"remarks": "Book not returned"}, format="json", **self._auth(self.fixture["librarian_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_promotion_blocked_until_cleared_then_override_works(self):
        student = self.fixture["student"]
        student.current_semester_year = "Semester 1"
        student.section_division = ""
        student.save(update_fields=["current_semester_year", "section_division"])

        self.client.post(
            reverse("clearance-bulk-generate"), {"term_id": self.fixture["term"].id},
            format="json", **self._auth(self.fixture["admin_user"]),
        )

        payload = {
            "department_id": self.fixture["department"].id,
            "from_semester_year": "Semester 1", "to_semester_year": "Semester 2",
        }
        response = self.client.post(
            reverse("students-promote"), payload, format="json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertIn(student.id, response.data["blocked_student_ids"])

        override_payload = dict(payload, override=True, override_reason="Manual clearance done offline")
        response = self.client.post(
            reverse("students-promote"), override_payload, format="json", **self._auth(self.fixture["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        with schema_context(self.tenant.schema_name):
            record = PromotionRecord.objects.get(student=student)
            self.assertEqual(record.override_reason, "Manual clearance done offline")

    def test_certificate_only_available_once_final_exit_fully_cleared(self):
        response = self.client.get(
            reverse("clearance-student-certificate", args=[self.fixture["student"].id]),
            **self._auth(self.fixture["student_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.post(
            reverse("clearance-final-exit-request"), {}, format="json",
            **self._auth(self.fixture["student_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        with schema_context(self.tenant.schema_name):
            req = ClearanceRequest.objects.get(
                student=self.fixture["student"], cycle_type=ClearanceRequest.CYCLE_FINAL_EXIT,
            )
            items = list(req.items.all())

        for item in items:
            self.client.post(
                reverse("clearance-item-clear", args=[item.id]), {}, format="json",
                **self._auth(self.fixture["admin_user"]),
            )

        response = self.client.get(
            reverse("clearance-student-certificate", args=[self.fixture["student"].id]),
            **self._auth(self.fixture["student_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["desks"]), 2)

        # The self-service "me" endpoint returns the same thing without the
        # caller needing to know their own StudentProfile id.
        response = self.client.get(reverse("clearance-my-certificate"), **self._auth(self.fixture["student_user"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["desks"]), 2)

    def test_my_status_endpoint_is_student_only(self):
        response = self.client.get(reverse("clearance-my-status"), **self._auth(self.fixture["admin_user"]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get(reverse("clearance-my-status"), **self._auth(self.fixture["student_user"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_cleared"])

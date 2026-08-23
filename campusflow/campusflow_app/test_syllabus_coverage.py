"""
Tests for the Syllabus Coverage Tracking feature (Phase 1): the
SyllabusCoverageEntry model and the three views in views/syllabus_coverage.py.
"""

import datetime

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    AcademicYear, Batch, Course, CourseOffering, Department, Program,
    Regulation, SyllabusCoverageEntry, SyllabusTopic, Term,
)


class _CoverageFixtureMixin:
    def _build_fixture(self):
        # "syllabus-tracker" is registered as a PREMIUM_MODULES entry
        # (views/module_permissions.py) — RequiresModule blocks every role,
        # including Faculty/HOD's own ROLE_DEFAULT_MODULES entry, unless the
        # tenant has actually subscribed to it. A fresh TenantTestCase tenant
        # starts unsubscribed, so tests need to opt in explicitly, the same
        # way a real tenant would via TenantSubscriptionView.
        self.tenant.subscribed_modules = ["syllabus-tracker"]
        self.tenant.save(update_fields=["subscribed_modules"])

        department = Department.objects.create(name="Computer Science", code="CSE")
        course = Course.objects.create(course_code="CS301", course_name="Data Structures", department=department)
        topics = [
            SyllabusTopic.objects.create(course=course, name=f"Unit {i}", order=i)
            for i in range(1, 5)
        ]

        academic_year = AcademicYear.objects.create(
            name="2026-2027", start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2027, 6, 30),
            is_current=True,
        )
        today = datetime.date.today()
        term = Term.objects.create(
            academic_year=academic_year, name="Odd Semester", kind=Term.KIND_ODD, sequence=1,
            start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=90),
            is_current=True,
        )
        program = Program.objects.create(name="B.Tech CSE", code="BTCSE", department=department)
        regulation = Regulation.objects.create(program=program, code="R2026", effective_from_year=2026)
        batch = Batch.objects.create(program=program, regulation=regulation, admission_year=2026, name="2026-2030")

        for role in ("Management", "Administrator", "Department Head", "Faculty"):
            Group.objects.get_or_create(name=role)

        hod_user = User.objects.create_user(username="hod_cse", password="pw12345!")
        hod_user.groups.add(Group.objects.get(name="Department Head"))
        department.hod = hod_user
        department.save(update_fields=["hod"])

        faculty_user = User.objects.create_user(username="faculty_a", password="pw12345!")
        faculty_user.groups.add(Group.objects.get(name="Faculty"))

        other_faculty = User.objects.create_user(username="faculty_b", password="pw12345!")
        other_faculty.groups.add(Group.objects.get(name="Faculty"))

        offering = CourseOffering.objects.create(
            course=course, term=term, batch=batch, faculty=faculty_user, is_active=True,
        )

        return {
            "department": department, "course": course, "topics": topics, "term": term,
            "batch": batch, "offering": offering,
            "hod_user": hod_user, "faculty_user": faculty_user, "other_faculty": other_faculty,
        }

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}


class SyllabusCoverageModelTests(_CoverageFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_upsert_is_unique_per_offering_topic(self):
        with schema_context(self.tenant.schema_name):
            offering = self.fixture["offering"]
            topic = self.fixture["topics"][0]
            entry, created = SyllabusCoverageEntry.objects.update_or_create(
                offering=offering, topic=topic, defaults={"status": SyllabusCoverageEntry.STATUS_COVERED},
            )
            self.assertTrue(created)
            entry2, created2 = SyllabusCoverageEntry.objects.update_or_create(
                offering=offering, topic=topic, defaults={"status": SyllabusCoverageEntry.STATUS_IN_PROGRESS},
            )
            self.assertFalse(created2)
            self.assertEqual(entry.id, entry2.id)
            self.assertEqual(SyllabusCoverageEntry.objects.filter(offering=offering, topic=topic).count(), 1)


class SyllabusCoverageAPITests(_CoverageFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.fixture = self._build_fixture()

    def test_faculty_sees_own_offering_in_my_offerings(self):
        response = self.client.get(
            reverse("syllabus-coverage-my-offerings"), **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        offerings = response.data["offerings"]
        self.assertEqual(len(offerings), 1)
        self.assertEqual(offerings[0]["course_code"], "CS301")
        self.assertEqual(offerings[0]["topics_total"], 4)
        self.assertEqual(offerings[0]["topics_covered"], 0)
        self.assertEqual(offerings[0]["coverage_pct"], 0.0)

    def test_other_faculty_does_not_see_offering(self):
        response = self.client.get(
            reverse("syllabus-coverage-my-offerings"), **self._auth(self.fixture["other_faculty"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["offerings"], [])

    def test_checklist_get_auto_derives_from_syllabus_topics(self):
        offering = self.fixture["offering"]
        response = self.client.get(
            reverse("syllabus-coverage-checklist", args=[offering.id]), **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["topics"]), 4)
        self.assertTrue(all(row["status"] == "not_started" for row in response.data["topics"]))
        self.assertEqual(response.data["pace"]["topics_total"], 4)

    def test_other_faculty_cannot_view_or_edit_offering_checklist(self):
        offering = self.fixture["offering"]
        get_response = self.client.get(
            reverse("syllabus-coverage-checklist", args=[offering.id]), **self._auth(self.fixture["other_faculty"]),
        )
        self.assertEqual(get_response.status_code, status.HTTP_403_FORBIDDEN)

        post_response = self.client.post(
            reverse("syllabus-coverage-checklist", args=[offering.id]),
            {"topic_id": self.fixture["topics"][0].id, "status": "covered"},
            format="json", **self._auth(self.fixture["other_faculty"]),
        )
        self.assertEqual(post_response.status_code, status.HTTP_403_FORBIDDEN)

    def test_faculty_can_mark_topic_covered_and_pace_updates(self):
        offering = self.fixture["offering"]
        topic = self.fixture["topics"][0]
        response = self.client.post(
            reverse("syllabus-coverage-checklist", args=[offering.id]),
            {"topic_id": topic.id, "status": "covered", "covered_on": str(datetime.date.today()), "remarks": "Done in class"},
            format="json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "covered")
        self.assertEqual(response.data["pace"]["topics_covered"], 1)
        self.assertEqual(response.data["pace"]["coverage_pct"], 25.0)

        with schema_context(self.tenant.schema_name):
            entry = SyllabusCoverageEntry.objects.get(offering=offering, topic=topic)
            self.assertEqual(entry.status, SyllabusCoverageEntry.STATUS_COVERED)
            self.assertEqual(entry.updated_by_id, self.fixture["faculty_user"].id)

    def test_post_rejects_topic_from_a_different_course(self):
        offering = self.fixture["offering"]
        with schema_context(self.tenant.schema_name):
            other_department = Department.objects.create(name="Mechanical", code="MECH")
            other_course = Course.objects.create(course_code="ME101", course_name="Thermo", department=other_department)
            foreign_topic = SyllabusTopic.objects.create(course=other_course, name="Unit X", order=1)

        response = self.client.post(
            reverse("syllabus-coverage-checklist", args=[offering.id]),
            {"topic_id": foreign_topic.id, "status": "covered"},
            format="json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_post_rejects_invalid_status(self):
        offering = self.fixture["offering"]
        topic = self.fixture["topics"][0]
        response = self.client.post(
            reverse("syllabus-coverage-checklist", args=[offering.id]),
            {"topic_id": topic.id, "status": "done_done_done"},
            format="json", **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_plain_faculty_cannot_see_hod_department_dashboard(self):
        response = self.client.get(
            reverse("syllabus-coverage-department"), **self._auth(self.fixture["faculty_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_hod_sees_own_department_offering_with_updated_pace(self):
        offering = self.fixture["offering"]
        topic = self.fixture["topics"][0]
        self.client.post(
            reverse("syllabus-coverage-checklist", args=[offering.id]),
            {"topic_id": topic.id, "status": "covered"},
            format="json", **self._auth(self.fixture["faculty_user"]),
        )

        response = self.client.get(
            reverse("syllabus-coverage-department"), **self._auth(self.fixture["hod_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        offerings = response.data["offerings"]
        self.assertEqual(len(offerings), 1)
        self.assertEqual(offerings[0]["id"], offering.id)
        self.assertEqual(offerings[0]["topics_covered"], 1)
        self.assertEqual(offerings[0]["faculty_name"], "faculty_a")

    def test_hod_can_also_view_and_edit_a_faculty_offering(self):
        offering = self.fixture["offering"]
        topic = self.fixture["topics"][1]
        response = self.client.post(
            reverse("syllabus-coverage-checklist", args=[offering.id]),
            {"topic_id": topic.id, "status": "in_progress"},
            format="json", **self._auth(self.fixture["hod_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

"""
Backend pieces added for the app-gap screens (2026-11-18):
- library self-service renewal (book-issues/<id>/renew/)
- promotion preview + history (students/promote/preview/, students/promote/batches/)
- parent missed-lectures list for attendance disputes (parent/children/<id>/missed-lectures/)
"""
import datetime
import json

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import Attendance, AttendanceCorrectionRequest, Classroom, Lecture
from .models.department import Department
from .models.library import Book, BookCopy, BookIssue
from .models.profile import GuardianProfile, StudentProfile, TeachingStaffProfile


class _Base(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.tenant.subscribed_modules = ["library", "academics", "attendance"]
        self.tenant.save(update_fields=["subscribed_modules"])
        with schema_context(self.tenant.schema_name):
            for role in ("Administrator", "Faculty", "student", "Librarian"):
                Group.objects.get_or_create(name=role)
            self.dept = Department.objects.create(name="Mechanical", code="ME")
            self.admin = User.objects.create_user(username="gs_admin", password="pw12345!")
            self.admin.groups.add(Group.objects.get(name="Administrator"))
            self.s1 = self._student("gs_s1", "ME-001", "SE", "A")
            self.s2 = self._student("gs_s2", "ME-002", "SE", "A")
            self.s3 = self._student("gs_s3", "ME-003", "TE", "")

    def _student(self, username, sid, year, section):
        user = User.objects.create_user(username=username, password="pw12345!", first_name=username.upper())
        user.groups.add(Group.objects.get(name="student"))
        return StudentProfile.objects.create(
            user=user, student_id=sid, department=self.dept, current_semester_year=year, section_division=section,
        )

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

    def _post(self, url, data, user):
        return self.client.post(url, json.dumps(data), content_type="application/json", **self._auth(user))


class LibraryRenewalTests(_Base):
    def _loan(self, student, due_in_days, barcode):
        with schema_context(self.tenant.schema_name):
            book = Book.objects.create(title=f"Book {barcode}", author="A", isbn=f"ISBN-{barcode}")
            copy = BookCopy.objects.create(book=book, barcode=barcode, status="Issued")
            return BookIssue.objects.create(
                book_copy=copy, student=student, due_date=timezone.localdate() + datetime.timedelta(days=due_in_days),
            )

    def test_student_renews_own_book_until_limit(self):
        loan = self._loan(self.s1, 3, "B1")
        url = reverse("bookissue-renew", args=[loan.id])
        first = self._post(url, {}, self.s1.user)
        self.assertEqual(first.status_code, status.HTTP_200_OK, first.data)
        self.assertEqual(first.data["renewal_count"], 1)
        self.assertEqual(first.data["renewals_left"], 1)
        expected = loan.due_date + datetime.timedelta(days=14)
        self.assertEqual(first.data["due_date"], expected.isoformat())

        self.assertEqual(self._post(url, {}, self.s1.user).status_code, status.HTTP_200_OK)
        third = self._post(url, {}, self.s1.user)
        self.assertEqual(third.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("renewed 2 times", third.data["error"])

    def test_cannot_renew_someone_elses_or_overdue_book(self):
        loan = self._loan(self.s1, 3, "B2")
        other = self._post(reverse("bookissue-renew", args=[loan.id]), {}, self.s2.user)
        self.assertEqual(other.status_code, status.HTTP_403_FORBIDDEN)

        overdue = self._loan(self.s1, -2, "B3")
        late = self._post(reverse("bookissue-renew", args=[overdue.id]), {}, self.s1.user)
        self.assertEqual(late.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("overdue", late.data["error"])

        # The library can still extend an overdue loan at the desk.
        desk = self._post(reverse("bookissue-renew", args=[overdue.id]), {}, self.admin)
        self.assertEqual(desk.status_code, status.HTTP_200_OK, desk.data)
        self.assertGreater(desk.data["due_date"], timezone.localdate().isoformat())


class PromotionPreviewTests(_Base):
    def test_classes_roster_and_history(self):
        auth = self._auth(self.admin)
        classes = self.client.get(reverse("students-promote-preview"), {"department_id": self.dept.id}, **auth)
        self.assertEqual(classes.status_code, status.HTTP_200_OK, classes.data)
        self.assertIn({"semester_year": "SE", "section_division": "A", "students": 2}, classes.data["classes"])

        roster = self.client.get(
            reverse("students-promote-preview"),
            {"department_id": self.dept.id, "from_semester_year": "SE", "from_section_division": "A"}, **auth,
        )
        self.assertEqual([r["student_id"] for r in roster.data["students"]], ["ME-001", "ME-002"])
        self.assertTrue(all(r["is_cleared"] for r in roster.data["students"]))  # no desks configured

        promote = self._post(reverse("students-promote"), {
            "department_id": self.dept.id, "from_semester_year": "SE", "from_section_division": "A",
            "to_semester_year": "TE", "to_section_division": "A",
            "decisions": [{"student_id": self.s2.id, "decision": "hold"}],
        }, self.admin)
        self.assertEqual(promote.status_code, status.HTTP_201_CREATED, promote.data)

        history = self.client.get(reverse("students-promote-batches"), **auth)
        self.assertEqual(history.status_code, status.HTTP_200_OK)
        self.assertEqual(history.data[0]["promoted"], 1)
        self.assertEqual(history.data[0]["held"], 1)
        self.assertEqual(history.data[0]["from_class"], "SE A")
        self.assertTrue(history.data[0]["can_revert"])

    def test_students_cannot_preview(self):
        res = self.client.get(reverse("students-promote-preview"), {"department_id": self.dept.id}, **self._auth(self.s1.user))
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)


class MissedLecturesTests(_Base):
    def test_parent_sees_missed_lectures_with_dispute_status(self):
        with schema_context(self.tenant.schema_name):
            fac = User.objects.create_user(username="gs_fac", password="pw12345!", first_name="Fac")
            fac.groups.add(Group.objects.get(name="Faculty"))
            TeachingStaffProfile.objects.create(user=fac, employee_id="GS-F1", department=self.dept)
            room = Classroom.objects.create(name="Room GS", code="RGS")
            now = timezone.now()
            attended = Lecture.objects.create(name="Thermo L1", subject="Thermo", faculty=fac, classroom=room,
                                              start_time=now - datetime.timedelta(days=2), end_time=now - datetime.timedelta(days=2, hours=-1), code="GS1")
            missed = Lecture.objects.create(name="Thermo L2", subject="Thermo", faculty=fac, classroom=room,
                                            start_time=now - datetime.timedelta(days=1), end_time=now - datetime.timedelta(days=1, hours=-1), code="GS2")
            disputed = Lecture.objects.create(name="Thermo L3", subject="Thermo", faculty=fac, classroom=room,
                                              start_time=now - datetime.timedelta(hours=5), end_time=now - datetime.timedelta(hours=4), code="GS3")
            Lecture.objects.create(name="Old", subject="Thermo", faculty=fac, classroom=room,
                                   start_time=now - datetime.timedelta(days=45), end_time=now - datetime.timedelta(days=45, hours=-1), code="GS4")
            Attendance.objects.create(user=self.s1.user, lecture=attended)
            parent = User.objects.create_user(username="gs_parent", password="pw12345!")
            guardian = GuardianProfile.objects.create(user=parent, guardian_id="GS-G1")
            guardian.students.add(self.s1)
            AttendanceCorrectionRequest.objects.create(student=self.s1, lecture=disputed, requested_by=parent, reason="Was ill")

        res = self.client.get(reverse("parent-child-missed-lectures", args=[self.s1.id]), **self._auth(parent))
        self.assertEqual(res.status_code, status.HTTP_200_OK, res.data)
        names = [r["lecture_name"] for r in res.data["results"]]
        self.assertEqual(names, ["Thermo L3", "Thermo L2"])  # newest first, attended + old excluded
        self.assertEqual(res.data["results"][0]["dispute"]["status"], "pending")
        self.assertIsNone(res.data["results"][1]["dispute"])

        # Filing a dispute for the missed one goes through the existing endpoint.
        filed = self._post(reverse("attendance-correction-create"),
                           {"student_id": self.s1.id, "lecture_id": missed.id, "reason": "Doctor visit"}, parent)
        self.assertEqual(filed.status_code, status.HTTP_201_CREATED, filed.data)

        # Another parent can't read this child's list.
        with schema_context(self.tenant.schema_name):
            stranger = User.objects.create_user(username="gs_stranger", password="pw12345!")
            GuardianProfile.objects.create(user=stranger, guardian_id="GS-G2")
        denied = self.client.get(reverse("parent-child-missed-lectures", args=[self.s1.id]), **self._auth(stranger))
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

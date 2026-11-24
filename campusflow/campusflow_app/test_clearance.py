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
    AcademicYear, ClearanceDesk, ClearanceFlow, ClearanceFlowStep, ClearanceItem, ClearanceRequest,
    ClearanceSettings, Department, PromotionRecord, StudentProfile, Term,
)
from .services.academics import set_current_term
from .services.clearance import ensure_default_flow, is_student_cleared


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

    def test_no_published_flow_means_not_gated(self):
        with schema_context(self.tenant.schema_name):
            is_cleared, request_obj = is_student_cleared(self.fixture["student"])
            self.assertTrue(is_cleared)
            self.assertIsNone(request_obj)

    def test_no_request_yet_means_not_cleared(self):
        with schema_context(self.tenant.schema_name):
            ensure_default_flow(ClearanceFlow.PURPOSE_PERIODIC)
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
        with schema_context(self.tenant.schema_name):
            ensure_default_flow(ClearanceFlow.PURPOSE_PERIODIC)
        response = self.client.get(reverse("clearance-my-status"), **self._auth(self.fixture["admin_user"]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.get(reverse("clearance-my-status"), **self._auth(self.fixture["student_user"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.data["is_cleared"])


class ClearanceFlowTests(_ClearanceFixtureMixin, TenantTestCase):
    """Flows built by Admin/HOD, subject-wise routing, sequencing, resubmission, gates."""

    def setUp(self):
        super().setUp()
        from .models.academics import Batch, Program, Regulation, Section
        from .models.course import Course
        from .models.offerings import CourseOffering, StudentCourseRegistration
        from .services.academics import get_default_grading_scheme

        with schema_context(self.tenant.schema_name):
            f = self.fixture = self._build_fixture()
            for role in ("Department Head", "Faculty"):
                Group.objects.get_or_create(name=role)

            def make_user(name, role):
                u = User.objects.create_user(username=name, password="pw12345!", first_name=name.title())
                u.groups.add(Group.objects.get(name=role))
                return u

            f["hod"] = make_user("hodcse", "Department Head")
            f["department"].hod = f["hod"]
            f["department"].save(update_fields=["hod"])
            f["other_dept"] = Department.objects.create(name="Mechanical", code="ME")
            f["other_hod"] = make_user("hodme", "Department Head")
            f["other_dept"].hod = f["other_hod"]
            f["other_dept"].save(update_fields=["hod"])
            f["teacher_a"] = make_user("teachera", "Faculty")
            f["teacher_b"] = make_user("teacherb", "Faculty")
            f["mentor"] = make_user("mentor1", "Faculty")

            program = Program.objects.create(name="B.Tech CSE", code="BTCSE", department=f["department"])
            regulation = Regulation.objects.create(
                program=program, code="R2023", effective_from_year=2023, grading_scheme=get_default_grading_scheme(),
            )
            batch = Batch.objects.create(program=program, regulation=regulation, admission_year=2023, name="2023-2027")
            section = Section.objects.create(batch=batch, name="A", semester_number=1, mentor=f["mentor"])
            student = f["student"]
            student.program, student.batch, student.section = program, batch, section
            student.current_semester_number = 1
            student.save()

            for code, teacher in (("CS101", f["teacher_a"]), ("CS102", f["teacher_b"])):
                course = Course.objects.create(
                    course_code=code, course_name=f"Course {code}", department=f["department"],
                    regulation=regulation, semester_number=1, credits=4,
                )
                offering = CourseOffering.objects.create(course=course, term=f["term"], batch=batch, faculty=teacher)
                StudentCourseRegistration.objects.create(student=student, offering=offering, term=f["term"])

    def _dept_flow_payload(self, **overrides):
        payload = {
            "name": "CSE Semester Clearance", "purpose": "periodic", "approval_mode": "sequential",
            "status": "published",
            "steps": [
                {"order": 1, "title": "Subject sign-off", "approver_type": "subject_faculty"},
                {"order": 2, "title": "Mentor", "approver_type": "section_mentor"},
                {"order": 3, "title": "HOD", "approver_type": "department_hod"},
            ],
        }
        payload.update(overrides)
        return payload

    def _create_dept_flow(self):
        response = self.client.post(
            reverse("clearance-flow-list"), self._dept_flow_payload(), content_type="application/json",
            **self._auth(self.fixture["hod"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        return response.data["id"]

    def _launch(self, flow_id, user):
        return self.client.post(
            reverse("clearance-flow-launch", args=[flow_id]), {"term_id": self.fixture["term"].id},
            content_type="application/json", **self._auth(user),
        )

    def test_hod_builds_only_own_department_flows_with_department_steps(self):
        flow_id = self._create_dept_flow()
        with schema_context(self.tenant.schema_name):
            self.assertEqual(ClearanceFlow.objects.get(pk=flow_id).department_id, self.fixture["department"].id)

        # A college office step is refused in a department flow.
        bad = self._dept_flow_payload(steps=[
            {"order": 1, "title": "Library", "approver_type": "desk", "desk": self.fixture["library_desk"].id},
        ])
        response = self.client.post(reverse("clearance-flow-list"), bad, content_type="application/json", **self._auth(self.fixture["hod"]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # Another department's HOD can't build for CSE or edit CSE's flow.
        other = self._dept_flow_payload(department=self.fixture["department"].id)
        response = self.client.post(reverse("clearance-flow-list"), other, content_type="application/json", **self._auth(self.fixture["other_hod"]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self.client.patch(
            reverse("clearance-flow-detail", args=[flow_id]), {"name": "x"}, content_type="application/json",
            **self._auth(self.fixture["other_hod"]),
        )
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))

        # A plain approver can't build flows at all.
        response = self.client.post(
            reverse("clearance-flow-list"), self._dept_flow_payload(), content_type="application/json",
            **self._auth(self.fixture["librarian_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_subject_wise_sequential_flow_routes_to_each_teacher_then_mentor_then_hod(self):
        flow_id = self._create_dept_flow()
        # Publishing already sent it; launching again only skips.
        response = self._launch(flow_id, self.fixture["hod"])
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data, {"created": 0, "skipped_existing": 1})

        with schema_context(self.tenant.schema_name):
            req = ClearanceRequest.objects.get(flow_id=flow_id)
            subject_items = list(req.items.filter(step_order=1))
            self.assertEqual(len(subject_items), 2)
            self.assertTrue(all(i.status == ClearanceItem.STATUS_PENDING for i in subject_items))
            self.assertEqual(req.items.filter(status=ClearanceItem.STATUS_WAITING).count(), 2)
            item_a = req.items.get(approver=self.fixture["teacher_a"])
            item_b = req.items.get(approver=self.fixture["teacher_b"])
            mentor_item = req.items.get(step_order=2)
            self.assertEqual(mentor_item.approver, self.fixture["mentor"])

        # Each teacher's inbox holds only their own subject.
        response = self.client.get(reverse("clearance-inbox"), **self._auth(self.fixture["teacher_a"]))
        self.assertEqual([row["id"] for row in response.data], [item_a.id])

        # Teacher A can't sign Teacher B's subject; the mentor can't act before their turn.
        response = self.client.post(reverse("clearance-item-clear", args=[item_b.id]), {}, content_type="application/json", **self._auth(self.fixture["teacher_a"]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.post(reverse("clearance-item-clear", args=[mentor_item.id]), {}, content_type="application/json", **self._auth(self.fixture["mentor"]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        for item, teacher in ((item_a, "teacher_a"), (item_b, "teacher_b")):
            response = self.client.post(reverse("clearance-item-clear", args=[item.id]), {}, content_type="application/json", **self._auth(self.fixture[teacher]))
            self.assertEqual(response.status_code, status.HTTP_200_OK)

        with schema_context(self.tenant.schema_name):
            mentor_item.refresh_from_db()
            self.assertEqual(mentor_item.status, ClearanceItem.STATUS_PENDING)
            self.assertEqual(req.items.get(step_order=3).status, ClearanceItem.STATUS_WAITING)

    def test_rejected_step_is_resubmitted_by_student_back_to_same_approver(self):
        flow_id = self._create_dept_flow()
        self._launch(flow_id, self.fixture["hod"])
        with schema_context(self.tenant.schema_name):
            item_a = ClearanceItem.objects.get(approver=self.fixture["teacher_a"])

        response = self.client.post(
            reverse("clearance-item-reject", args=[item_a.id]), {"remarks": "Journal incomplete"},
            content_type="application/json", **self._auth(self.fixture["teacher_a"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Only the student can resubmit, and only a rejected item.
        response = self.client.post(reverse("clearance-item-resubmit", args=[item_a.id]), {}, content_type="application/json", **self._auth(self.fixture["teacher_a"]))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.post(
            reverse("clearance-item-resubmit", args=[item_a.id]), {"note": "Journal completed"},
            content_type="application/json", **self._auth(self.fixture["student_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], ClearanceItem.STATUS_PENDING)
        self.assertEqual(response.data["resubmit_count"], 1)

        response = self.client.get(reverse("clearance-item-detail", args=[item_a.id]), **self._auth(self.fixture["teacher_a"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["can_act"])
        self.assertEqual([h["action"] for h in response.data["history"]], ["activated", "rejected", "resubmitted"])

    def test_gate_needs_every_applicable_flow_cleared(self):
        student = self.fixture["student"]
        with schema_context(self.tenant.schema_name):
            college_flow = ensure_default_flow(ClearanceFlow.PURPOSE_PERIODIC)
        flow_id = self._create_dept_flow()
        self._launch(flow_id, self.fixture["hod"])
        self._launch(college_flow.id, self.fixture["admin_user"])

        with schema_context(self.tenant.schema_name):
            for item in ClearanceItem.objects.filter(request__flow=college_flow):
                item.status = ClearanceItem.STATUS_CLEARED
                item.save(update_fields=["status"])
            ClearanceRequest.objects.get(flow=college_flow).recompute_status()
            cleared, blocking = is_student_cleared(student)
            self.assertFalse(cleared)
            self.assertEqual(blocking.flow_id, flow_id)

            # Another department's flow doesn't apply to this student.
            other = ClearanceFlow.objects.create(
                name="ME flow", department=self.fixture["other_dept"], status=ClearanceFlow.STATUS_PUBLISHED,
            )
            ClearanceFlowStep.objects.create(flow=other, title="HOD", approver_type="department_hod")

            for item in ClearanceItem.objects.filter(request__flow_id=flow_id):
                item.status = ClearanceItem.STATUS_CLEARED
                item.save(update_fields=["status"])
            ClearanceRequest.objects.get(flow_id=flow_id).recompute_status()
            cleared, _ = is_student_cleared(student)
            self.assertTrue(cleared)

    def test_student_applies_only_when_flow_allows_it(self):
        with schema_context(self.tenant.schema_name):
            flow = ClearanceFlow.objects.create(
                name="TC Clearance", purpose=ClearanceFlow.PURPOSE_FINAL_EXIT, status=ClearanceFlow.STATUS_PUBLISHED,
            )
            ClearanceFlowStep.objects.create(flow=flow, title="Library", approver_type="desk", desk=self.fixture["library_desk"])

        url = reverse("clearance-flow-apply", args=[flow.id])
        response = self.client.post(url, {}, content_type="application/json", **self._auth(self.fixture["student_user"]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        with schema_context(self.tenant.schema_name):
            flow.allow_student_apply = True
            flow.save(update_fields=["allow_student_apply"])
        response = self.client.get(reverse("clearance-my-flows"), **self._auth(self.fixture["student_user"]))
        self.assertEqual([f["id"] for f in response.data], [flow.id])
        response = self.client.post(url, {}, content_type="application/json", **self._auth(self.fixture["student_user"]))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        response = self.client.post(url, {}, content_type="application/json", **self._auth(self.fixture["student_user"]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        # The desk role sees it in its inbox and on its dashboard count.
        response = self.client.get(reverse("clearance-inbox-summary"), **self._auth(self.fixture["librarian_user"]))
        self.assertEqual(response.data["pending"], 1)

    def test_launched_flow_steps_are_locked_and_flow_cannot_be_deleted(self):
        flow_id = self._create_dept_flow()
        self._launch(flow_id, self.fixture["hod"])
        changed = self._dept_flow_payload(steps=[{"order": 1, "title": "HOD only", "approver_type": "department_hod"}])
        response = self.client.put(reverse("clearance-flow-detail", args=[flow_id]), changed, content_type="application/json", **self._auth(self.fixture["hod"]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

        response = self.client.patch(reverse("clearance-flow-detail", args=[flow_id]), {"status": "closed"}, content_type="application/json", **self._auth(self.fixture["hod"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        response = self.client.delete(reverse("clearance-flow-detail", args=[flow_id]), **self._auth(self.fixture["hod"]))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_college_wide_flow_reaches_every_student(self):
        f = self.fixture
        response = self.client.post(
            reverse("clearance-flow-list"),
            {
                "name": "College No-Dues", "purpose": "other", "approval_mode": "parallel", "status": "published",
                "department": None,
                "steps": [{"order": 1, "title": "Library", "approver_type": "desk", "desk": f["library_desk"].id}],
            },
            content_type="application/json", **self._auth(f["admin_user"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertIsNone(response.data["department"])
        flow_id = response.data["id"]
        # Publishing sends it: no separate Launch needed.
        self.assertEqual(response.data["launched"]["created"], 1)

        # Launch again is safe (late joiners) and skips who already has it.
        response = self.client.post(
            reverse("clearance-flow-launch", args=[flow_id]), {}, content_type="application/json",
            **self._auth(f["admin_user"]),
        )
        self.assertEqual(response.data, {"created": 0, "skipped_existing": 1})

        response = self.client.get(reverse("clearance-request-list"), **self._auth(f["student_user"]))
        rows = response.data.get("results", response.data) if isinstance(response.data, dict) else response.data
        self.assertEqual([r["flow"] for r in rows], [flow_id])

    def test_publishing_a_draft_sends_it_but_student_apply_flows_are_not_pushed(self):
        f = self.fixture
        response = self.client.post(
            reverse("clearance-flow-list"), self._dept_flow_payload(status="draft"), content_type="application/json",
            **self._auth(f["hod"]),
        )
        self.assertNotIn("launched", response.data)
        flow_id = response.data["id"]
        with schema_context(self.tenant.schema_name):
            self.assertFalse(ClearanceRequest.objects.filter(flow_id=flow_id).exists())

        response = self.client.patch(
            reverse("clearance-flow-detail", args=[flow_id]), {"status": "published"}, content_type="application/json",
            **self._auth(f["hod"]),
        )
        self.assertEqual(response.data["launched"]["created"], 1)
        # Saving an already-published flow doesn't send it again.
        response = self.client.patch(
            reverse("clearance-flow-detail", args=[flow_id]), {"name": "Renamed"}, content_type="application/json",
            **self._auth(f["hod"]),
        )
        self.assertNotIn("launched", response.data)

        response = self.client.post(
            reverse("clearance-flow-list"),
            self._dept_flow_payload(name="TC", purpose="final_exit", allow_student_apply=True),
            content_type="application/json", **self._auth(f["hod"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertNotIn("launched", response.data)
        with schema_context(self.tenant.schema_name):
            self.assertFalse(ClearanceRequest.objects.filter(flow_id=response.data["id"]).exists())

    def test_specific_person_without_the_module_still_gets_their_inbox(self):
        f = self.fixture
        Group.objects.get_or_create(name="Support Staff")
        lab_assistant = User.objects.create_user(username="labasst", password="pw12345!", first_name="Lab")
        lab_assistant.groups.add(Group.objects.get(name="Support Staff"))
        bystander = User.objects.create_user(username="clerk1", password="pw12345!")
        bystander.groups.add(Group.objects.get(name="Support Staff"))

        # Not a clearance role, and no flow names them yet.
        response = self.client.get(reverse("clearance-inbox"), **self._auth(lab_assistant))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.post(
            reverse("clearance-flow-list"),
            self._dept_flow_payload(
                approval_mode="parallel",
                steps=[{"order": 1, "title": "Lab equipment", "approver_type": "specific_user", "approver_user": lab_assistant.id}],
            ),
            content_type="application/json", **self._auth(f["hod"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        self.assertEqual(response.data["launched"]["created"], 1)

        response = self.client.get(reverse("user-allowed-modules"), **self._auth(lab_assistant))
        self.assertIn("clearance", response.data["allowed_modules"])
        response = self.client.get(reverse("clearance-inbox"), **self._auth(lab_assistant))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        response = self.client.post(
            reverse("clearance-item-clear", args=[response.data[0]["id"]]), {}, content_type="application/json",
            **self._auth(lab_assistant),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

        # Being an approver doesn't make them a flow builder, and others in the role get nothing.
        response = self.client.post(
            reverse("clearance-flow-list"), self._dept_flow_payload(), content_type="application/json",
            **self._auth(lab_assistant),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(reverse("clearance-inbox"), **self._auth(bystander))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_no_dues_pdf_then_submit_to_department_and_receive(self):
        f = self.fixture
        response = self.client.post(
            reverse("clearance-flow-list"),
            self._dept_flow_payload(approval_mode="parallel", steps=[{"order": 1, "title": "HOD", "approver_type": "department_hod"}]),
            content_type="application/json", **self._auth(f["hod"]),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)
        with schema_context(self.tenant.schema_name):
            req = ClearanceRequest.objects.get(flow_id=response.data["id"])
            item = req.items.get()
        pdf_url = reverse("clearance-request-pdf", args=[req.id])

        # Not cleared yet: no PDF, no submission.
        self.assertEqual(self.client.get(pdf_url, **self._auth(f["student_user"])).status_code, status.HTTP_400_BAD_REQUEST)
        submit_url = reverse("clearance-request-submit", args=[req.id])
        self.assertEqual(
            self.client.post(submit_url, {}, content_type="application/json", **self._auth(f["student_user"])).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        self.client.post(reverse("clearance-item-clear", args=[item.id]), {}, content_type="application/json", **self._auth(f["hod"]))

        response = self.client.get(pdf_url, **self._auth(f["student_user"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertTrue(response.content.startswith(b"%PDF"))
        # Another department's HOD can't download it.
        self.assertEqual(self.client.get(pdf_url, **self._auth(f["other_hod"])).status_code, status.HTTP_403_FORBIDDEN)

        response = self.client.post(submit_url, {"note": "Original handed in too"}, content_type="application/json", **self._auth(f["student_user"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertIsNotNone(response.data["submitted_at"])
        self.assertEqual(
            self.client.post(submit_url, {}, content_type="application/json", **self._auth(f["student_user"])).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

        response = self.client.get(reverse("clearance-submissions"), **self._auth(f["hod"]))
        self.assertEqual([r["id"] for r in response.data], [req.id])
        response = self.client.get(reverse("clearance-submissions"), **self._auth(f["other_hod"]))
        self.assertEqual(response.data, [])
        self.assertEqual(self.client.get(reverse("clearance-submissions"), **self._auth(f["teacher_a"])).status_code, status.HTTP_403_FORBIDDEN)

        receive_url = reverse("clearance-request-receive", args=[req.id])
        self.assertEqual(
            self.client.post(receive_url, {}, content_type="application/json", **self._auth(f["other_hod"])).status_code,
            status.HTTP_403_FORBIDDEN,
        )
        response = self.client.post(receive_url, {}, content_type="application/json", **self._auth(f["hod"]))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["received_by_name"], "Hodcse")
        response = self.client.get(reverse("clearance-submissions") + "?status=received", **self._auth(f["hod"]))
        self.assertEqual([r["id"] for r in response.data], [req.id])

        # The QR link verifies without a login.
        with schema_context(self.tenant.schema_name):
            req.refresh_from_db()
        response = self.client.get(reverse("clearance-verify", args=[self.tenant.schema_name, req.verification_token]))
        # A login-free request leaves the connection on the public schema; put it back for the next test.
        from django.db import connection
        connection.set_tenant(self.tenant)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["valid"])
        self.assertEqual(response.data["student_id"], "CSE001")

    def test_launch_requires_published_flow(self):
        response = self.client.post(
            reverse("clearance-flow-list"), self._dept_flow_payload(status="draft"), content_type="application/json",
            **self._auth(self.fixture["hod"]),
        )
        response = self._launch(response.data["id"], self.fixture["hod"])
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

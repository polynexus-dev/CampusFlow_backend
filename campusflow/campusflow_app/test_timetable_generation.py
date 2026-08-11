"""
Tests for automatic timetable generation: services/timetable_generation.py's
CP-SAT solver (real solves against small hand-built scenarios — mocking a
constraint solver would defeat the point of testing it), the
run_generate_timetable Celery task, and the generate/apply/discard API flow.

campusflow_app is a TENANT_APP (django-tenants) — every DB operation runs
inside schema_context(self.tenant.schema_name), matching the convention
established in the other test files this session.
"""

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models.academics import Batch, Program, Regulation, Section
from .models.classroom import Classroom
from .models.course import Course
from .models.department import Department
from .models.offerings import CourseOffering
from .models.profile import TeachingStaffProfile
from .models.schedule import Schedule
from .models.timetable_generation import TimetableGenerationRun
from .services import timetable_generation as tg
from .services.academics import get_current_term, get_default_grading_scheme
from .tasks import run_generate_timetable


class _TimetableFixtureMixin:
    """Shared fixture builders — mirrors the `_spine()` helper pattern already used across tests.py."""

    def _department(self, code="TT"):
        return Department.objects.create(name=f"Dept {code}", code=code)

    def _term(self):
        return get_current_term()

    def _batch(self, department, suffix="A"):
        scheme = get_default_grading_scheme()
        program = Program.objects.create(name=f"Program {suffix}", code=f"PRG{suffix}", department=department)
        regulation = Regulation.objects.create(
            program=program, code=f"REG{suffix}", effective_from_year=2020, grading_scheme=scheme,
        )
        return Batch.objects.create(program=program, regulation=regulation, admission_year=2024, name=f"Batch {suffix}")

    def _course(self, department, suffix, lecture_hours=1):
        return Course.objects.create(
            course_code=f"CRS{suffix}", course_name=f"Course {suffix}", department=department,
            lecture_hours=lecture_hours,
        )

    def _faculty(self, department, suffix, max_weekly_teaching_hours=None):
        user = User.objects.create_user(username=f"faculty_tt_{suffix}", email=f"faculty_tt_{suffix}@test.com")
        TeachingStaffProfile.objects.create(
            user=user, employee_id=f"EMP_TT_{suffix}", department=department,
            max_weekly_teaching_hours=max_weekly_teaching_hours,
        )
        return user

    def _classroom(self, suffix, capacity=None):
        return Classroom.objects.create(name=f"Room {suffix}", code=f"RM{suffix}", capacity=capacity)

    def _offering(self, course, term, batch, faculty=None, section=None):
        return CourseOffering.objects.create(course=course, term=term, batch=batch, faculty=faculty, section=section)


class SolverUnitTests(_TimetableFixtureMixin, TenantTestCase):
    def test_generate_timetable_produces_one_placement_per_session(self):
        with schema_context(self.tenant.schema_name):
            department = self._department("A")
            term = self._term()
            batch = self._batch(department)
            faculty1 = self._faculty(department, "f1")
            faculty2 = self._faculty(department, "f2")
            course1 = self._course(department, "1")
            course2 = self._course(department, "2")
            self._classroom("1")
            self._offering(course1, term, batch, faculty=faculty1)
            self._offering(course2, term, batch, faculty=faculty2)

            placements = tg.generate_timetable(term)
            self.assertEqual(len(placements), 2)

    def test_solver_never_double_books_the_same_faculty(self):
        with schema_context(self.tenant.schema_name):
            department = self._department("B")
            term = self._term()
            batch = self._batch(department)
            faculty = self._faculty(department, "shared")
            course1 = self._course(department, "3")
            course2 = self._course(department, "4")
            self._classroom("2")
            self._offering(course1, term, batch, faculty=faculty)
            self._offering(course2, term, batch, faculty=faculty)

            placements = tg.generate_timetable(term)
            self.assertEqual(len(placements), 2)
            slot_a = (placements[0]["day_of_week"], placements[0]["start_time"])
            slot_b = (placements[1]["day_of_week"], placements[1]["start_time"])
            self.assertNotEqual(slot_a, slot_b)

    def test_offerings_without_faculty_are_excluded(self):
        with schema_context(self.tenant.schema_name):
            department = self._department("C")
            term = self._term()
            batch = self._batch(department)
            course = self._course(department, "5")
            self._classroom("3")
            self._offering(course, term, batch, faculty=None)

            placements = tg.generate_timetable(term)
            self.assertEqual(placements, [])

    def test_classroom_too_small_is_excluded_from_candidates(self):
        with schema_context(self.tenant.schema_name):
            department = self._department("D")
            term = self._term()
            batch = self._batch(department)
            section = Section.objects.create(batch=batch, name="A", semester_number=1, capacity=50)
            faculty = self._faculty(department, "cap")
            course = self._course(department, "6")
            small_room = self._classroom("small", capacity=10)
            big_room = self._classroom("big", capacity=100)
            self._offering(course, term, batch, faculty=faculty, section=section)

            placements = tg.generate_timetable(term)
            self.assertEqual(len(placements), 1)
            self.assertEqual(placements[0]["classroom_id"], big_room.id)
            self.assertNotEqual(placements[0]["classroom_id"], small_room.id)

    def test_capacity_constraint_skipped_when_data_missing(self):
        with schema_context(self.tenant.schema_name):
            department = self._department("E")
            term = self._term()
            batch = self._batch(department)
            section = Section.objects.create(batch=batch, name="A", semester_number=1, capacity=50)
            faculty = self._faculty(department, "nocap")
            course = self._course(department, "7")
            self._classroom("unsized", capacity=None)  # no capacity set -> constraint skipped, not blocking
            self._offering(course, term, batch, faculty=faculty, section=section)

            placements = tg.generate_timetable(term)
            self.assertEqual(len(placements), 1)

    def test_faculty_weekly_load_cap_makes_it_infeasible_when_exceeded(self):
        with schema_context(self.tenant.schema_name):
            department = self._department("F")
            term = self._term()
            batch = self._batch(department)
            faculty = self._faculty(department, "overloaded", max_weekly_teaching_hours=1)
            course1 = self._course(department, "8", lecture_hours=1)
            course2 = self._course(department, "9", lecture_hours=1)
            self._classroom("4")
            self._offering(course1, term, batch, faculty=faculty)
            self._offering(course2, term, batch, faculty=faculty)

            # 2 required hours for a faculty capped at 1 -> no feasible assignment.
            with self.assertRaises(tg.TimetableInfeasibleError):
                tg.generate_timetable(term)

    def test_routes_around_existing_live_schedule(self):
        with schema_context(self.tenant.schema_name):
            department = self._department("G")
            term = self._term()
            batch = self._batch(department)
            faculty = self._faculty(department, "route")
            other_faculty = self._faculty(department, "other")
            course = self._course(department, "10")
            other_course = self._course(department, "11")
            classroom = self._classroom("5")

            # Occupy the very first grid slot in the only classroom with a live row.
            first_day, first_start = tg._slot_grid()[0]
            Schedule.objects.create(
                course=other_course, faculty=other_faculty, classroom=classroom,
                day_of_week=first_day, start_time=first_start, end_time=first_start,
                semester=term.name, academic_year=term.academic_year.name, term=term,
                is_draft=False,
            )

            self._offering(course, term, batch, faculty=faculty)
            placements = tg.generate_timetable(term)

            self.assertEqual(len(placements), 1)
            placed_slot = (placements[0]["day_of_week"], placements[0]["start_time"])
            self.assertNotEqual(placed_slot, (first_day, first_start))


class RunGenerateTimetableTaskTests(_TimetableFixtureMixin, TenantTestCase):
    def test_task_success_creates_draft_schedule_rows(self):
        with schema_context(self.tenant.schema_name):
            department = self._department("H")
            term = self._term()
            batch = self._batch(department)
            faculty = self._faculty(department, "task1")
            course = self._course(department, "12")
            self._classroom("6")
            self._offering(course, term, batch, faculty=faculty)
            run = TimetableGenerationRun.objects.create(term=term)

        run_generate_timetable(self.tenant.schema_name, run.id)

        with schema_context(self.tenant.schema_name):
            run.refresh_from_db()
            self.assertEqual(run.status, "completed")
            self.assertIsNotNone(run.solve_time_seconds)
            drafts = Schedule.objects.filter(generation_run=run)
            self.assertEqual(drafts.count(), 1)
            self.assertTrue(drafts.first().is_draft)

    def test_task_records_infeasible_status(self):
        with schema_context(self.tenant.schema_name):
            department = self._department("I")
            term = self._term()
            batch = self._batch(department)
            faculty = self._faculty(department, "task2", max_weekly_teaching_hours=1)
            course1 = self._course(department, "13", lecture_hours=1)
            course2 = self._course(department, "14", lecture_hours=1)
            self._classroom("7")
            self._offering(course1, term, batch, faculty=faculty)
            self._offering(course2, term, batch, faculty=faculty)
            run = TimetableGenerationRun.objects.create(term=term)

        run_generate_timetable(self.tenant.schema_name, run.id)

        with schema_context(self.tenant.schema_name):
            run.refresh_from_db()
            self.assertEqual(run.status, "infeasible")
            self.assertEqual(Schedule.objects.filter(generation_run=run).count(), 0)

    def test_task_no_op_when_run_missing(self):
        with schema_context(self.tenant.schema_name):
            term = self._term()
            run = TimetableGenerationRun.objects.create(term=term)
        run_generate_timetable(self.tenant.schema_name, run.id + 9999)


class TimetableGenerationAPITests(_TimetableFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ("Management", "Faculty"):
                Group.objects.get_or_create(name=role)

            self.department = self._department("API")
            self.term = self._term()
            self.batch = self._batch(self.department, suffix="API")

            admin_user = User.objects.create_user(
                username="tt_admin", email="tt_admin@test.com", password="pw12345!",
            )
            admin_user.groups.add(Group.objects.get(name="Management"))
            self.admin_token = RefreshToken.for_user(admin_user)
            self.admin_token["tenant_schema"] = self.tenant.schema_name

            faculty_user = User.objects.create_user(
                username="tt_faculty", email="tt_faculty@test.com", password="pw12345!",
            )
            faculty_user.groups.add(Group.objects.get(name="Faculty"))
            self.faculty_token = RefreshToken.for_user(faculty_user)
            self.faculty_token["tenant_schema"] = self.tenant.schema_name

    def _auth(self, token):
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

    def test_faculty_cannot_trigger_generation(self):
        response = self.client.post(
            reverse("timetable-generate"), {"term_id": self.term.id}, format="json", **self._auth(self.faculty_token),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_generate_requires_term_id(self):
        response = self.client.post(reverse("timetable-generate"), format="json", **self._auth(self.admin_token))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_generate_queues_run(self):
        response = self.client.post(
            reverse("timetable-generate"), {"term_id": self.term.id}, format="json", **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_202_ACCEPTED)
        self.assertEqual(response.data["status"], "pending")
        with schema_context(self.tenant.schema_name):
            self.assertEqual(TimetableGenerationRun.objects.filter(term=self.term).count(), 1)

    def test_apply_flips_draft_schedules_live(self):
        with schema_context(self.tenant.schema_name):
            faculty = self._faculty(self.department, "apply")
            course = self._course(self.department, "apply1")
            classroom = self._classroom("apply")
            run = TimetableGenerationRun.objects.create(term=self.term, status="completed")
            Schedule.objects.create(
                course=course, faculty=faculty, classroom=classroom,
                day_of_week="Monday", start_time="09:00", end_time="10:00",
                semester=self.term.name, academic_year=self.term.academic_year.name, term=self.term,
                is_draft=True, generation_run=run,
            )

        response = self.client.post(
            reverse("timetablegenerationrun-apply", args=[run.id]), **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "applied")
        with schema_context(self.tenant.schema_name):
            self.assertTrue(Schedule.objects.filter(generation_run=run, is_draft=False).exists())

    def test_apply_rejects_non_completed_run(self):
        with schema_context(self.tenant.schema_name):
            run = TimetableGenerationRun.objects.create(term=self.term, status="pending")
        response = self.client.post(
            reverse("timetablegenerationrun-apply", args=[run.id]), **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_discard_deletes_draft_schedules(self):
        with schema_context(self.tenant.schema_name):
            faculty = self._faculty(self.department, "discard")
            course = self._course(self.department, "discard1")
            classroom = self._classroom("discard")
            run = TimetableGenerationRun.objects.create(term=self.term, status="completed")
            Schedule.objects.create(
                course=course, faculty=faculty, classroom=classroom,
                day_of_week="Tuesday", start_time="10:00", end_time="11:00",
                semester=self.term.name, academic_year=self.term.academic_year.name, term=self.term,
                is_draft=True, generation_run=run,
            )

        response = self.client.post(
            reverse("timetablegenerationrun-discard", args=[run.id]), **self._auth(self.admin_token),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["status"], "discarded")
        with schema_context(self.tenant.schema_name):
            self.assertEqual(Schedule.objects.filter(generation_run=run).count(), 0)

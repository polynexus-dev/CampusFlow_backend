"""
Tests for Roles & Permissions: module actions, data scope and custom roles
(services/rbac.py, views/rbac.py, RequiresModule / RequiresAction).
"""

import datetime

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    AcademicYear, Batch, Course, CourseOffering, Department, Program, Regulation, Term,
)
from .models.audit import AuditLog
from .models.module_permissions import TenantModulePermission
from .models.offerings import StudentCourseRegistration
from .models.profile import AdministratorProfile, DepartmentHeadProfile, StudentProfile, TeachingStaffProfile
from .models.risk_score import StudentRiskScore
from .permissions import get_user_group

PASSWORD = "pw12345!"


class _RbacFixtureMixin:
    def _build_fixture(self):
        self.tenant.subscribed_modules = ["announcements", "at-risk-prediction", "fees"]
        self.tenant.save(update_fields=["subscribed_modules"])

        self.cse = Department.objects.create(name="Computer Science", code="CSE")
        self.mech = Department.objects.create(name="Mechanical", code="MECH")

        self.admin = self._user("admin_a", "Administrator")
        AdministratorProfile.objects.create(user=self.admin, employee_id="ADM-1", status="active")
        self.faculty = self._user("faculty_a", "Faculty")
        TeachingStaffProfile.objects.create(
            user=self.faculty, employee_id="FAC-1", department=self.cse, status="active",
        )
        self.taught = self._student("stu_taught", self.cse)
        self.same_dept = self._student("stu_dept", self.cse)
        self.other_dept = self._student("stu_other", self.mech)
        for student in (self.taught, self.same_dept, self.other_dept):
            StudentRiskScore.objects.create(student=student, risk_score=50, risk_tier="medium")

        year = AcademicYear.objects.create(
            name="2026-2027", start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2027, 6, 30),
            is_current=True,
        )
        today = datetime.date.today()
        term = Term.objects.create(
            academic_year=year, name="Odd", kind=Term.KIND_ODD, sequence=1,
            start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=90),
            is_current=True,
        )
        program = Program.objects.create(name="B.Tech CSE", code="BTCSE", department=self.cse)
        regulation = Regulation.objects.create(program=program, code="R2026", effective_from_year=2026)
        batch = Batch.objects.create(program=program, regulation=regulation, admission_year=2026, name="2026-2030")
        course = Course.objects.create(course_code="CS301", course_name="Data Structures", department=self.cse)
        offering = CourseOffering.objects.create(course=course, term=term, batch=batch, faculty=self.faculty, is_active=True)
        StudentCourseRegistration.objects.create(student=self.taught, offering=offering, term=term)

    def _user(self, username, role):
        user = User.objects.create_user(username=username, password=PASSWORD)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def _student(self, username, department):
        user = self._user(username, "student")
        return StudentProfile.objects.create(user=user, student_id=username, department=department, status="active")

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

    def _role_id(self, name):
        return Group.objects.get_or_create(name=name)[0].id

    def _patch_role(self, name, body, user=None):
        return self.client.patch(
            reverse("rbac-role-detail", args=[self._role_id(name)]), body,
            content_type="application/json", **self._auth(user or self.admin),
        )

    def _all_codes_for(self, name):
        response = self.client.get(reverse("rbac-roles"), **self._auth(self.admin))
        return next(r for r in response.data["roles"] if r["name"] == name)["permissions"]

    def _post_announcement(self, user):
        return self.client.post(
            reverse("announcement-list-create"), {"title": "Hello", "content": "World"},
            content_type="application/json", **self._auth(user),
        )

    def _at_risk_ids(self, user):
        response = self.client.get(reverse("analytics-at-risk-students"), **self._auth(user))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return {row["student"] for row in response.data}


class ModuleActionTests(_RbacFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build_fixture()

    def test_untouched_role_keeps_full_access(self):
        self.assertEqual(self._post_announcement(self.faculty).status_code, status.HTTP_201_CREATED)

    def test_removing_add_blocks_writes_but_not_reads(self):
        codes = [c for c in self._all_codes_for("Faculty") if c != "announcements.add"]
        self.assertEqual(self._patch_role("Faculty", {"permissions": codes}).status_code, status.HTTP_200_OK)

        self.assertEqual(self._post_announcement(self.faculty).status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(reverse("announcement-list-create"), **self._auth(self.faculty))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_removing_view_removes_the_module(self):
        codes = [c for c in self._all_codes_for("Faculty") if not c.startswith("at-risk-prediction.")]
        self._patch_role("Faculty", {"permissions": codes})

        response = self.client.get(reverse("analytics-at-risk-students"), **self._auth(self.faculty))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(reverse("user-allowed-modules"), **self._auth(self.faculty))
        self.assertNotIn("at-risk-prediction", response.data["allowed_modules"])

    def test_core_module_can_be_taken_away(self):
        """ROLE_DEFAULT_MODULES used to force non-premium modules back on."""
        codes = [c for c in self._all_codes_for("Faculty") if not c.startswith("student.")]
        self._patch_role("Faculty", {"permissions": codes})

        response = self.client.get(reverse("student_user_profile"), **self._auth(self.faculty))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(reverse("user-allowed-modules"), **self._auth(self.faculty))
        self.assertNotIn("student", response.data["allowed_modules"])

    def test_removing_add_blocks_student_registration(self):
        codes = [c for c in self._all_codes_for("Faculty") if c != "student.add"]
        self._patch_role("Faculty", {"permissions": codes})

        response = self.client.post(
            reverse("student_registration"), {}, content_type="application/json", **self._auth(self.faculty),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_allowed_modules_reports_narrowed_actions(self):
        self._patch_role("Faculty", {"permissions": ["announcements.view"]})

        response = self.client.get(reverse("user-allowed-modules"), **self._auth(self.faculty))
        self.assertEqual(response.data["module_actions"]["announcements"], ["view"])

    def test_allowed_modules_reports_nothing_for_an_untouched_role_or_admin(self):
        TenantModulePermission.objects.create(group_name="Administrator", module_actions={"fees": []})

        for user in (self.faculty, self.admin):
            response = self.client.get(reverse("user-allowed-modules"), **self._auth(user))
            self.assertEqual(response.data["module_actions"], {})

    def test_write_action_implies_view(self):
        response = self._patch_role("Faculty", {"permissions": ["announcements.add"]})
        self.assertIn("announcements.view", response.data["permissions"])

    def test_unknown_code_is_rejected(self):
        response = self._patch_role("Faculty", {"permissions": ["fees.steal"]})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        response = self._patch_role("Faculty", {"permissions": ["payroll.view"]})  # not subscribed
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_admin_roles_cannot_be_narrowed(self):
        response = self._patch_role("Administrator", {"permissions": []})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_admin_cannot_edit_roles(self):
        response = self._patch_role("Faculty", {"data_scope": "all"}, user=self.faculty)
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        response = self.client.get(reverse("rbac-roles"), **self._auth(self.faculty))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_module_toggle_screen_overrides_actions(self):
        self._patch_role("Faculty", {"permissions": []})

        response = self.client.post(
            reverse("role-module-permissions"), {"group_name": "Faculty", "allowed_modules": ["announcements"]},
            content_type="application/json", **self._auth(self.admin),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._post_announcement(self.faculty).status_code, status.HTTP_201_CREATED)


class DepartmentHeadStudentEditTests(_RbacFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build_fixture()
            self.hod = self._user("hod_cse", "Department Head")
            DepartmentHeadProfile.objects.create(user=self.hod, employee_id="HOD-1", department=self.cse, status="active")

    def _edit(self, student):
        return self.client.put(
            reverse("student_user_profile"), {"id": student.id, "contact_number": "9000000000"},
            content_type="application/json", **self._auth(self.hod),
        )

    def test_can_edit_a_student_in_their_department(self):
        self.assertEqual(self._edit(self.same_dept).status_code, status.HTTP_200_OK)

    def test_cannot_edit_a_student_in_another_department(self):
        self.assertEqual(self._edit(self.other_dept).status_code, status.HTTP_403_FORBIDDEN)


class DataScopeTests(_RbacFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build_fixture()
        self.everyone = {self.taught.id, self.same_dept.id, self.other_dept.id}

    def test_default_scope_sees_everyone(self):
        self.assertEqual(self._at_risk_ids(self.faculty), self.everyone)

    def test_department_scope(self):
        self._patch_role("Faculty", {"data_scope": "department"})
        self.assertEqual(self._at_risk_ids(self.faculty), {self.taught.id, self.same_dept.id})

    def test_own_scope_is_students_they_teach(self):
        self._patch_role("Faculty", {"data_scope": "own"})
        self.assertEqual(self._at_risk_ids(self.faculty), {self.taught.id})

    def test_scope_covers_the_student_directory_and_its_count(self):
        self._patch_role("Faculty", {"data_scope": "own"})
        url = reverse("student_user_profile")

        count = self.client.get(url, {"count_only": "true"}, **self._auth(self.faculty))
        self.assertEqual(count.data["count"], 1)

    def test_scope_blocks_a_direct_lookup_by_id(self):
        self._patch_role("Faculty", {"data_scope": "department"})

        allowed = self.client.get(
            reverse("analytics-student-progress"), {"student_id": self.same_dept.id}, **self._auth(self.faculty),
        )
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        hidden = self.client.get(
            reverse("analytics-student-progress"), {"student_id": self.other_dept.id}, **self._auth(self.faculty),
        )
        self.assertEqual(hidden.status_code, status.HTTP_404_NOT_FOUND)

    def test_department_scope_without_a_department_sees_nothing(self):
        TeachingStaffProfile.objects.filter(user=self.faculty).update(department=None)
        self._patch_role("Faculty", {"data_scope": "department"})
        self.assertEqual(self._at_risk_ids(self.faculty), set())

    def test_admin_ignores_scope(self):
        TenantModulePermission.objects.create(group_name="Administrator", data_scope="own")
        self.assertEqual(self._at_risk_ids(self.admin), self.everyone)


class CustomRoleTests(_RbacFixtureMixin, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build_fixture()

    def _create_role(self, name="Exam Clerk", based_on="Faculty"):
        return self.client.post(
            reverse("rbac-roles"), {"name": name, "based_on": based_on},
            content_type="application/json", **self._auth(self.admin),
        )

    def _add_member(self, role_id, user):
        return self.client.post(
            reverse("rbac-role-members", args=[role_id]), {"user_id": user.id},
            content_type="application/json", **self._auth(self.admin),
        )

    def test_custom_role_passes_its_base_roles_checks(self):
        role = self._create_role().data
        self.assertEqual(self._add_member(role["id"], self.faculty).status_code, status.HTTP_201_CREATED)

        self.assertEqual(get_user_group(self.faculty), "Faculty")
        self.assertEqual(self.faculty.groups.first().name, "Exam Clerk")
        self.assertEqual(self._post_announcement(self.faculty).status_code, status.HTTP_201_CREATED)

    def test_custom_role_permissions_do_not_touch_the_base_role(self):
        role = self._create_role().data
        self._add_member(role["id"], self.faculty)
        other = self._user("faculty_b", "Faculty")

        self._patch_role("Exam Clerk", {"permissions": ["announcements.view"]})

        self.assertEqual(self._post_announcement(self.faculty).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._post_announcement(other).status_code, status.HTTP_201_CREATED)

    def test_member_can_log_in(self):
        role = self._create_role().data
        self._add_member(role["id"], self.faculty)

        response = self.client.post(
            reverse("token_obtain_pair"), {"username": "faculty_a", "password": PASSWORD},
            content_type="application/json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(response.data["roleName"], "Exam Clerk")

    def test_role_cannot_be_based_on_an_admin_role(self):
        response = self._create_role(based_on="Administrator")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_name_is_rejected(self):
        self.assertEqual(self._create_role(name="faculty").status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_base_role_accounts_can_join(self):
        role = self._create_role().data
        response = self._add_member(role["id"], self.admin)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(self.admin.groups.first().name, "Administrator")

    def test_removing_a_member_returns_them_to_the_base_role(self):
        role = self._create_role().data
        self._add_member(role["id"], self.faculty)

        response = self.client.delete(
            reverse("rbac-role-member-detail", args=[role["id"], self.faculty.id]), **self._auth(self.admin),
        )
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self.faculty.groups.first().name, "Faculty")

    def test_role_change_is_audited(self):
        role = self._create_role().data
        self._add_member(role["id"], self.faculty)

        entry = AuditLog.objects.filter(model_name="User", object_id=str(self.faculty.id)).latest("id")
        self.assertEqual(entry.changes["role"], {"old": "Faculty", "new": "Exam Clerk"})

    def test_delete_needs_an_empty_custom_role(self):
        role = self._create_role().data
        self._add_member(role["id"], self.faculty)
        url = reverse("rbac-role-detail", args=[role["id"]])

        self.assertEqual(self.client.delete(url, **self._auth(self.admin)).status_code, status.HTTP_400_BAD_REQUEST)
        self.client.delete(reverse("rbac-role-member-detail", args=[role["id"], self.faculty.id]), **self._auth(self.admin))
        self.assertEqual(self.client.delete(url, **self._auth(self.admin)).status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(TenantModulePermission.objects.filter(group_name="Exam Clerk").exists())

    def test_built_in_role_cannot_be_deleted(self):
        response = self.client.delete(
            reverse("rbac-role-detail", args=[self._role_id("Faculty")]), **self._auth(self.admin),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

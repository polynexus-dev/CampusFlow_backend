"""
CampusFlow Role-Based Access Control (RBAC) Permissions
=========================================================

Auth Flow:
  1. SaaS Admin (superuser, public schema) → creates Colleges (Tenants)
  2. College Admin (Management group, tenant schema) → created by SaaS Admin
  3. Department → created only by SaaS Admin OR College Admin (Management/Administrator)
     ↳ No Department = no users of any role can be created
  4. All other users (Faculty, Support Staff, Department Head, Student)
     → created only by College Admin (Management/Administrator) AFTER a department exists

Role hierarchy (highest → lowest):
  SaaS Admin (is_superuser) > Management > Administrator > Department Head > Faculty > Support Staff > Student
"""

from rest_framework.permissions import BasePermission
from django.db import connection


def get_user_group(user):
    """Returns the name of the user's first group, or None."""
    if user.groups.exists():
        return user.groups.first().name
    return None


def is_saas_admin(user):
    """SaaS Admin = Django superuser (lives in the public schema)."""
    return user.is_authenticated and user.is_superuser


def is_college_admin(user):
    """College Admin = Management or Administrator group in a tenant schema."""
    if not user.is_authenticated:
        return False
    group = get_user_group(user)
    return group in ('Management', 'Administrator')


def is_saas_or_college_admin(user):
    return is_saas_admin(user) or is_college_admin(user)


def is_faculty_or_above(user):
    """Faculty, Department Head, Administrator, Management, or SaaS Admin."""
    if not user.is_authenticated:
        return False
    if is_saas_admin(user):
        return True
    group = get_user_group(user)
    return group in ('Management', 'Administrator', 'Department Head', 'Faculty')


# ─────────────────────────────────────────────
# Permission classes (use in views)
# ─────────────────────────────────────────────

class IsSaaSAdmin(BasePermission):
    """Only the SaaS superuser can access this endpoint."""
    message = "Only the SaaS Admin can perform this action."

    def has_permission(self, request, view):
        return is_saas_admin(request.user)


class IsCollegeAdmin(BasePermission):
    """Only Management or Administrator roles can access this endpoint."""
    message = "Only College Admins (Management or Administrator) can perform this action."

    def has_permission(self, request, view):
        return request.user.is_authenticated and is_college_admin(request.user)


class IsSaaSOrCollegeAdmin(BasePermission):
    """SaaS Admin OR College Admin can access this endpoint (e.g. department management)."""
    message = "Only SaaS Admin or College Admins can perform this action."

    def has_permission(self, request, view):
        return request.user.is_authenticated and is_saas_or_college_admin(request.user)


class IsFacultyOrAbove(BasePermission):
    """Faculty, HOD, Administrator, Management, and SaaS Admin."""
    message = "You do not have sufficient privileges to perform this action."

    def has_permission(self, request, view):
        return is_faculty_or_above(request.user)


class IsNotStudent(BasePermission):
    """Any authenticated user except students."""
    message = "Students are not allowed to access this resource."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if is_saas_admin(request.user):
            return True
        group = get_user_group(request.user)
        return group != 'student'


class DepartmentExistsForUserCreation(BasePermission):
    """
    Blocks user creation (for any non-SaaS-Admin) when no department exists.
    The SaaS Admin is exempt — they create the first College Admin directly.
    """
    message = "Cannot create users: no departments exist yet. Create a department first."

    def has_permission(self, request, view):
        # SaaS admin bypasses this gate
        if is_saas_admin(request.user):
            return True

        # Only enforce on write operations
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True

        from campusflow_app.models.department import Department
        if not Department.objects.exists():
            return False
        return True


class CanCreateCollegeAdmin(BasePermission):
    """
    Only the SaaS Admin can create the first Management/Administrator user in a tenant.
    Once a College Admin exists, they can also promote/create other admins.
    """
    message = "Only the SaaS Admin can create College Admin accounts."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if is_saas_admin(request.user):
            return True
        # An existing College Admin can also create other admin/management accounts
        return is_college_admin(request.user)


# ─────────────────────────────────────────────
# Additional permission classes for specific resources
# ─────────────────────────────────────────────

class CanCreateLecture(BasePermission):
    """
    Lectures can be created/edited/deleted by:
      - SaaS Admin
      - College Admin (Management / Administrator)
      - Faculty (they create their own lectures)
      - Department Head (they oversee their dept lectures)
    Students and Support Staff CANNOT create/modify lectures.
    """
    message = "Only Faculty, Department Heads, or College Admins can manage lectures."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True  # all authenticated users can read
        if is_saas_admin(request.user):
            return True
        group = get_user_group(request.user)
        return group in ('Management', 'Administrator', 'Department Head', 'Faculty')


class CanMarkAttendanceManually(BasePermission):
    """
    Manual attendance marking (by staff on behalf of student) is only for:
      - SaaS Admin, Management, Administrator, Faculty, Department Head
    Students cannot manually mark another student's attendance.
    """
    message = "Only Faculty or College Admins can manually mark attendance."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if is_saas_admin(request.user):
            return True
        group = get_user_group(request.user)
        return group in ('Management', 'Administrator', 'Department Head', 'Faculty')


class CanManageLocation(BasePermission):
    """
    Locations (QR check-in points) can only be created/modified by College Admins or SaaS Admin.
    Anyone authenticated can GET locations (needed to scan QR codes).
    """
    message = "Only College Admins or SaaS Admin can manage locations."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if request.method in ('GET', 'HEAD', 'OPTIONS'):
            return True
        return is_saas_or_college_admin(request.user)


class CanGenerateQR(BasePermission):
    """
    QR code generation is restricted to College Admins, Faculty, and Department Heads.
    Students cannot generate QR codes.
    """
    message = "Only Faculty, Department Heads, or College Admins can generate QR codes."

    def has_permission(self, request, view):
        if not request.user.is_authenticated:
            return False
        if is_saas_admin(request.user):
            return True
        group = get_user_group(request.user)
        return group in ('Management', 'Administrator', 'Department Head', 'Faculty')

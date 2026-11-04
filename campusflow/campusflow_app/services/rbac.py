"""
campusflow_app/services/rbac.py

What a role may do inside a module, and how much of the college's data it sees.

A role holds a module or it doesn't (TenantModulePermission.allowed_modules,
see views/module_permissions.py). On top of that a College Admin can narrow it:

  module_actions  view/add/change/delete per module, applied to every endpoint
                  from its HTTP method by RequiresModule / RequiresAction
  data_scope      all / department / own, applied to student data through
                  scope_students()

These only ever narrow. Each view's own role checks (IsFacultyOrAbove,
ManagedBy, ...) still run, so ticking a box can't hand a role something its
built-in rules forbid. College Admins are never narrowed: they are what lets
anyone fix a bad setting.

Permissions are per module rather than Django's per model because almost every
endpoint here is a plain APIView with no queryset for DjangoModelPermissions to
read, while nearly all of them already declare their module.
"""

from ..models.module_permissions import TenantModulePermission
from ..models.offerings import StudentCourseRegistration
from ..permissions import get_user_role_name, is_college_admin, is_saas_admin

ACTIONS = ("view", "add", "change", "delete")

METHOD_ACTIONS = {"POST": "add", "PUT": "change", "PATCH": "change", "DELETE": "delete"}


def action_for_method(method):
    return METHOD_ACTIONS.get(method, "view")


def can_perform(user, module_key, action):
    """Whether `user`'s role may perform `action` in the module, going by its explicit settings."""
    if is_saas_admin(user) or is_college_admin(user):
        return True
    role = TenantModulePermission.objects.filter(group_name=get_user_role_name(user)).first()
    if role is None or module_key not in role.module_actions:
        return True
    return action in role.module_actions[module_key]


def module_actions_for(user):
    """The modules `user`'s role was narrowed in — what the frontend needs to hide buttons."""
    if is_saas_admin(user) or is_college_admin(user):
        return {}
    role = TenantModulePermission.objects.filter(group_name=get_user_role_name(user)).first()
    return role.module_actions if role else {}


def data_scope_for(user):
    if is_saas_admin(user) or is_college_admin(user):
        return TenantModulePermission.SCOPE_ALL
    scope = TenantModulePermission.objects.filter(
        group_name=get_user_role_name(user),
    ).values_list("data_scope", flat=True).first()
    return scope or TenantModulePermission.SCOPE_ALL


def user_department_id(user):
    for relation in ("department_head_profile", "teaching_staff_profile", "non_teaching_staff_profile"):
        profile = getattr(user, relation, None)
        if profile is not None:
            return profile.department_id
    return None


def scope_students(queryset, user, student_path=""):
    """
    Narrows `queryset` to the students `user`'s role may see. `student_path` is
    the lookup from the queryset's model to StudentProfile, e.g. "student__".
    A role with nothing to match (no department, no classes) sees nothing.
    """
    scope = data_scope_for(user)
    if scope == TenantModulePermission.SCOPE_ALL:
        return queryset
    if scope == TenantModulePermission.SCOPE_DEPARTMENT:
        department_id = user_department_id(user)
        if department_id is None:
            return queryset.none()
        return queryset.filter(**{f"{student_path}department_id": department_id})
    taught = StudentCourseRegistration.objects.filter(offering__faculty=user).values("student_id")
    return queryset.filter(**{f"{student_path}id__in": taught})

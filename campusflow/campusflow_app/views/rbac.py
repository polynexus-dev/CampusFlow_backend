"""
Roles & Permissions: the College Admin screen over TenantModulePermission.

    GET    /api/tenant/rbac/roles/                     every role + the module catalog
    POST   /api/tenant/rbac/roles/                     {name, based_on}
    PATCH  /api/tenant/rbac/roles/<id>/                {permissions?, data_scope?}
    DELETE /api/tenant/rbac/roles/<id>/                custom roles with no members
    GET    /api/tenant/rbac/roles/<id>/members/        members + who could be added
    POST   /api/tenant/rbac/roles/<id>/members/        {user_id}
    DELETE /api/tenant/rbac/roles/<id>/members/<uid>/  back to the base role

A permission is a "module.action" code, e.g. "fees.add". See services/rbac.py
for what they mean and how they are enforced.

College Admins only, unlike Module Assignment's delegable access: whoever can
edit roles can give themselves anything, so this isn't something to hand down.
"""

from django.contrib.auth.models import Group, User
from django.db import connection, transaction
from django.db.models import Count, ProtectedError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.audit import AuditLog
from ..models.module_permissions import TenantModulePermission
from ..permissions import (
    BUILT_IN_ROLES, NON_TEACHING_STAFF_ROLES, SUPERVISOR_ROLE, IsSaaSOrCollegeAdmin, get_user_group,
)
from ..services.rbac import ACTIONS
from .module_permissions import PREMIUM_MODULES, get_role_modules

ADMIN_ROLES = ("Management", "Administrator", SUPERVISOR_ROLE)

# Managed elsewhere: CA through CA Engagements, guardians through their links.
HIDDEN_ROLES = ("CA", "guardian", "SaaS Admin")

# A custom role runs on its base role's account type, so it can only be based on
# a staff role, and never on an admin role, which would make it one.
BASE_ROLES = ("Principal", "Department Head", "Faculty", *NON_TEACHING_STAFF_ROLES)

MODULE_CATALOG = [
    ("People", {"student": "Students", "staff": "Staff"}),
    ("Academics", {
        "academics": "Academic Calendar", "transcript": "Transcripts", "exams": "Exams & Marks",
        "syllabus-tracker": "Syllabus Tracker", "assignments": "Assignments",
        "valuation": "Valuation", "ai-valuation": "AI Valuation",
    }),
    ("Daily Operations", {
        "attendance": "Attendance", "schedule": "Schedule",
        "timetable-generation": "Timetable Generation", "leave": "Leave", "payroll": "Payroll",
    }),
    ("Campus ERP", {
        "fees": "Fees", "scholarship": "Scholarships", "clearance": "Clearance",
        "bus-tracking": "Bus Tracking", "hostel": "Hostel", "admissions": "Admissions",
        "tpo": "Placements", "library": "Library", "inventory": "Inventory",
    }),
    ("Compliance", {"compliance-center": "Compliance Center", "ledger": "Financial Ledger"}),
    ("Insights", {
        "analytics": "Analytics", "at-risk-prediction": "At-Risk Prediction",
        "announcements": "Announcements",
    }),
]


def _available_modules():
    """Catalog modules this college can use: core ones, plus subscribed premium ones."""
    subscribed = {
        m.lower().replace(" ", "-") for m in getattr(connection.tenant, "subscribed_modules", None) or []
    }
    return [
        key for _, modules in MODULE_CATALOG for key in modules
        if key not in PREMIUM_MODULES or key in subscribed
    ]


def _role_codes(group_name, row, available):
    if group_name in ADMIN_ROLES:
        return [f"{key}.{action}" for key in available for action in ACTIONS]
    held = get_role_modules(group_name)
    explicit = row.module_actions if row else {}
    return [
        f"{key}.{action}"
        for key in available if key in held
        for action in explicit.get(key, ACTIONS)
    ]


def _serialize_role(group, rows, available):
    row = rows.get(group.name)
    is_admin = group.name in ADMIN_ROLES
    codes = _role_codes(group.name, row, available)
    return {
        "id": group.id,
        "name": group.name,
        "is_custom": group.name not in BUILT_IN_ROLES,
        "based_on": row.based_on if row else "",
        "data_scope": TenantModulePermission.SCOPE_ALL if is_admin else (row.data_scope if row else TenantModulePermission.SCOPE_ALL),
        "permissions": codes,
        "member_count": group.member_count,
        "locked_reason": "College admin roles always have full access." if is_admin else "",
        # Students only ever reach their own records, whatever this says.
        "scope_editable": not is_admin and group.name != "student",
    }


def _role_sort_key(group):
    if group.name in ADMIN_ROLES:
        return (0, group.name)
    return (2 if group.name not in BUILT_IN_ROLES else 1, group.name.lower())


def _roles_queryset():
    return Group.objects.exclude(name__in=HIDDEN_ROLES).annotate(member_count=Count("user"))


class RoleListCreateView(APIView):
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]

    def get(self, request):
        available = _available_modules()
        rows = {row.group_name: row for row in TenantModulePermission.objects.all()}
        return Response({
            "roles": [_serialize_role(g, rows, available) for g in sorted(_roles_queryset(), key=_role_sort_key)],
            "catalog": [
                {"group": label, "modules": [{"key": k, "label": v} for k, v in modules.items() if k in available]}
                for label, modules in MODULE_CATALOG
            ],
            "scopes": [{"value": v, "label": label} for v, label in TenantModulePermission.SCOPE_CHOICES],
            "base_roles": BASE_ROLES,
        })

    def post(self, request):
        name = str(request.data.get("name", "")).strip()
        based_on = request.data.get("based_on")
        if not 2 <= len(name) <= 50:
            return Response({"error": "Role name must be between 2 and 50 characters."}, status=status.HTTP_400_BAD_REQUEST)
        if based_on not in BASE_ROLES:
            return Response({"error": "Choose which staff role this one is based on."}, status=status.HTTP_400_BAD_REQUEST)
        if Group.objects.filter(name__iexact=name).exists() or name.lower() in {r.lower() for r in BUILT_IN_ROLES}:
            return Response({"error": f"Role '{name}' already exists."}, status=status.HTTP_400_BAD_REQUEST)

        base = TenantModulePermission.objects.filter(group_name=based_on).first()
        with transaction.atomic():
            group = Group.objects.create(name=name)
            row = TenantModulePermission.objects.create(
                group_name=name,
                based_on=based_on,
                allowed_modules=base.allowed_modules if base else [],
                module_actions=base.module_actions if base else {},
                data_scope=base.data_scope if base else TenantModulePermission.SCOPE_ALL,
            )
        group.member_count = 0
        return Response(_serialize_role(group, {name: row}, _available_modules()), status=status.HTTP_201_CREATED)


def _get_role(pk):
    return _roles_queryset().filter(pk=pk).first()


def _parse_codes(codes, available):
    """{module: [actions]} for every available module, or None if `codes` has an unknown one."""
    actions = {key: [] for key in available}
    for code in codes:
        key, _, action = str(code).partition(".")
        if key not in actions or action not in ACTIONS:
            return None
        actions[key].append(action)
    for key, granted in actions.items():
        # Nothing here can be changed by a role that can't open it.
        if granted and "view" not in granted:
            granted.append("view")
        actions[key] = [a for a in ACTIONS if a in granted]
    return actions


class RoleDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]

    def patch(self, request, pk):
        group = _get_role(pk)
        if group is None:
            return Response({"error": "Role not found."}, status=status.HTTP_404_NOT_FOUND)
        if group.name in ADMIN_ROLES:
            return Response({"error": "College admin roles always have full access."}, status=status.HTTP_400_BAD_REQUEST)

        row, _ = TenantModulePermission.objects.get_or_create(group_name=group.name)

        if "data_scope" in request.data:
            scope = request.data["data_scope"]
            if scope not in dict(TenantModulePermission.SCOPE_CHOICES) or group.name == "student":
                return Response({"error": "Invalid data scope for this role."}, status=status.HTTP_400_BAD_REQUEST)
            row.data_scope = scope

        if "permissions" in request.data:
            codes = request.data["permissions"]
            available = _available_modules()
            actions = _parse_codes(codes, available) if isinstance(codes, list) else None
            if actions is None:
                return Response({"error": "Send a list of known 'module.action' codes."}, status=status.HTTP_400_BAD_REQUEST)
            row.module_actions = {**row.module_actions, **actions}
            kept = [m for m in row.allowed_modules if m.lower().replace(" ", "-") not in actions]
            row.allowed_modules = sorted(
                {"dashboard", "settings", "profile", *kept, *(key for key, granted in actions.items() if granted)}
            )

        row.save()
        return Response(_serialize_role(group, {group.name: row}, _available_modules()))

    def delete(self, request, pk):
        group = _get_role(pk)
        if group is None:
            return Response({"error": "Role not found."}, status=status.HTTP_404_NOT_FOUND)
        if group.name in BUILT_IN_ROLES:
            return Response({"error": "Built-in roles can't be deleted."}, status=status.HTTP_400_BAD_REQUEST)
        if group.member_count:
            return Response({"error": "Move everyone out of this role before deleting it."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            with transaction.atomic():
                TenantModulePermission.objects.filter(group_name=group.name).delete()
                group.delete()
        except ProtectedError:
            return Response({"error": "This role is still used by a clearance desk."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(status=status.HTTP_204_NO_CONTENT)


def _person(user):
    return {"id": user.id, "name": user.get_full_name() or user.username, "username": user.username}


def _set_role(request, user, group, previous):
    """Group changes aren't seen by the audit signals, so this is logged by hand."""
    user.groups.set([group])
    AuditLog.objects.create(
        user=request.user,
        action="UPDATE",
        model_name="User",
        object_id=str(user.pk),
        object_repr=f"{user.username} role changed",
        changes={"role": {"old": previous, "new": group.name}},
        endpoint=request.path,
    )


def _custom_role(pk):
    group = _get_role(pk)
    if group is None or group.name in BUILT_IN_ROLES:
        return None, None
    row = TenantModulePermission.objects.filter(group_name=group.name).first()
    return (group, row) if row and row.based_on else (None, None)


class RoleMembersView(APIView):
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]

    def get(self, request, pk):
        group = _get_role(pk)
        if group is None:
            return Response({"error": "Role not found."}, status=status.HTTP_404_NOT_FOUND)
        members = group.user_set.order_by("first_name", "username")
        row = TenantModulePermission.objects.filter(group_name=group.name).first()
        eligible = User.objects.none()
        if row and row.based_on:
            # Sibling custom roles on the same base are the same kind of account.
            same_base = TenantModulePermission.objects.filter(based_on=row.based_on).exclude(group_name=group.name)
            names = [row.based_on, *same_base.values_list("group_name", flat=True)]
            eligible = User.objects.filter(
                groups__name__in=names, is_superuser=False, is_active=True,
            ).distinct().order_by("first_name", "username")
        return Response({
            "members": [_person(u) for u in members[:500]],
            "eligible": [_person(u) for u in eligible[:500]],
        })

    def post(self, request, pk):
        group, row = _custom_role(pk)
        if group is None:
            return Response({"error": "People can only be moved into custom roles."}, status=status.HTTP_400_BAD_REQUEST)
        target = User.objects.filter(pk=request.data.get("user_id"), is_superuser=False).first()
        if target is None:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        previous = get_user_group(target)
        if previous != row.based_on:
            return Response(
                {"error": f"This role is based on {row.based_on}, so only {row.based_on} accounts can join it."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        _set_role(request, target, group, target.groups.first().name)
        return Response(_person(target), status=status.HTTP_201_CREATED)


class RoleMemberDetailView(APIView):
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]

    def delete(self, request, pk, user_id):
        group, row = _custom_role(pk)
        if group is None:
            return Response({"error": "Role not found."}, status=status.HTTP_404_NOT_FOUND)
        target = group.user_set.filter(pk=user_id).first()
        if target is None:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)
        base, _ = Group.objects.get_or_create(name=row.based_on)
        _set_role(request, target, base, group.name)
        return Response(status=status.HTTP_204_NO_CONTENT)

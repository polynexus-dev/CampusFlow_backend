from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, BasePermission
from django.db import connection, transaction
from tenants.models import Tenant
from campusflow_app.models import TenantModulePermission
from campusflow_app.permissions import IsSaaSAdmin, IsCollegeAdmin, get_user_group

# Default modules hierarchy list for validation
ALL_ERP_MODULES = [
    "management", "administrator", "department", "room", "staff",
    "student", "attendance", "schedule", "leave", "payroll",
    "exams", "analytics", "announcements", "audit-logs", "assignments",
    "fees", "bus-tracking", "hostel", "tpo", "library", "inventory", "valuation"
]

ROLE_DEFAULT_MODULES = {
    "SaaS Admin": ["dashboard", "settings"],
    "Management": ALL_ERP_MODULES,
    "Administrator": ALL_ERP_MODULES,
    "Department Head": [
        "dashboard", "department", "room", "staff", "student", "attendance",
        "schedule", "settings", "leave", "exams", "analytics", "announcements",
        "assignments", "bus-tracking", "tpo", "library", "valuation"
    ],
    "Faculty": [
        "dashboard", "attendance", "schedule", "settings", "leave", "exams",
        "announcements", "analytics", "assignments", "bus-tracking", "valuation"
    ],
    "Support Staff": [
        "dashboard", "room", "settings", "leave", "announcements", "hostel",
        "library", "inventory"
    ],
    "student": [
        "dashboard", "attendance", "schedule", "settings", "exams", "announcements",
        "assignments", "fees", "bus-tracking", "hostel", "tpo", "library"
    ]
}



class TenantSubscriptionView(APIView):
    """
    SaaS Admin level: Manage modules subscribed by a Tenant.
    GET /api/tenant/subscriptions/<int:tenant_id>/
    POST /api/tenant/subscriptions/<int:tenant_id>/
    """
    permission_classes = [IsAuthenticated, IsSaaSAdmin]

    def get(self, request, tenant_id):
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            return Response({"error": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({
            "tenant_id": tenant.id,
            "tenant_name": tenant.name,
            "subscribed_modules": tenant.subscribed_modules or []
        })

    def post(self, request, tenant_id):
        try:
            tenant = Tenant.objects.get(id=tenant_id)
        except Tenant.DoesNotExist:
            return Response({"error": "Tenant not found."}, status=status.HTTP_404_NOT_FOUND)

        modules = request.data.get("subscribed_modules", [])
        if not isinstance(modules, list):
            return Response({"error": "subscribed_modules must be a list."}, status=status.HTTP_400_BAD_REQUEST)

        # Validate modules
        invalid_modules = [m for m in modules if m not in ALL_ERP_MODULES]
        if invalid_modules:
            return Response(
                {"error": f"Invalid modules: {', '.join(invalid_modules)}. Valid modules: {', '.join(ALL_ERP_MODULES)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        tenant.subscribed_modules = modules
        tenant.save()

        return Response({
            "message": "Tenant subscriptions updated successfully.",
            "subscribed_modules": tenant.subscribed_modules
        })


class CanManageModulePermissions(BasePermission):
    """
    Permission class allowing access to primary College Admins (Management, Administrator),
    OR any user role that has been explicitly allocated the 'module-assignment' permission.
    """
    def has_permission(self, request, view):
        user = request.user
        if not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        group_name = get_user_group(user)
        if not group_name:
            return False
        if group_name in ('Management', 'Administrator'):
            return True
        try:
            perm = TenantModulePermission.objects.get(group_name=group_name)
            return "module-assignment" in (perm.allowed_modules or [])
        except TenantModulePermission.DoesNotExist:
            return False


class RoleModulePermissionView(APIView):
    """
    College Admin level: Manage active modules for each user role.
    GET /api/tenant/module-permissions/
    POST /api/tenant/module-permissions/
    """
    permission_classes = [IsAuthenticated, CanManageModulePermissions]

    def get(self, request):
        # Subscribed pool for current tenant
        tenant = connection.tenant
        subscribed = getattr(tenant, 'subscribed_modules', None) or []

        from django.contrib.auth.models import Group
        roles = [g.name for g in Group.objects.all().order_by('name')]
        data = []

        subscribed_lower_map = {m.lower().replace(" ", "-"): m for m in subscribed}
        PREMIUM_MODULES = {
            "attendance", "leave", "payroll", "exams", "assignments",
            "fees", "bus-tracking", "hostel", "tpo", "library", "inventory", "valuation", "announcements"
        }

        for role in roles:
            perm, _ = TenantModulePermission.objects.get_or_create(group_name=role)
            allowed = perm.allowed_modules
            if allowed is None:
                allowed = ROLE_DEFAULT_MODULES.get(role) or []
                
            # Filter allowed: 
            # 1. Keep core modules (non-premium)
            # 2. Keep premium modules ONLY if they are subscribed
            filtered_allowed = []
            for m in allowed:
                m_norm = m.lower().replace(" ", "-")
                if m_norm not in PREMIUM_MODULES:
                    filtered_allowed.append(m)
                elif m_norm in subscribed_lower_map:
                    filtered_allowed.append(subscribed_lower_map[m_norm])
                    
            data.append({
                "group_name": role,
                "allowed_modules": filtered_allowed
            })

        return Response({
            "subscribed_modules": subscribed,
            "role_permissions": data
        })

    def post(self, request):
        group_name = request.data.get("group_name")
        allowed_modules = request.data.get("allowed_modules", [])

        if not group_name:
            return Response({"error": "group_name is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(allowed_modules, list):
            return Response({"error": "allowed_modules must be a list."}, status=status.HTTP_400_BAD_REQUEST)

        # Lock organization admin roles from modification by delegated managers
        if group_name in ('Management', 'Administrator'):
            requesting_group = get_user_group(request.user)
            if not request.user.is_superuser and requesting_group not in ('Management', 'Administrator'):
                return Response(
                    {"error": "Permissions for organization admin roles (Management, Administrator) can only be modified by primary admins themselves."}, 
                    status=status.HTTP_403_FORBIDDEN
                )

        from django.contrib.auth.models import Group
        if not Group.objects.filter(name=group_name).exists():
            return Response({"error": f"Invalid group_name. Role '{group_name}' does not exist."}, status=status.HTTP_400_BAD_REQUEST)

        # Intersect with currently subscribed modules to prevent bypass (case-insensitive)
        tenant = connection.tenant
        subscribed = getattr(tenant, 'subscribed_modules', None) or []
        subscribed_lower_map = {m.lower().replace(" ", "-"): m for m in subscribed}
        
        PREMIUM_MODULES = {
            "attendance", "leave", "payroll", "exams", "assignments",
            "fees", "bus-tracking", "hostel", "tpo", "library", "inventory", "valuation", "announcements"
        }
        
        # Get existing permission object
        perm, _ = TenantModulePermission.objects.get_or_create(group_name=group_name)
        existing_allowed = perm.allowed_modules
        if existing_allowed is None:
            existing_allowed = ROLE_DEFAULT_MODULES.get(group_name) or []
            
        # Retain any existing modules that are NOT part of the editable premium modules (e.g. core modules)
        new_allowed = []
        for m in existing_allowed:
            m_norm = m.lower().replace(" ", "-")
            if m_norm not in PREMIUM_MODULES:
                new_allowed.append(m)
                
        # Add the validated premium modules sent from frontend
        for m in allowed_modules:
            m_norm = m.lower().replace(" ", "-")
            if m_norm in subscribed_lower_map:
                new_allowed.append(subscribed_lower_map[m_norm])

        perm.allowed_modules = list(set(new_allowed))
        perm.save()

        return Response({
            "message": f"Module permissions updated for role {group_name}.",
            "group_name": group_name,
            "allowed_modules": perm.allowed_modules
        })


class MyAllowedModulesView(APIView):
    """
    Returns the intersection of the Tenant's subscribed modules and the user's role permissions.
    GET /api/user/allowed-modules/
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        tenant = connection.tenant

        subscribed = getattr(tenant, 'subscribed_modules', None) or []

        # If SaaS Admin (superuser), grant access to all subscribed modules (normalized)
        if user.is_superuser:
            normalized_subscribed = [m.lower().replace(" ", "-") for m in subscribed]
            return Response({
                "role": "SaaS Admin",
                "allowed_modules": normalized_subscribed
            })

        # Resolve role
        group_name = get_user_group(user)
        if not group_name:
            return Response({
                "role": "None",
                "allowed_modules": ["dashboard", "settings", "profile"]
            })

        # Get role default modules
        default_allowed = ROLE_DEFAULT_MODULES.get(group_name) or ["dashboard", "settings", "profile"]

        # Get role allowed modules from db, falling back to defaults
        try:
            perm = TenantModulePermission.objects.get(group_name=group_name)
            allowed = perm.allowed_modules
            if not allowed:
                allowed = default_allowed
        except TenantModulePermission.DoesNotExist:
            allowed = default_allowed


        # Intersect to find final list (case-insensitive, returning lowercase/dash-separated form)
        subscribed_lower = {m.lower().replace(" ", "-") for m in subscribed}
        
        PREMIUM_MODULES = {
            "attendance", "leave", "payroll", "exams", "assignments",
            "fees", "bus-tracking", "hostel", "tpo", "library", "inventory", "valuation", "announcements"
        }
        
        final_modules = []
        
        # 1. Process database allowed list
        for m in allowed:
            m_norm = m.lower().replace(" ", "-")
            if m_norm not in PREMIUM_MODULES:
                final_modules.append(m_norm)
            elif m_norm in subscribed_lower:
                final_modules.append(m_norm)
                
        # 2. Always guarantee all default core modules for the role
        for m in default_allowed:
            m_norm = m.lower().replace(" ", "-")
            if m_norm not in PREMIUM_MODULES and m_norm not in final_modules:
                final_modules.append(m_norm)

        # Always guarantee core basic views
        for core in ["dashboard", "settings", "profile"]:
            if core not in final_modules:
                final_modules.append(core)

        return Response({
            "role": group_name,
            "allowed_modules": final_modules
        })


class CustomRolesView(APIView):
    """
    College Admin level: Manage custom role groups within a Tenant.
    GET /api/tenant/roles/  - List all roles
    POST /api/tenant/roles/ - Create a new custom role
    """
    permission_classes = [IsAuthenticated, CanManageModulePermissions]

    def get(self, request):
        from django.contrib.auth.models import Group
        groups = Group.objects.all().order_by('name')
        return Response({
            "roles": [g.name for g in groups]
        })

    def post(self, request):
        from django.contrib.auth.models import Group
        role_name = request.data.get("role_name", "").strip()

        if not role_name:
            return Response({"error": "role_name is required."}, status=status.HTTP_400_BAD_REQUEST)

        if len(role_name) < 2 or len(role_name) > 50:
            return Response({"error": "Role name must be between 2 and 50 characters."}, status=status.HTTP_400_BAD_REQUEST)

        # Check duplicates case-insensitively
        if Group.objects.filter(name__iexact=role_name).exists():
            return Response({"error": f"Role '{role_name}' already exists."}, status=status.HTTP_400_BAD_REQUEST)

        # Create role Group
        group = Group.objects.create(name=role_name)

        # Initialize tenant permissions with core basics default list
        TenantModulePermission.objects.get_or_create(
            group_name=group.name,
            defaults={"allowed_modules": ["dashboard", "settings", "profile"]}
        )

        return Response({
            "message": f"Custom role '{group.name}' created successfully.",
            "role_name": group.name
        }, status=status.HTTP_201_CREATED)


from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
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


class RoleModulePermissionView(APIView):
    """
    College Admin level: Manage active modules for each user role.
    GET /api/tenant/module-permissions/
    POST /api/tenant/module-permissions/
    """
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def get(self, request):
        # Subscribed pool for current tenant
        tenant = connection.tenant
        subscribed = tenant.subscribed_modules or []

        roles = ['student', 'Faculty', 'Department Head', 'Support Staff', 'Management', 'Administrator']
        data = []

        for role in roles:
            perm, _ = TenantModulePermission.objects.get_or_create(group_name=role)
            # Filter allowed to only what's currently subscribed by SaaS
            filtered_allowed = [m for m in perm.allowed_modules if m in subscribed]
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

        roles = ['student', 'Faculty', 'Department Head', 'Support Staff', 'Management', 'Administrator']
        if group_name not in roles:
            return Response({"error": f"Invalid group_name. Must be one of: {', '.join(roles)}"}, status=status.HTTP_400_BAD_REQUEST)

        # Intersect with currently subscribed modules to prevent bypass
        tenant = connection.tenant
        subscribed = tenant.subscribed_modules or []
        validated_allowed = [m for m in allowed_modules if m in subscribed]

        perm, _ = TenantModulePermission.objects.get_or_create(group_name=group_name)
        perm.allowed_modules = validated_allowed
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

        subscribed = tenant.subscribed_modules or []

        # If SaaS Admin (superuser), grant access to all subscribed modules
        if user.is_superuser:
            return Response({
                "role": "SaaS Admin",
                "allowed_modules": subscribed
            })

        # Resolve role
        group_name = get_user_group(user)
        if not group_name:
            return Response({
                "role": "None",
                "allowed_modules": ["dashboard", "settings", "profile"]
            })

        # Get role allowed modules from db
        try:
            perm = TenantModulePermission.objects.get(group_name=group_name)
            allowed = perm.allowed_modules or []
        except TenantModulePermission.DoesNotExist:
            # Defaults if not configured yet
            if group_name in ('Management', 'Administrator'):
                allowed = ALL_ERP_MODULES
            else:
                allowed = ["dashboard", "attendance", "schedule", "settings", "profile"]

        # Intersect to find final list
        final_modules = [m for m in allowed if m in subscribed]

        # Always guarantee core basic views
        for core in ["dashboard", "settings", "profile"]:
            if core not in final_modules:
                final_modules.append(core)

        return Response({
            "role": group_name,
            "allowed_modules": final_modules
        })

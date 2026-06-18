"""
Tenant (College) Views
======================
Only the SaaS Admin (Django superuser) can create colleges.
This is enforced both here and via IsAdminUser permission.
"""
from rest_framework import generics, permissions
from .serializers import TenantCreateSerializer, TenantListSerializer, TenantUpdateSerializer
from .models import Tenant


class TenantCreateAPIView(generics.ListCreateAPIView):
    """
    SaaS Admin only: Create and list colleges (tenants).
    
    After creating a college, the SaaS Admin must:
    1. Log in to the college's tenant subdomain
    2. Create a Management user (College Admin) via POST /register/
    3. The College Admin then creates departments
    4. After departments exist, the College Admin creates other users
    """
    queryset = Tenant.objects.all()
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return TenantListSerializer
        return TenantCreateSerializer

    def perform_create(self, serializer):
        serializer.save()

    def create(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Only the SaaS Admin (superuser) can create colleges."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().create(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Only the SaaS Admin (superuser) can list colleges."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().list(request, *args, **kwargs)


class TenantDetailAPIView(generics.RetrieveUpdateDestroyAPIView):
    """
    SaaS Admin only: Retrieve, update, or delete a college (tenant).
    """
    queryset = Tenant.objects.all()
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

    def get_serializer_class(self):
        if self.request.method in ['PUT', 'PATCH']:
            return TenantUpdateSerializer
        return TenantListSerializer

    def retrieve(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Only the SaaS Admin (superuser) can view college details."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().retrieve(request, *args, **kwargs)

    def update(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Only the SaaS Admin (superuser) can update colleges."},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        if not request.user.is_superuser:
            from rest_framework.response import Response
            from rest_framework import status
            return Response(
                {"error": "Only the SaaS Admin (superuser) can delete colleges."},
                status=status.HTTP_403_FORBIDDEN
            )
        # Custom delete: also clean up associated schemas if desired, but django-tenants handles this on model delete.
        return super().destroy(request, *args, **kwargs)

"""
Tenant (College) Views
======================
Only the SaaS Admin (Django superuser) can create colleges.
This is enforced both here and via IsAdminUser permission.
"""
from rest_framework import generics, permissions
from .serializers import TenantCreateSerializer
from .models import Tenant


class TenantCreateAPIView(generics.CreateAPIView):
    """
    SaaS Admin only: Create a new college (tenant).
    
    After creating a college, the SaaS Admin must:
    1. Log in to the college's tenant subdomain
    2. Create a Management user (College Admin) via POST /register/
    3. The College Admin then creates departments
    4. After departments exist, the College Admin creates other users
    """
    queryset = Tenant.objects.all()
    serializer_class = TenantCreateSerializer
    # IsAdminUser = is_staff=True, which for superusers is always True
    permission_classes = [permissions.IsAuthenticated, permissions.IsAdminUser]

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

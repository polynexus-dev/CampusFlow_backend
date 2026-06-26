from django_tenants.middleware.main import TenantMainMiddleware
from django.db import connection
from django.http import Http404
from tenants.models import Tenant
from django_tenants.utils import get_public_schema_name, get_tenant_model
import base64
import json


def _get_schema_from_jwt(request):
    """
    Decode JWT bearer token (without verification) to extract tenant_schema claim.
    This is a safe operation — we're NOT authenticating here, just routing.
    Full authentication still happens via DRF's JWTAuthentication later.
    """
    try:
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if not auth_header.startswith('Bearer '):
            return None
        token = auth_header.split(' ', 1)[1]
        # JWT is base64url encoded: header.payload.signature
        payload_b64 = token.split('.')[1]
        # Add padding
        payload_b64 += '=' * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get('tenant_schema')
    except Exception:
        return None


class CampusFlowTenantMiddleware(TenantMainMiddleware):
    def process_request(self, request):
        TenantModel = get_tenant_model()

        # 1. Check for X-Tenant header (mobile apps set this after login)
        tenant_schema = request.headers.get('X-Tenant')
        if tenant_schema:
            try:
                tenant = TenantModel.objects.get(schema_name=tenant_schema)
                request.tenant = tenant
                connection.set_tenant(tenant)
                self.activate_tenant_timezone(request)
                return
            except TenantModel.DoesNotExist:
                pass

        # 2. Run standard django-tenants domain resolution
        try:
            super().process_request(request)
            self.activate_tenant_timezone(request)
            return
        except Exception:
            pass

        # 3. Fallback: read tenant_schema embedded in JWT token
        #    (Handles case where X-Tenant was not sent but user is authenticated)
        jwt_schema = _get_schema_from_jwt(request)
        if jwt_schema:
            try:
                tenant = TenantModel.objects.get(schema_name=jwt_schema)
                request.tenant = tenant
                connection.set_tenant(tenant)
                self.activate_tenant_timezone(request)
                return
            except TenantModel.DoesNotExist:
                pass

        # 4. Last resort: fall back to public schema (for unmatched hosts in dev)
        try:
            public_tenant = TenantModel.objects.get(schema_name=get_public_schema_name())
            request.tenant = public_tenant
            connection.set_tenant(public_tenant)
            self.activate_tenant_timezone(request)
        except Exception:
            pass

    def activate_tenant_timezone(self, request):
        from django.utils import timezone
        if hasattr(request, 'tenant') and request.tenant:
            tzname = getattr(request.tenant, 'timezone', 'Asia/Kolkata')
            if tzname:
                try:
                    timezone.activate(tzname)
                except Exception:
                    timezone.activate('Asia/Kolkata')
            else:
                timezone.activate('Asia/Kolkata')

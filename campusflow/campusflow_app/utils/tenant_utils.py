"""
campusflow_app/utils/tenant_utils.py

Shared tenant schema utilities used across API views.
"""
import base64
import json

from django.db import connection


def ensure_tenant_schema(request):
    """
    Ensure the database connection is set to the correct tenant schema.

    The middleware should already have done this, but when requests come
    from the mobile app using a raw IP address (e.g. 192.168.1.195:8000),
    django-tenants cannot match the domain, so it falls back to 'public'.

    This function is called at the start of any view that queries
    tenant-specific tables. It reads the schema from (in priority order):
      1. Already on a non-public schema — no action needed.
      2. X-Tenant request header.
      3. 'tenant_schema' claim embedded in the JWT Bearer token.

    This is safe because it is NOT used for authentication — DRF's
    JWTAuthentication middleware still performs the actual token verification.
    We are only routing the DB connection.
    """
    # Already on the right schema — nothing to do
    if connection.schema_name not in ('public', ''):
        return

    from tenants.models import Tenant

    # 1. X-Tenant header (set by mobile app httpClient after login)
    header_schema = request.headers.get('X-Tenant')
    if header_schema:
        try:
            tenant = Tenant.objects.get(schema_name=header_schema)
            connection.set_tenant(tenant)
            return
        except Tenant.DoesNotExist:
            pass

    # 2. tenant_schema claim from JWT payload (fallback for existing sessions
    #    where X-Tenant wasn't sent, e.g. before this fix was deployed)
    try:
        auth_header = request.META.get('HTTP_AUTHORIZATION', '')
        if auth_header.startswith('Bearer '):
            token_str = auth_header.split(' ', 1)[1]
            payload_b64 = token_str.split('.')[1]
            payload_b64 += '=' * (4 - len(payload_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(payload_b64))
            jwt_schema = payload.get('tenant_schema')
            if jwt_schema:
                tenant = Tenant.objects.get(schema_name=jwt_schema)
                connection.set_tenant(tenant)
                return
    except Exception:
        pass

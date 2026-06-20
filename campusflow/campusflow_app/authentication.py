"""
campusflow_app/authentication.py

Custom JWT authentication that switches to the correct tenant schema
before returning the authenticated user.

DRF call order:
  1. authenticate()         ← we set schema HERE
  2. check_permissions()    ← needs the correct schema already set
  3. view.get/post/etc()    ← runs in correct schema context

Without this, IP-based mobile requests (no domain match) fall through
to the public schema, causing "relation X does not exist" errors
during permission checks that hit tenant-specific tables.
"""
import base64
import json

from django.db import connection
from rest_framework_simplejwt.authentication import JWTAuthentication


def _switch_schema_from_token(raw_token: bytes | str):
    """
    Decode a JWT payload (without full verification — just for routing)
    and switch the DB connection to the tenant schema embedded in it.
    Full cryptographic verification still happens in the parent class.
    """
    # Already on a real tenant schema — nothing to do
    if connection.schema_name not in ('public', ''):
        return

    try:
        from tenants.models import Tenant

        token_str = raw_token if isinstance(raw_token, str) else raw_token.decode('utf-8')
        payload_b64 = token_str.split('.')[1]
        # Add required base64 padding
        payload_b64 += '=' * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))

        schema = payload.get('tenant_schema')
        if schema and schema != 'public':
            tenant = Tenant.objects.using('default').get(schema_name=schema)
            connection.set_tenant(tenant)
    except Exception:
        # Never block authentication due to schema routing failure
        pass


class TenantAwareJWTAuthentication(JWTAuthentication):
    """
    Extends simplejwt's JWTAuthentication to switch the DB connection
    to the correct tenant schema before the user object is fetched.

    This is the earliest safe point in DRF's request lifecycle to do
    schema switching, ensuring that subsequent permission checks and
    view code all run against the right PostgreSQL schema.
    """

    def authenticate(self, request):
        header = self.get_header(request)
        if header is None:
            return None

        # 1. Extract the raw token from the Authorization header
        raw_token = self.get_raw_token(header)
        if raw_token is None:
            return None  # No auth header — let DRF handle unauthenticated

        # 2. Switch schema BEFORE verifying (safe — we verify next)
        _switch_schema_from_token(raw_token)

        # 3. Full JWT validation (signature, expiry, etc.) via parent class
        validated_token = self.get_validated_token(raw_token)

        # 4. Fetch user object (now in the correct schema)
        return self.get_user(validated_token), validated_token

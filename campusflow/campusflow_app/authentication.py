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
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication
from rest_framework_simplejwt.exceptions import AuthenticationFailed


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

        # 4. SECURITY: the token's own (signed, verified) tenant_schema claim
        # must match the schema the connection is actually on. Without this,
        # a valid token from one tenant could be replayed against another
        # tenant's schema via a spoofed X-Tenant header, since step 2 above
        # only switches schema when still on 'public' and never re-checks
        # against the token once a schema has already been selected.
        token_schema = validated_token.get('tenant_schema')
        if token_schema != connection.schema_name:
            raise AuthenticationFailed('Token tenant does not match the active tenant schema.')

        # 4.5 Demo-tenant guardrail: block DELETE tenant-wide here, not in
        # CampusFlowTenantMiddleware — that middleware runs BEFORE this
        # authenticate() call, and for requests hitting the base/public
        # domain (the normal case per the "login via base URL" pattern)
        # django-tenants' own domain resolution already succeeds against
        # the public tenant there, so the middleware never reaches its JWT
        # fallback and never sees the real (demo) tenant. This is the one
        # point guaranteed to run, for every view, AFTER the schema switch
        # above has resolved the actual tenant.
        if request.method == 'DELETE':
            tenant = getattr(connection, 'tenant', None)
            if tenant and getattr(tenant, 'is_demo', False):
                from campusflow_app.demo_guard import DEMO_BLOCK_MESSAGE
                raise PermissionDenied(DEMO_BLOCK_MESSAGE)

        # 5. Fetch user object (now in the correct, verified schema)
        return self.get_user(validated_token), validated_token

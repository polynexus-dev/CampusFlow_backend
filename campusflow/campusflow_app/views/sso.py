"""
Cross-subdomain login hand-off (web).

Login happens on the base site (campusnexus.in); the user then continues on
their college's subdomain (<college>.campusnexus.in), which has its own
localStorage. Tokens used to travel in the redirect URL, which leaks them
into browser history, server logs and Referer headers. Now:

  1. Base site, logged in:  POST /api/auth/sso/handoff/ {refresh?}  -> {code}
     (the base site's refresh token, if sent, is blacklisted — the session
     moves to the subdomain rather than being copied)
  2. Redirect to <college>.campusnexus.in/login?handoff=<code>
  3. Subdomain:             POST /api/auth/sso/redeem/ {code} -> fresh tokens

The code is random, single use, and expires after SSO_HANDOFF_TTL_SECONDS.
It needs a cache shared by all web workers (Redis in production).
"""
import secrets

from django.contrib.auth.models import User
from django.core.cache import cache
from django.db import connection
from rest_framework import status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from ..serializers import MyTokenObtainPairSerializer
from ..throttling import AuthScopedRateThrottle

SSO_HANDOFF_TTL_SECONDS = 60


def _key(code):
    return f"sso_handoff:{code}"


class SSOHandoffCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh = request.data.get("refresh")
        if refresh:
            try:
                token = RefreshToken(refresh)
                if str(token.get("user_id")) == str(request.user.id):
                    token.blacklist()
            except TokenError:
                pass  # already invalid — nothing to revoke

        code = secrets.token_urlsafe(32)
        cache.set(
            _key(code),
            {"user_id": request.user.id, "schema": connection.schema_name},
            timeout=SSO_HANDOFF_TTL_SECONDS,
        )
        return Response({"code": code, "expires_in": SSO_HANDOFF_TTL_SECONDS}, status=status.HTTP_201_CREATED)


class SSOHandoffRedeemView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AuthScopedRateThrottle]
    throttle_scope = "sso_handoff"

    def post(self, request):
        from tenants.models import Tenant

        code = request.data.get("code") or ""
        entry = cache.get(_key(code)) if code else None
        # delete() reports whether the key existed, so two racing redeems of
        # the same code can't both succeed.
        if not entry or not cache.delete(_key(code)):
            return Response({"error": "This sign-in link has expired. Please log in again."}, status=status.HTTP_400_BAD_REQUEST)

        tenant = Tenant.objects.filter(schema_name=entry["schema"]).first()
        if tenant is None:
            return Response({"error": "College not found."}, status=status.HTTP_400_BAD_REQUEST)
        connection.set_tenant(tenant)

        user = User.objects.filter(id=entry["user_id"], is_active=True).first()
        if user is None:
            return Response({"error": "Account is not active."}, status=status.HTTP_400_BAD_REQUEST)

        refresh = MyTokenObtainPairSerializer.get_token(user)  # adds tenant_schema
        return Response({
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "tenant_schema": tenant.schema_name,
            "tenant_code": tenant.code,
        }, status=status.HTTP_200_OK)


class TenantTokenRefreshView(APIView):
    """
    POST /api/token/refresh/ {refresh} -> {access, refresh}
    Standard simplejwt rotation (the old refresh token is blacklisted), plus:
    the refresh token must belong to the college this request is routed to
    (X-Tenant), so rotation/blacklisting happens in that college's schema.
    No authentication classes: clients may still attach the expired access
    token, which would otherwise fail authentication before we get here.
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        from rest_framework_simplejwt.serializers import TokenRefreshSerializer

        raw = request.data.get("refresh") or ""
        try:
            token_schema = RefreshToken(raw).get("tenant_schema")
        except TokenError:
            return Response({"error": "Session expired. Please log in again."}, status=status.HTTP_401_UNAUTHORIZED)
        if token_schema != connection.schema_name:
            return Response({"error": "Session expired. Please log in again."}, status=status.HTTP_401_UNAUTHORIZED)

        serializer = TokenRefreshSerializer(data={"refresh": raw})
        try:
            serializer.is_valid(raise_exception=True)
        except Exception:
            return Response({"error": "Session expired. Please log in again."}, status=status.HTTP_401_UNAUTHORIZED)
        return Response(serializer.validated_data, status=status.HTTP_200_OK)

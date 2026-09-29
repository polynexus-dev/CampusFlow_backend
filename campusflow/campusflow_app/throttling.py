"""
Rate limits for unauthenticated auth endpoints (login, OTP request/verify,
password reset, parent linking). Scopes and rates are configured in
settings.REST_FRAMEWORK['DEFAULT_THROTTLE_RATES'].

AUTH_THROTTLE_ENABLED lets the test suite switch these off (it logs in and
requests codes many times from one IP within a minute); a dedicated test
turns it back on to prove the limits work.
"""
from django.conf import settings
from rest_framework.throttling import ScopedRateThrottle


class AuthScopedRateThrottle(ScopedRateThrottle):
    def allow_request(self, request, view):
        if not getattr(settings, "AUTH_THROTTLE_ENABLED", True):
            return True
        return super().allow_request(request, view)

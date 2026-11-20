"""
Cap CAPTCHA (https://github.com/tiagozip/cap): self-hosted proof-of-work,
Apache-2.0, no third party sees our users.

The browser solves a challenge with the <cap-widget> (or `new Cap().solve()`)
against our Cap server and sends the resulting token with the request, as the
`cap_token` field or the `X-Cap-Token` header. We confirm it server-to-server:

    POST {CAP_API_ENDPOINT}siteverify  {"secret": CAP_SECRET, "response": token}
    -> {"success": true}

Tokens are single-use. Configure with env vars CAP_ENABLED, CAP_API_ENDPOINT
(https://<cap-host>/<site-key>/) and CAP_SECRET. With CAP_ENABLED off (the
default, and always in tests) every check passes, so nothing changes until the
Cap server is up and the frontend sends tokens.

Where it's enforced:
  - CaptchaRequired permission: parent-link requests, guardian-consent resend.
  - Login: only after LOGIN_CAPTCHA_AFTER_FAILURES failed attempts for that
    username or IP (views/users.py MyObtainTokenPairView).

The mobile app can't run the widget natively, so GET /captcha/ serves a page
with it; the app shows that page in a WebView and receives the token.
"""
import json
import logging
import urllib.error
import urllib.request

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.clickjacking import xframe_options_exempt
from rest_framework import status
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission

logger = logging.getLogger(__name__)

CAPTCHA_ERROR = "Please complete the CAPTCHA and try again."


def captcha_enabled():
    return bool(getattr(settings, "CAP_ENABLED", False))


def get_cap_token(request):
    data = getattr(request, "data", None)
    token = None
    if hasattr(data, "get"):
        token = data.get("cap_token") or data.get("cap-token")
    token = token or request.headers.get("X-Cap-Token")
    return str(token).strip() if token else ""


def verify_cap_token(token):
    """True if Cap's server accepts the token. Network/config failures return
    CAP_FAIL_OPEN (default False: block rather than let bots through)."""
    if not captcha_enabled():
        return True
    if not token:
        return False
    endpoint = getattr(settings, "CAP_API_ENDPOINT", "")
    secret = getattr(settings, "CAP_SECRET", "")
    fail_open = bool(getattr(settings, "CAP_FAIL_OPEN", False))
    if not endpoint or not secret:
        logger.error("CAP_ENABLED is on but CAP_API_ENDPOINT / CAP_SECRET are not set.")
        return fail_open
    url = endpoint.rstrip("/") + "/siteverify"
    body = json.dumps({"secret": secret, "response": token}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=getattr(settings, "CAP_TIMEOUT", 5)) as resp:
            return bool(json.loads(resp.read() or b"{}").get("success"))
    except urllib.error.HTTPError as exc:
        # Cap answers a bad/used token with a 4xx and success: false.
        if 400 <= exc.code < 500:
            return False
        logger.warning("Cap siteverify returned HTTP %s", exc.code)
        return fail_open
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        logger.warning("Cap siteverify unreachable: %s", exc)
        return fail_open


def request_passes_captcha(request):
    return verify_cap_token(get_cap_token(request))


class CaptchaFailed(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_code = "captcha_required"

    def __init__(self):
        super().__init__()
        self.detail = captcha_failed_payload()  # raw, so captcha_required stays a JSON boolean


def captcha_failed_payload():
    """Reply when a request was refused for a missing/invalid token. `code`
    marks this exact case (retry with a token); `captcha_required` alone also
    appears on a failed login to say the *next* attempt will need one."""
    return {"error": CAPTCHA_ERROR, "captcha_required": True, "code": "captcha_required"}


@xframe_options_exempt  # the web app may embed it in an iframe
def captcha_page(request):
    """GET /captcha/: a bare page with the Cap widget. The mobile app opens it
    in a WebView when an API reply says captcha_required, and gets the token
    back as a {"type": "cap-token", "token": ...} message."""
    return render(request, "captcha/solve.html", {
        "enabled": captcha_enabled(),
        "api_endpoint": getattr(settings, "CAP_API_ENDPOINT", ""),
        "widget_src": getattr(settings, "CAP_WIDGET_SRC", ""),
    })


class CaptchaRequired(BasePermission):
    """Add to permission_classes; only checks unsafe methods (POST etc.)."""

    def has_permission(self, request, view):
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return True
        if not request_passes_captcha(request):
            raise CaptchaFailed()
        return True

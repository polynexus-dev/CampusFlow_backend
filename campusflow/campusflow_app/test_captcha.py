"""Cap CAPTCHA: token verification, login after repeated failures, and the
public/abusable endpoints that always need a token (captcha.py)."""
import io
import json
import urllib.error
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from rest_framework import status

from .captcha import CAPTCHA_ERROR, verify_cap_token
from .test_security_fixes import _SecurityFixture

CAP = dict(CAP_ENABLED=True, CAP_API_ENDPOINT="https://cap.test/site123/", CAP_SECRET="s3cret", CAP_FAIL_OPEN=False)


def _reply(payload):
    resp = mock.MagicMock()
    resp.read.return_value = json.dumps(payload).encode()
    resp.__enter__.return_value = resp
    return resp


class VerifyCapTokenTests(SimpleTestCase):
    def test_disabled_always_passes(self):
        with override_settings(CAP_ENABLED=False):
            self.assertTrue(verify_cap_token(""))

    @override_settings(**CAP)
    def test_posts_secret_and_token_to_siteverify(self):
        with mock.patch("urllib.request.urlopen", return_value=_reply({"success": True})) as urlopen:
            self.assertTrue(verify_cap_token("tok"))
        req = urlopen.call_args[0][0]
        self.assertEqual(req.full_url, "https://cap.test/site123/siteverify")
        self.assertEqual(json.loads(req.data), {"secret": "s3cret", "response": "tok"})

    @override_settings(**CAP)
    def test_missing_or_rejected_token_fails(self):
        self.assertFalse(verify_cap_token(""))
        rejected = urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b'{"success":false}'))
        with mock.patch("urllib.request.urlopen", side_effect=rejected):
            self.assertFalse(verify_cap_token("used-token"))
        with mock.patch("urllib.request.urlopen", return_value=_reply({"success": False})):
            self.assertFalse(verify_cap_token("tok"))

    @override_settings(**CAP)
    def test_cap_server_down_follows_fail_open(self):
        down = urllib.error.URLError("connection refused")
        with mock.patch("urllib.request.urlopen", side_effect=down):
            self.assertFalse(verify_cap_token("tok"))
            with override_settings(CAP_FAIL_OPEN=True):
                self.assertTrue(verify_cap_token("tok"))


class _CapOn:
    """TenantTestCase skips class-level @override_settings, so switch Cap on per test."""

    def setUp(self):
        super().setUp()
        override = override_settings(**CAP, LOGIN_CAPTCHA_AFTER_FAILURES=3)
        override.enable()
        self.addCleanup(override.disable)


class LoginCaptchaTests(_CapOn, _SecurityFixture, TenantTestCase):
    PASSWORD = "Right!Passw0rd"

    def setUp(self):
        super().setUp()
        cache.clear()
        self._user("capuser", "Administrator", password=self.PASSWORD)

    def _login(self, password, **extra):
        return self.client.post(
            reverse("token_obtain_pair"), {"username": "capuser", "password": password, **extra},
            content_type="application/json",
        )

    def test_first_attempts_need_no_captcha(self):
        self._login("wrong-pass")
        response = self._login(self.PASSWORD)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_captcha_required_after_repeated_failures(self):
        for _ in range(2):
            self.assertNotIn("captcha_required", str(self._login("wrong-pass").data))
        third = self._login("wrong-pass")
        self.assertTrue(third.data.get("captcha_required"), third.data)

        # Right password but no token: still refused.
        blocked = self._login(self.PASSWORD)
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(blocked.json(), {"error": CAPTCHA_ERROR, "captcha_required": True, "code": "captcha_required"})

        with mock.patch("urllib.request.urlopen", return_value=_reply({"success": True})):
            ok = self._login(self.PASSWORD, cap_token="solved")
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.data)

        # Success clears the username's counter.
        self.assertEqual(self._login(self.PASSWORD).status_code, status.HTTP_200_OK)


class CaptchaProtectedEndpointTests(_CapOn, _SecurityFixture, TenantTestCase):
    def _post(self, name, data, **extra):
        return self.client.post(
            reverse(name), data, content_type="application/json",
            HTTP_X_TENANT=self.tenant.schema_name, **extra,
        )

    def test_guardian_consent_resend_needs_token(self):
        response = self._post("guardian_consent_resend", {"email": "kid@test.com"})
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json(), {"error": CAPTCHA_ERROR, "captcha_required": True, "code": "captcha_required"})

        with mock.patch("urllib.request.urlopen", return_value=_reply({"success": True})):
            response = self._post("guardian_consent_resend", {"email": "kid@test.com", "cap_token": "solved"})
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)

    def test_captcha_page(self):
        page = self.client.get(reverse("captcha_page"), HTTP_X_TENANT=self.tenant.schema_name)
        self.assertContains(page, 'data-cap-api-endpoint="https://cap.test/site123/"')
        self.assertContains(page, "cap-widget@")
        with override_settings(CAP_ENABLED=False):
            off = self.client.get(reverse("captcha_page"), HTTP_X_TENANT=self.tenant.schema_name)
        self.assertContains(off, "cap-disabled")
        self.assertNotContains(off, "<cap-widget")

    def test_parent_link_request_needs_token(self):
        parent = self._user("cap_parent", "Parent")
        response = self._post("parent-link-request-create", {"student_code": "NOPE"}, **self._auth(parent))
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(response.data["captcha_required"])

        with mock.patch("urllib.request.urlopen", return_value=_reply({"success": True})):
            response = self._post(
                "parent-link-request-create", {"student_code": "NOPE"}, HTTP_X_CAP_TOKEN="solved", **self._auth(parent),
            )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND, response.data)

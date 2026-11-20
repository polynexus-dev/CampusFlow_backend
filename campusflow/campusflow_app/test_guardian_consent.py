"""Guardian consent via signed email link (guardian_consent.py)."""
import datetime
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail, signing
from django.core.cache import cache
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status

from .guardian_consent import SALT, make_token
from .models.profile import StudentProfile


class GuardianConsentLinkTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(username="minor", email="minor@test.com", password="x", first_name="Riya")
            self.profile = StudentProfile.objects.create(
                user=user, student_id="STU-M1", date_of_birth=datetime.date(2012, 1, 1),
                parent_guardian_name="Mrs Rao", parent_guardian_email="rao@test.com", status="pending_guardian",
            )
            self.token = make_token(self.profile, self.tenant.schema_name)

    def _status(self):
        with schema_context(self.tenant.schema_name):
            self.profile.refresh_from_db()
            return self.profile.status, self.profile.guardian_consent_given

    def _page(self, token=None):
        return reverse("guardian_consent_page", kwargs={"token": token or self.token})

    def test_opening_the_link_changes_nothing(self):
        response = self.client.get(self._page())
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Riya")
        self.assertEqual(self._status(), ("pending_guardian", False))

    def test_approve_from_page(self):
        no_confirm = self.client.post(self._page(), {"action": "approve"})
        self.assertEqual(no_confirm.status_code, 400)
        response = self.client.post(self._page(), {"action": "approve", "confirm": "1"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self._status(), ("active", True))
        # Single use: the link can't flip the decision afterwards.
        again = self.client.post(self._page(), {"action": "decline"})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self._status(), ("active", True))

    def test_decline_via_api(self):
        response = self.client.post(reverse("guardian_consent"), {"token": self.token, "action": "decline"},
                                    content_type="application/json")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        self.assertEqual(self._status(), ("rejected", False))

    def test_tampered_expired_and_superseded_links_fail(self):
        tampered = self.token[:-2] + ("aa" if not self.token.endswith("aa") else "bb")
        self.assertEqual(self.client.post(self._page(tampered), {"action": "approve", "confirm": "1"}).status_code, 400)

        forged = signing.dumps({"s": self.tenant.schema_name, "p": self.profile.pk, "e": "rao@test.com"}, salt="other")
        self.assertEqual(self.client.get(self._page(forged)).status_code, 400)

        with mock.patch("campusflow_app.guardian_consent.link_max_age", return_value=-1):
            self.assertContains(self.client.get(self._page()), "expired", status_code=400)

        # Changing the guardian email invalidates links sent to the old one.
        with schema_context(self.tenant.schema_name):
            StudentProfile.objects.filter(pk=self.profile.pk).update(parent_guardian_email="new@test.com")
        self.assertEqual(self.client.post(self._page(), {"action": "approve", "confirm": "1"}).status_code, 400)
        self.assertEqual(self._status(), ("pending_guardian", False))

    def test_token_payload_is_signed_not_secret_details(self):
        data = signing.loads(self.token, salt=SALT)
        self.assertEqual(data, {"s": self.tenant.schema_name, "p": self.profile.pk, "e": "rao@test.com"})

    def test_resend_goes_only_to_guardian_on_file(self):
        response = self.client.post(reverse("guardian_consent_resend"), {"email": "minor@test.com"},
                                    content_type="application/json", HTTP_X_TENANT=self.tenant.schema_name)
        self.assertEqual(response.status_code, 200)
        self.assertEqual([m.to for m in mail.outbox], [["rao@test.com"]])
        self.assertIn("/register/guardian-consent/", mail.outbox[0].body)

        unknown = self.client.post(reverse("guardian_consent_resend"), {"email": "ghost@test.com"},
                                   content_type="application/json", HTTP_X_TENANT=self.tenant.schema_name)
        self.assertEqual(unknown.data, response.data)
        self.assertEqual(len(mail.outbox), 1)

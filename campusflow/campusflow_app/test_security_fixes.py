"""
Regression tests for the 2026-09-29 security fixes (see the web repo's
FEATURE_PARITY_PROGRESS.md for the list). Each test pins one hole shut.
"""
import datetime

from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from tenants.models import Invoice

from .models.academics import AcademicYear
from .models.department import Department
from .models.profile import GuardianProfile, StudentProfile
from .models.statutory_committee import CommitteeMembership, StatutoryCommittee
from .utils.geofence import point_in_boundary, validate_boundary


class _SecurityFixture:
    def _user(self, username, group_name=None, password="Str0ng!Passw0rd", **extra):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(username=username, email=f"{username}@test.com", password=password, **extra)
            if group_name:
                group, _ = Group.objects.get_or_create(name=group_name)
                user.groups.add(group)
        return user

    def _token(self, user):
        with schema_context(self.tenant.schema_name):
            token = RefreshToken.for_user(user)
            token["tenant_schema"] = self.tenant.schema_name
        return token

    def _auth(self, user):
        return {"HTTP_AUTHORIZATION": f"Bearer {self._token(user).access_token}"}


class SaaSInvoiceApprovalTests(_SecurityFixture, TenantTestCase):
    def test_college_admin_with_is_staff_cannot_approve_own_invoice(self):
        invoice = Invoice.objects.create(
            tenant=self.tenant, invoice_number="INV-SEC-1", amount=1000,
            billing_period_start=datetime.date(2026, 7, 1), billing_period_end=datetime.date(2026, 7, 31),
            due_date=datetime.date(2026, 7, 10),
        )
        admin = self._user("college_admin", "Management", is_staff=True)
        response = self.client.post(reverse("saas_invoice_approve", kwargs={"pk": invoice.pk}), **self._auth(admin))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        invoice.refresh_from_db()
        self.assertNotEqual(invoice.status, "paid")

        response = self.client.get(reverse("saas_invoice_list"), **self._auth(admin))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class IsNotStudentTests(_SecurityFixture, TenantTestCase):
    def test_student_cannot_see_fee_dashboard_or_staff_directory(self):
        self.tenant.subscribed_modules = ["fees"]
        self.tenant.save(update_fields=["subscribed_modules"])
        student = self._user("sec_student", "student")
        self.assertEqual(self.client.get(reverse("fee-dashboard"), **self._auth(student)).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self.client.get(reverse("college-employees-list"), **self._auth(student)).status_code, status.HTTP_403_FORBIDDEN)

    def test_staff_still_can(self):
        admin = self._user("sec_admin", "Administrator")
        self.assertEqual(self.client.get(reverse("college-employees-list"), **self._auth(admin)).status_code, status.HTTP_200_OK)


class TokenVerifyTests(_SecurityFixture, TenantTestCase):
    def test_garbage_token_is_rejected(self):
        response = self.client.post(reverse("verify-token"), {"token": "not-a-jwt"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_real_token_is_accepted(self):
        user = self._user("verify_me", "Faculty")
        response = self.client.post(
            reverse("verify-token"), {"token": str(self._token(user).access_token)}, format="json",
            HTTP_X_TENANT=self.tenant.schema_name,
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)


class OtpBruteForceTests(_SecurityFixture, TenantTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.tenant.permitted_email_domain = "test.com"
        self.tenant.save()
        self._user("victim", "Administrator")

    def _otp_entry(self):
        return cache.get(f"otp:forgot:{self.tenant.schema_name}:victim@test.com")

    def test_code_dies_after_five_wrong_guesses(self):
        self.client.post(reverse("forgot_password_request_otp"), {"email": "victim@test.com"}, format="json")
        real_code = self._otp_entry()["code"]
        wrong = "000000" if real_code != "000000" else "111111"
        for _ in range(5):
            self.client.post(reverse("forgot_password_verify_otp"), {"email": "victim@test.com", "otp": wrong}, format="json")
        # Even the right code is now useless.
        response = self.client.post(reverse("forgot_password_verify_otp"), {"email": "victim@test.com", "otp": real_code}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unknown_email_gets_the_same_reply(self):
        known = self.client.post(reverse("forgot_password_request_otp"), {"email": "victim@test.com"}, format="json")
        unknown = self.client.post(reverse("forgot_password_request_otp"), {"email": "nobody@test.com"}, format="json")
        self.assertEqual(known.status_code, unknown.status_code)
        self.assertEqual(known.data, unknown.data)

    def test_codes_per_email_are_capped(self):
        for _ in range(5):
            self.client.post(reverse("forgot_password_request_otp"), {"email": "victim@test.com"}, format="json")
        response = self.client.post(reverse("forgot_password_request_otp"), {"email": "victim@test.com"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)

    @override_settings(AUTH_THROTTLE_ENABLED=True)
    def test_login_is_rate_limited_per_ip(self):
        codes = [
            self.client.post(reverse("token_obtain_pair"), {"username": "victim", "password": "wrong"}, format="json").status_code
            for _ in range(12)
        ]
        self.assertIn(status.HTTP_429_TOO_MANY_REQUESTS, codes)


class LoginTests(_SecurityFixture, TenantTestCase):
    def setUp(self):
        super().setUp()
        cache.clear()

    def test_unknown_user_and_wrong_password_look_the_same(self):
        self._user("realuser", "Administrator")
        unknown = self.client.post(reverse("token_obtain_pair"), {"username": "ghost", "password": "whatever1"}, format="json")
        wrong = self.client.post(reverse("token_obtain_pair"), {"username": "realuser", "password": "whatever1"}, format="json")
        self.assertEqual(unknown.status_code, wrong.status_code)
        self.assertNotIn("does not exist", str(unknown.data))

    def test_account_locks_after_repeated_failures(self):
        self._user("lockme", "Administrator", password="Right!Passw0rd")
        for _ in range(10):
            self.client.post(reverse("token_obtain_pair"), {"username": "lockme", "password": "wrong-pass"}, format="json")
        response = self.client.post(reverse("token_obtain_pair"), {"username": "lockme", "password": "Right!Passw0rd"}, format="json")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Too many failed login attempts", str(response.data))


class SessionAndSsoTests(_SecurityFixture, TenantTestCase):
    def test_refresh_rotates_and_rejects_other_college(self):
        user = self._user("refresher", "Faculty")
        refresh = self._token(user)
        ok = self.client.post(reverse("token-refresh"), {"refresh": str(refresh)}, format="json",
                              HTTP_X_TENANT=self.tenant.schema_name)
        self.assertEqual(ok.status_code, status.HTTP_200_OK)
        self.assertIn("access", ok.data)

        # Routed to the public schema instead of the token's college.
        other = self.client.post(reverse("token-refresh"), {"refresh": str(refresh)}, format="json")
        self.assertEqual(other.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_handoff_code_is_single_use(self):
        user = self._user("handoff_user", "Faculty")
        created = self.client.post(reverse("sso-handoff"), {}, format="json", **self._auth(user))
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        code = created.data["code"]

        first = self.client.post(reverse("sso-redeem"), {"code": code}, format="json")
        self.assertEqual(first.status_code, status.HTTP_200_OK)
        self.assertEqual(first.data["tenant_schema"], self.tenant.schema_name)
        second = self.client.post(reverse("sso-redeem"), {"code": code}, format="json")
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)


class MarksVisibilityTests(_SecurityFixture, TenantTestCase):
    def test_guardian_and_support_staff_get_no_marks(self):
        self.tenant.subscribed_modules = ["exams"]
        self.tenant.save(update_fields=["subscribed_modules"])
        for username, group in (("sec_guardian", "guardian"), ("sec_support", "Support Staff")):
            user = self._user(username, group)
            response = self.client.get(reverse("studentexamresult-list"), **self._auth(user))
            if response.status_code == status.HTTP_200_OK:
                data = response.data if isinstance(response.data, list) else response.data.get("results", [])
                self.assertEqual(len(data), 0)
            else:
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class CommitteeTests(_SecurityFixture, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            year = AcademicYear.objects.create(
                name="2026-2027", start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2027, 6, 30),
            )
            self.committee = StatutoryCommittee.objects.create(
                committee_type=StatutoryCommittee.TYPE_CHOICES[0][0], academic_year=year,
                formed_date=datetime.date(2026, 7, 1),
            )

    def test_any_user_can_list_committees_to_file_a_complaint(self):
        student = self._user("complainant", "student")
        response = self.client.get(reverse("statutorycommittee-list"), **self._auth(student))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_non_member_cannot_record_a_meeting(self):
        outsider = self._user("outsider", "Faculty")
        response = self.client.post(
            reverse("committeemeeting-list"),
            {"committee": self.committee.id, "meeting_date": "2026-08-01", "minutes_text": "x"},
            format="json", **self._auth(outsider),
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_member_can_record_a_meeting(self):
        member = self._user("member", "Faculty")
        with schema_context(self.tenant.schema_name):
            CommitteeMembership.objects.create(
                committee=self.committee, user=member, role_in_committee="Member",
                appointed_date=datetime.date(2026, 7, 1),
            )
        response = self.client.post(
            reverse("committeemeeting-list"),
            {"committee": self.committee.id, "meeting_date": "2026-08-01", "minutes_text": "x"},
            format="json", **self._auth(member),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.data)


class ParentLinkTests(_SecurityFixture, TenantTestCase):
    def test_failed_link_attempts_are_capped(self):
        cache.clear()
        guardian = self._user("parent1", "guardian")
        with schema_context(self.tenant.schema_name):
            GuardianProfile.objects.create(user=guardian, guardian_id="GUA-SEC1")
            dept = Department.objects.create(name="Sec Dept", code="SEC")
            child = self._user("child1", "student")
            StudentProfile.objects.create(user=child, student_id="STUSEC1", department=dept,
                                          date_of_birth=datetime.date(2008, 1, 2))
        for guess in range(5):
            response = self.client.post(
                reverse("parent-link-child"),
                {"student_id": "STUSEC1", "verification_key": f"2008-01-{10 + guess}"},
                format="json", **self._auth(guardian),
            )
            self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        # Now even the correct DOB is refused until the window passes.
        response = self.client.post(
            reverse("parent-link-child"), {"student_id": "STUSEC1", "verification_key": "2008-01-02"},
            format="json", **self._auth(guardian),
        )
        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)


class GeofenceTests(SimpleTestCase):
    SQUARE = [[21.14580, 79.08820], [21.14598, 79.08820], [21.14598, 79.08839], [21.14580, 79.08839]]

    def test_inside_and_outside(self):
        self.assertTrue(point_in_boundary(21.14589, 79.088295, self.SQUARE)[0])
        self.assertFalse(point_in_boundary(21.14535, 79.088295, self.SQUARE, buffer_m=10)[0])

    def test_gps_drift_buffer(self):
        just_outside = (21.145755, 79.088295)  # ~5 m south of the south edge
        self.assertFalse(point_in_boundary(*just_outside, self.SQUARE, buffer_m=0)[0])
        self.assertTrue(point_in_boundary(*just_outside, self.SQUARE, buffer_m=10)[0])

    def test_validation(self):
        self.assertIsNone(validate_boundary(self.SQUARE))
        self.assertIsNotNone(validate_boundary([[1, 2], [3, 4]]))
        self.assertIsNotNone(validate_boundary([[91, 0], [0, 0], [1, 1]]))

"""
Admin student-enrollment helpers: admission-number generation and the
"pre-created account, invite by email OTP" pattern already used by
StaffRegistrationView (views/users.py) — factored out here so
AdminEnrollStudentView doesn't duplicate it for the student + guardian
accounts it creates.
"""

import random

from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import connection
from django.utils import timezone

from campusflow_app.models import StudentProfile


def generate_admission_number(academic_year=None):
    """f'{tenant.code}-{academic_year}-{sequence:04d}', e.g. GPS-2026-0412."""
    tenant = getattr(connection, "tenant", None)
    prefix = (getattr(tenant, "code", None) or "STU").upper()
    academic_year = academic_year or str(timezone.localdate().year)

    stub = f"{prefix}-{academic_year}-"
    existing = StudentProfile.objects.filter(admission_number__startswith=stub).count()
    return f"{stub}{existing + 1:04d}"


def _unique_username(username_hint):
    base = (username_hint or "user").lower().replace(" ", ".")
    username = base
    suffix = 1
    while User.objects.filter(username=username).exists():
        suffix += 1
        username = f"{base}{suffix}"
    return username


def create_pending_user(email, first_name="", last_name="", username_hint=None):
    """Create a User with is_active=False and no usable password — activated
    later via the existing VerifyAccountView/StudentOnboardVerifyPasswordView
    OTP flows, exactly like StaffRegistrationView's pre-created accounts."""
    username = _unique_username(username_hint or email.split("@")[0])
    user = User.objects.create(
        username=username, email=email, first_name=first_name, last_name=last_name,
        is_active=False,
    )
    user.set_unusable_password()
    user.save()
    return user


def send_invite_otp(user, subject="CampusFlow Account Created", message_prefix="Your account has been created."):
    """Same cache_otp + send_mail pattern as StaffRegistrationView (views/users.py:251-256)."""
    otp_code = str(random.randint(100000, 999999))
    cache.set(f"otp_{user.email}", otp_code, timeout=600)
    try:
        send_mail(subject, f"{message_prefix} OTP: {otp_code}", None, [user.email])
    except Exception:
        pass
    return otp_code

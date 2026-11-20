"""
Guardian consent for students under 18 (DPDP Act, s.9).

When a minor is registered their profile is 'pending_guardian' and the
guardian on file gets an email with a signed link. Only someone who can read
that inbox can approve or decline: the link carries a signature over the
college, the profile and the guardian's email, so changing the guardian email
invalidates old links, and once the student leaves 'pending_guardian' the link
does nothing. Links expire after GUARDIAN_CONSENT_LINK_DAYS.

    GET/POST /register/guardian-consent/<token>/   page the guardian sees
    POST     /register/guardian-consent/           {token, action} (API)
    POST     /register/guardian-consent/resend/    {email} -> re-send the link
"""
import logging

from django.conf import settings
from django.core import signing
from django.core.mail import EmailMultiAlternatives
from django.db import connection
from django.template.loader import render_to_string
from django.urls import reverse
from django_tenants.utils import get_tenant_model, schema_context

logger = logging.getLogger(__name__)

SALT = "campusflow.guardian-consent.v1"


def link_max_age():
    return int(getattr(settings, "GUARDIAN_CONSENT_LINK_DAYS", 14)) * 24 * 3600


class InvalidConsentLink(Exception):
    pass


def make_token(profile, schema_name=None):
    return signing.dumps(
        {"s": schema_name or connection.schema_name, "p": profile.pk, "e": (profile.parent_guardian_email or "").lower()},
        salt=SALT, compress=True,
    )


def read_token(token):
    """-> (schema_name, profile_pk, guardian_email). Raises InvalidConsentLink."""
    try:
        data = signing.loads(token or "", salt=SALT, max_age=link_max_age())
        return data["s"], int(data["p"]), data["e"]
    except signing.SignatureExpired as exc:
        raise InvalidConsentLink("This link has expired. Ask the college or the student to send a new one.") from exc
    except (signing.BadSignature, KeyError, TypeError, ValueError) as exc:
        raise InvalidConsentLink("This link is not valid.") from exc


class consent_context:
    """`with consent_context(token) as (tenant, profile):` runs the block in
    the student's college schema. Raises InvalidConsentLink for a bad,
    expired or superseded link."""

    def __init__(self, token):
        self.schema, self.pk, self.guardian_email = read_token(token)
        self.tenant = get_tenant_model().objects.filter(schema_name=self.schema, is_active=True).first()
        if self.tenant is None or self.schema == "public":
            raise InvalidConsentLink("This link is not valid.")
        self._ctx = schema_context(self.schema)

    def __enter__(self):
        from .models.profile import StudentProfile

        self._ctx.__enter__()
        profile = StudentProfile.objects.select_related("user").filter(pk=self.pk).first()
        if profile is None or (profile.parent_guardian_email or "").lower() != self.guardian_email:
            self._ctx.__exit__(None, None, None)
            raise InvalidConsentLink("This link is not valid.")
        return self.tenant, profile

    def __exit__(self, *exc):
        return self._ctx.__exit__(*exc)


def apply_decision(profile, approve, request=None):
    """Approve or decline. Returns False if the profile is no longer waiting."""
    from .models.audit import AuditLog

    if profile.status != "pending_guardian":
        return False
    new_status = "active" if approve else "rejected"
    profile.status = new_status
    profile.guardian_consent_given = bool(approve)
    profile.save(update_fields=["status", "guardian_consent_given"])
    AuditLog.objects.create(
        user=None, action="UPDATE", model_name="StudentProfile", object_id=str(profile.pk),
        object_repr=f"Guardian {'approved' if approve else 'declined'} consent for {profile.user.username} (signed email link)",
        changes={"status": {"old": "pending_guardian", "new": new_status},
                 "guardian_consent_given": {"old": False, "new": bool(approve)}},
        ip_address=request.META.get("REMOTE_ADDR") if request else None,
        user_agent=(request.META.get("HTTP_USER_AGENT", "") if request else "")[:500],
        endpoint=(request.path if request else "")[:500],
    )
    return True


def consent_url(token, request=None):
    path = reverse("guardian_consent_page", kwargs={"token": token})
    base = getattr(settings, "PUBLIC_BACKEND_URL", "")
    if base:
        return base.rstrip("/") + path
    if request is not None:
        return request.build_absolute_uri(path)
    return path


def send_consent_request(profile, request=None):
    """Email the guardian the approval link. Returns True if sent."""
    guardian_email = profile.parent_guardian_email
    if not guardian_email or profile.status != "pending_guardian":
        return False
    tenant = getattr(connection, "tenant", None)
    context = {
        "guardian_name": profile.parent_guardian_name or "Parent/Guardian",
        "student_name": profile.user.get_full_name() or profile.user.username,
        "college_name": getattr(tenant, "name", "") or "your college",
        "url": consent_url(make_token(profile), request),
        "days": link_max_age() // 86400,
    }
    subject = f"Consent needed: {context['student_name']}'s CampusNexus account"
    text = (
        f"Dear {context['guardian_name']},\n\n"
        f"{context['college_name']} has registered {context['student_name']} on CampusNexus. "
        "Because the student is under 18, the account stays inactive until a parent or guardian agrees.\n\n"
        f"Review and approve or decline here (link valid for {context['days']} days):\n{context['url']}\n\n"
        "If you don't recognise this, you can ignore this email or decline using the link."
    )
    try:
        msg = EmailMultiAlternatives(subject=subject, body=text, from_email=None, to=[guardian_email])
        msg.attach_alternative(render_to_string("emails/guardian_consent_request.html", context), "text/html")
        msg.send()
        return True
    except Exception:
        logger.exception("Could not send guardian consent email for profile %s", profile.pk)
        return False

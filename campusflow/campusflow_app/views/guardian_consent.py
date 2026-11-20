"""
Guardian consent for minors: signed email link instead of "anyone who knows
the student's email, ID and guardian email". See guardian_consent.py.
"""
from django.db import connection
from django.shortcuts import render
from django.utils.decorators import method_decorator
from django.views import View
from django.views.decorators.csrf import csrf_exempt
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from ..captcha import CaptchaRequired
from ..guardian_consent import InvalidConsentLink, apply_decision, consent_context, send_consent_request
from ..models.profile import StudentProfile
from ..throttling import AuthScopedRateThrottle

APPROVED = "Thank you. Consent recorded, and the student's account is now active."
DECLINED = "Consent declined. The student's account will not be activated."
ALREADY = "A response has already been recorded for this student. Contact the college to change it."


def _decide(token, action, request):
    """-> (message, http_status). Raises InvalidConsentLink."""
    if action not in ("approve", "decline", "reject"):
        return "action must be 'approve' or 'decline'.", status.HTTP_400_BAD_REQUEST
    with consent_context(token) as (_tenant, profile):
        if not apply_decision(profile, approve=(action == "approve"), request=request):
            return ALREADY, status.HTTP_409_CONFLICT
    return (APPROVED if action == "approve" else DECLINED), status.HTTP_200_OK


@method_decorator(csrf_exempt, name="dispatch")  # the signed token in the URL is the secret
class GuardianConsentPageView(View):
    """GET /register/guardian-consent/<token>/ shows who the request is for;
    POST action=approve|decline records it. Opening the link (e.g. by an email
    scanner) never changes anything."""

    template = "guardian_consent/page.html"

    def get(self, request, token):
        try:
            with consent_context(token) as (tenant, profile):
                if profile.status != "pending_guardian":
                    return render(request, self.template, {"error": ALREADY})
                context = {
                    "student_name": profile.user.get_full_name() or profile.user.username,
                    "college_name": tenant.name,
                    "guardian_name": profile.parent_guardian_name,
                }
        except InvalidConsentLink as exc:
            return render(request, self.template, {"error": str(exc)}, status=400)
        return render(request, self.template, context)

    def post(self, request, token):
        action = request.POST.get("action", "")
        if action == "approve" and not request.POST.get("confirm"):
            return render(request, self.template, {"error": "Please confirm you are the student's parent or guardian."}, status=400)
        try:
            message, code = _decide(token, action, request)
        except InvalidConsentLink as exc:
            return render(request, self.template, {"error": str(exc)}, status=400)
        key = "done" if code == status.HTTP_200_OK else "error"
        return render(request, self.template, {key: message}, status=code)


class GuardianConsentApprovalView(APIView):
    """POST /register/guardian-consent/ {token, action: approve|decline}.
    Same as the page, for apps that render their own screen."""
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [AuthScopedRateThrottle]
    throttle_scope = "guardian_consent"

    def post(self, request):
        try:
            message, code = _decide(
                str(request.data.get("token", "")).strip(),
                str(request.data.get("action", "")).strip().lower(),
                request,
            )
        except InvalidConsentLink as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        key = "message" if code == status.HTTP_200_OK else "error"
        return Response({key: message}, status=code)


class GuardianConsentResendView(APIView):
    """POST /register/guardian-consent/resend/ {email}: re-send the link to
    the guardian already on file (never to an address given here). Same reply
    whether or not the student exists. Needs a Cap token when CAP_ENABLED."""
    permission_classes = [AllowAny, CaptchaRequired]
    authentication_classes = []
    throttle_classes = [AuthScopedRateThrottle]
    throttle_scope = "guardian_consent"

    def post(self, request):
        email = str(request.data.get("email", "")).strip().lower()
        if not email or "@" not in email:
            return Response({"error": "email is required."}, status=status.HTTP_400_BAD_REQUEST)
        if connection.schema_name == "public":
            from tenants.models import Tenant
            tenant = Tenant.objects.filter(permitted_email_domain=email.split("@")[-1]).first()
            if tenant:
                connection.set_tenant(tenant)
        if connection.schema_name != "public":
            profile = StudentProfile.objects.select_related("user").filter(
                user__email__iexact=email, status="pending_guardian",
            ).first()
            if profile:
                send_consent_request(profile, request)
        return Response({"message": "If this student is waiting for guardian consent, the guardian has been emailed a new link."})

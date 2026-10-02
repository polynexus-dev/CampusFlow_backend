"""
WhatsApp OTP delivery via AWS End User Messaging Social.

This module only *delivers* a code. Generating, storing and checking codes
stays in views/users.py (issue_otp / check_otp), so a code sent on WhatsApp
and one sent by email are the same tenant-scoped entry in the Django cache,
with the same attempt limits.

Configured in settings (WA_*). Delivery is disabled when WA_ORIGINATION_ID is
empty, and callers fall back to email. AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY
are passed to boto3 only when both are set; otherwise boto3's default chain
is used (IAM role on AWS, ~/.aws/credentials locally). The IAM permission
needed is social-messaging:SendWhatsAppMessage.
"""

import json
import logging
import os

from django.conf import settings

log = logging.getLogger(__name__)

_client = None


class WhatsAppError(Exception):
    """The message could not be delivered on WhatsApp."""


def is_enabled():
    return bool(settings.WA_ORIGINATION_ID)


def normalize_phone(phone):
    """
    '+91 90750-80310' / '09075080310' / '9075080310' -> '919075080310'.
    Raises ValueError (with a message safe to show) for anything that isn't
    an Indian mobile number.
    """
    digits = "".join(ch for ch in str(phone or "") if ch.isascii() and ch.isdigit())
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) != 12 or not digits.startswith("91") or digits[2] not in "6789":
        raise ValueError("Please enter a valid 10-digit Indian mobile number.")
    return digits


def phone_variants(normalized):
    """Forms the same number may already be stored in (older rows weren't normalized)."""
    local = normalized[2:]
    return [normalized, "+" + normalized, local, "0" + local]


def _get_client():
    global _client
    if _client is None:
        import boto3
        kwargs = {"region_name": settings.WA_AWS_REGION}
        key_id = os.getenv("AWS_ACCESS_KEY_ID", "").strip()
        secret = os.getenv("AWS_SECRET_ACCESS_KEY", "").strip()
        if key_id and secret:  # never hand boto3 empty strings
            kwargs.update(aws_access_key_id=key_id, aws_secret_access_key=secret)
        _client = boto3.client("socialmessaging", **kwargs)
    return _client


def send_otp(phone, code):
    """Send `code` using the approved authentication template. Returns the AWS messageId."""
    if not is_enabled():
        raise WhatsAppError("WhatsApp delivery is not configured.")
    from botocore.exceptions import BotoCoreError, ClientError

    phone = normalize_phone(phone)
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "+" + phone,  # AWS requires E.164 with the leading '+'
        "type": "template",
        "template": {
            "name": settings.WA_OTP_TEMPLATE,
            "language": {"code": settings.WA_OTP_LANGUAGE},
            "components": [
                {"type": "body", "parameters": [{"type": "text", "text": code}]},
                # Authentication templates carry a copy-code button that needs the code too.
                {"type": "button", "sub_type": "url", "index": "0",
                 "parameters": [{"type": "text", "text": code}]},
            ],
        },
    }
    masked = f"{phone[:4]}****{phone[-2:]}"
    try:
        resp = _get_client().send_whatsapp_message(
            originationPhoneNumberId=settings.WA_ORIGINATION_ID,
            message=json.dumps(payload).encode("utf-8"),
            metaApiVersion=settings.WA_META_API_VERSION,
        )
    except ClientError as e:
        err = e.response.get("Error", {})
        log.error("WhatsApp OTP to %s failed [%s]: %s", masked, err.get("Code"), err.get("Message"))
        raise WhatsAppError(err.get("Code") or "ClientError") from e
    except BotoCoreError as e:  # no credentials, network, bad region, ...
        log.error("WhatsApp OTP to %s failed: %s", masked, e)
        raise WhatsAppError(type(e).__name__) from e

    log.info("WhatsApp OTP sent to %s msg=%s", masked, resp.get("messageId"))
    return resp.get("messageId")

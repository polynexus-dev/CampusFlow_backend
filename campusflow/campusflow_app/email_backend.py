"""
Email backend wrapper that suppresses outgoing mail for the public demo
tenant. Rather than patching every call site that sends mail (OTP emails,
password recovery, contact enquiries, DPDP notices, ...), this wraps
whichever real backend is configured (SMTP or Anymail/Brevo, see
settings.DEMO_REAL_EMAIL_BACKEND) and drops messages at the one point they
all funnel through, whenever the active tenant is flagged `is_demo`.
"""

import logging

from django.conf import settings
from django.core.mail.backends.base import BaseEmailBackend
from django.db import connection
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class DemoAwareEmailBackend(BaseEmailBackend):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        real_backend_cls = import_string(settings.DEMO_REAL_EMAIL_BACKEND)
        self._real_backend = real_backend_cls(*args, **kwargs)

    def send_messages(self, email_messages):
        tenant = getattr(connection, "tenant", None)
        if tenant and getattr(tenant, "is_demo", False):
            for message in email_messages:
                logger.info(
                    "Suppressed outgoing email for demo tenant: to=%s subject=%r",
                    message.to, message.subject,
                )
            return len(email_messages)
        return self._real_backend.send_messages(email_messages)

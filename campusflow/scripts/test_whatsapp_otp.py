"""
Send a test WhatsApp OTP through the real backend service.

    python scripts/test_whatsapp_otp.py 9075080310 [code]

Uses the WA_* / AWS_* settings from .env. Prints the AWS messageId, or the
full error. The code defaults to 123456 and is not stored anywhere, so it
can't be used to log in.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402

from campusflow_app.services import whatsapp  # noqa: E402


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    phone, code = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "123456")

    print(f"origination={settings.WA_ORIGINATION_ID or '(empty: WhatsApp disabled)'} "
          f"region={settings.WA_AWS_REGION} template={settings.WA_OTP_TEMPLATE} "
          f"language={settings.WA_OTP_LANGUAGE}")
    try:
        print("normalized:", whatsapp.normalize_phone(phone))
        print("messageId:", whatsapp.send_otp(phone, code))
    except Exception as e:
        cause = e.__cause__
        print(f"FAILED: {type(e).__name__}: {e}")
        if cause is not None:
            print(f"cause: {type(cause).__name__}: {cause}")
            print("response:", getattr(cause, "response", None))
        sys.exit(1)


if __name__ == "__main__":
    main()

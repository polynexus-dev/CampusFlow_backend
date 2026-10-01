"""
WhatsApp OTP via AWS End User Messaging Social
Polynexus Technologies - Vidyam / CampusNexus login

pip install boto3 redis python-dotenv
"""

import os
import re
import json
import time
import hashlib
import secrets
import logging

# Load .env so this file works both standalone and when imported by Django
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

import boto3
from botocore.exceptions import ClientError

log = logging.getLogger("whatsapp_otp")

# ---------------------------------------------------------------- config ----
AWS_REGION        = os.getenv("AWS_REGION", "ap-south-1")
AWS_ACCESS_KEY    = os.getenv("AWS_ACCESS_KEY_ID", "")
AWS_SECRET_KEY    = os.getenv("AWS_SECRET_ACCESS_KEY", "")
META_API_VERSION  = "v20.0"

# phoneNumberId from:
#   aws socialmessaging get-linked-whatsapp-business-account \
#       --id waba-1f585d386d474639a8bab090b15d998b --region ap-south-1
ORIGINATION_ID = os.getenv("WA_ORIGINATION_ID", "phone-number-id-5592862006d042e1adbd35337b1af4bd")

# Use the exact template names you created in the console
PRODUCTS = {
    "vidyam":      {"template": "otp_login", "language": "en_IN"},
    "campusnexus": {"template": "otp_login", "language": "en_IN"},
}

OTP_LENGTH = 6
OTP_TTL = 300            # 5 min - matches template expiry
MAX_ATTEMPTS = 5         # wrong guesses before OTP is burned
RESEND_COOLDOWN = 60     # seconds between sends to the same number
MAX_SENDS_PER_HOUR = 5   # per phone, per product

# ------------------------------------------------------------- storage ------
class _MemoryStore:
    """Dev-only fallback. Use Redis in production (multiple workers)."""
    def __init__(self):
        self._d = {}

    def get(self, k):
        v = self._d.get(k)
        if not v or v[1] < time.time():
            self._d.pop(k, None)
            return None
        return v[0]

    def set(self, k, val, ttl):
        self._d[k] = (val, time.time() + ttl)

    def delete(self, k):
        self._d.pop(k, None)

    def incr(self, k, ttl):
        cur = int(self.get(k) or 0) + 1
        exp = self._d[k][1] if k in self._d else time.time() + ttl
        self._d[k] = (str(cur), exp)
        return cur


class _RedisStore:
    def __init__(self, url):
        import redis
        self.r = redis.Redis.from_url(url, decode_responses=True)

    def get(self, k):
        return self.r.get(k)

    def set(self, k, val, ttl):
        self.r.setex(k, ttl, val)

    def delete(self, k):
        self.r.delete(k)

    def incr(self, k, ttl):
        pipe = self.r.pipeline()
        pipe.incr(k)
        pipe.expire(k, ttl, nx=True)
        return pipe.execute()[0]


store = _RedisStore(os.environ["REDIS_URL"]) if os.getenv("REDIS_URL") else _MemoryStore()

# Build boto3 client — uses explicit keys if set, otherwise falls back to
# IAM role / ~/.aws/credentials / environment variables (standard AWS chain)
_boto_kwargs = {"region_name": AWS_REGION}
if AWS_ACCESS_KEY and AWS_SECRET_KEY:
    _boto_kwargs["aws_access_key_id"]     = AWS_ACCESS_KEY
    _boto_kwargs["aws_secret_access_key"] = AWS_SECRET_KEY

client = boto3.client("socialmessaging", **_boto_kwargs)

# -------------------------------------------------------------- errors ------
class OTPError(Exception):
    """Message is safe to show to the end user."""


# ------------------------------------------------------------- helpers ------
def normalize_phone(phone: str) -> str:
    """'+91 90750-80310' / '09075080310' / '9075080310' -> '919075080310'"""
    digits = "".join(ch for ch in str(phone) if ch.isascii() and ch.isdigit())
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    if len(digits) == 10:
        digits = "91" + digits
    if len(digits) != 12 or not digits.startswith("91") or digits[2] not in "6789":
        raise OTPError(f"Please enter a valid Indian mobile number. (got {phone!r} -> {digits!r})")
    return digits


def _hash(product, phone, otp):
    return hashlib.sha256(f"{product}:{phone}:{otp}".encode()).hexdigest()


def _key(kind, product, phone):
    return f"otp:{kind}:{product}:{phone}"


# ---------------------------------------------------------------- send ------
def send_otp(phone: str, product: str) -> str:
    """Generate an OTP, deliver it on WhatsApp, return AWS messageId."""
    if product not in PRODUCTS:
        raise ValueError(f"Unknown product: {product}")
    phone = normalize_phone(phone)
    cfg = PRODUCTS[product]

    if store.get(_key("cooldown", product, phone)):
        raise OTPError(f"Please wait {RESEND_COOLDOWN} seconds before requesting a new code.")
    if store.incr(_key("hourly", product, phone), 3600) > MAX_SENDS_PER_HOUR:
        raise OTPError("Too many OTP requests. Please try again after some time.")

    otp = "".join(str(secrets.randbelow(10)) for _ in range(OTP_LENGTH))

    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": "+" + phone,       # AWS requires E.164 with leading '+'
        "type": "template",
        "template": {
            "name": cfg["template"],
            "language": {"code": cfg["language"]},
            "components": [
                {"type": "body",
                 "parameters": [{"type": "text", "text": otp}]},
                {"type": "button", "sub_type": "url", "index": "0",
                 "parameters": [{"type": "text", "text": otp}]},
            ],
        },
    }

    try:
        resp = client.send_whatsapp_message(
            originationPhoneNumberId=ORIGINATION_ID,
            message=json.dumps(payload).encode("utf-8"),
            metaApiVersion=META_API_VERSION,
        )
    except ClientError as e:
        code = e.response["Error"]["Code"]
        log.error("WhatsApp send failed [%s] %s: %s",
                  product, phone, e.response["Error"].get("Message"))
        if code == "ThrottledRequestException":
            raise OTPError("Service is busy. Please try again shortly.")
        raise OTPError("Could not send OTP on WhatsApp. Please try again.")

    # Store only after AWS accepted the message
    store.set(_key("code", product, phone),
              json.dumps({"h": _hash(product, phone, otp), "a": 0}), OTP_TTL)
    store.set(_key("cooldown", product, phone), "1", RESEND_COOLDOWN)

    msg_id = resp["messageId"]
    log.info("OTP sent [%s] to %s****%s msg=%s", product, phone[:4], phone[-2:], msg_id)
    return msg_id


# -------------------------------------------------------------- verify ------
def verify_otp(phone: str, product: str, otp: str) -> bool:
    phone = normalize_phone(phone)
    k = _key("code", product, phone)
    raw = store.get(k)
    if not raw:
        raise OTPError("OTP expired or not requested. Please request a new code.")

    rec = json.loads(raw)
    if rec["a"] >= MAX_ATTEMPTS:
        store.delete(k)
        raise OTPError("Too many wrong attempts. Please request a new code.")

    otp = re.sub(r"\D", "", otp or "")
    if secrets.compare_digest(rec["h"], _hash(product, phone, otp)):
        store.delete(k)          # one-time use
        return True

    rec["a"] += 1
    store.set(k, json.dumps(rec), OTP_TTL)   # note: resets TTL slightly; fine for 5-min window
    return False


# ---------------------------------------------------------------- test ------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    number = input("Your WhatsApp number [+919075080310]: ").strip() or "+919075080310"
    product = input("Product (vidyam/campusnexus): ").strip().lower()
    print("messageId:", send_otp(number, product))
    code = input("Enter the code you received: ")
    print("Verified!" if verify_otp(number, product, code) else "Wrong code")

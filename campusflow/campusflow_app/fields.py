from django.conf import settings
from django.db import models
from cryptography.fernet import Fernet, InvalidToken


def _get_fernet():
    key = settings.FIELD_ENCRYPTION_KEY
    return Fernet(key if isinstance(key, bytes) else key.encode())


class EncryptedCharField(models.CharField):
    """
    Transparently encrypts/decrypts a CharField's value at rest using Fernet.
    Payment gateway secrets (API secrets, salts, webhook secrets) use this
    instead of plain CharField so a DB dump/leak doesn't expose them directly.
    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_length", 500)
        super().__init__(*args, **kwargs)

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        if value in (None, ""):
            return value
        return _get_fernet().encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        if value in (None, ""):
            return value
        try:
            return _get_fernet().decrypt(value.encode()).decode()
        except (InvalidToken, ValueError):
            # Not encrypted yet (pre-migration legacy value) — return as-is.
            return value

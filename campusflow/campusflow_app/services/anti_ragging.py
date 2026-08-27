"""Reference-number generation for anti-ragging undertakings — same
tenant-code + year + zero-padded-sequence shape as
services/enrollment.generate_admission_number, so the number is both
human-readable and collision-free per tenant schema without needing a
separate counter table."""
from django.db import connection

from ..models.anti_ragging import AntiRaggingUndertaking


def generate_undertaking_reference_number(academic_year):
    tenant = getattr(connection, "tenant", None)
    prefix = (getattr(tenant, "code", None) or "AR").upper()
    year_label = academic_year.name if academic_year else "0000"

    stub = f"AR-{prefix}-{year_label}-"
    existing = AntiRaggingUndertaking.objects.filter(reference_number__startswith=stub).count()
    return f"{stub}{existing + 1:04d}"

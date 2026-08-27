from django.core.management.base import BaseCommand
from django_tenants.utils import tenant_context
from tenants.models import Tenant
from campusflow_app.models.compliance import ComplianceCertificateType

# Curated starter catalog so every college sees a ready-made dropdown on day
# one (Docs/compliance_and_audit_portal_plan.md §8 open decision — resolved
# here in favor of a curated seed). Admins remain free to add tenant-specific
# types on top; this command only creates missing rows, never edits existing
# ones, so it's safe to re-run after a tenant has customized its own list.
#
# `varies_by_state` entries are the ones a single "AICTE"/"UGC" issuing
# authority can't cover — Professional Tax, Shops & Establishments, State
# Pollution Control Board consent, and similar are legally different
# certificates in every state. issuing_authority is left generic ("State
# Government") for those; a college fills in its own state's actual
# department name when it uploads the certificate.
CATALOG = [
    # ── National bodies — the original Certificate & License Vault (P1) list ──
    ("UGC 2(f) Recognition", "UGC", False, False),
    ("UGC 12(B) Recognition", "UGC", False, False),
    ("Trust/Society Registration", "Registrar of Societies/Trusts", False, False),
    ("AICTE Extension of Approval (EOA) Letter", "AICTE", True, False),
    ("University Affiliation Certificate", "Affiliating University", True, False),
    ("Fire Safety NOC", "State Fire Department", True, True),
    ("Building/Structural Stability Certificate", "Local Municipal Authority", False, True),
    ("Previous NAAC Accreditation Certificate", "NAAC", False, False),
    ("Audited Financial Statement", "Chartered Accountant", True, False),

    # ── State-varying statutory/labour compliance (missing-module addition) ──
    ("Professional Tax Registration Certificate", "State Government", True, True),
    ("Shops & Establishments Act Registration", "State Labour Department", True, True),
    ("State Pollution Control Board — Consent to Establish/Operate", "State Pollution Control Board", True, True),
    ("Labour Welfare Fund Registration", "State Labour Department", True, True),
    ("State Minority Institution Status Certificate", "State Minority Welfare Department", False, True),
    ("Trade License (Local Municipal Body)", "Local Municipal Authority", True, True),

    # ── National, but commonly audited alongside the above ──
    ("POSH Act — Internal Complaints Committee (ICC) Constitution Certificate", "Internal Complaints Committee", True, False),
    ("UGC Anti-Ragging Compliance / Affidavit Certificate", "UGC / Anti-Ragging Committee", True, False),

    # ── Professional-council approvals, for tenants running those programs ──
    ("NCTE Recognition (B.Ed / Education Programs)", "NCTE", True, False),
    ("Pharmacy Council Approval (PCI / State Pharmacy Council)", "PCI / State Pharmacy Council", True, False),
    ("Bar Council of India Affiliation (Law Programs)", "Bar Council of India", True, False),
]


class Command(BaseCommand):
    help = "Seeds the ComplianceCertificateType catalog with a curated national + state-varying starter list, for every tenant schema. Safe to re-run — only creates missing types."

    def handle(self, *args, **options):
        tenants = Tenant.objects.exclude(schema_name='public')

        for tenant in tenants:
            with tenant_context(tenant):
                created_count = 0
                for name, issuing_authority, renews_annually, varies_by_state in CATALOG:
                    _, created = ComplianceCertificateType.objects.get_or_create(
                        name=name,
                        defaults={
                            "issuing_authority": issuing_authority,
                            "renews_annually": renews_annually,
                            "varies_by_state": varies_by_state,
                        },
                    )
                    if created:
                        created_count += 1

                self.stdout.write(self.style.SUCCESS(
                    f"Schema '{tenant.schema_name}': {created_count} certificate type(s) seeded."
                ))

        self.stdout.write(self.style.SUCCESS("Compliance certificate type seed completed for all schemas."))

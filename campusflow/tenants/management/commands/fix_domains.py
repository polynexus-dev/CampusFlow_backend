"""
Management command: fix_domains
================================
Updates stale/development tenant domain records (e.g. *.localhost) to their
correct production equivalents based on the tenant's schema_name.

Usage:
    python manage.py fix_domains --base-domain campusflow.polynexus.in

Options:
    --base-domain   The production root domain (e.g. campusflow.polynexus.in).
                    Each tenant will be assigned: {schema_name}.{base-domain}
    --dry-run       Print what would change without writing to the database.
"""

from django.core.management.base import BaseCommand
from tenants.models import Tenant, Domain


class Command(BaseCommand):
    help = "Update stale tenant domain records to production-correct values."

    def add_arguments(self, parser):
        parser.add_argument(
            '--base-domain',
            type=str,
            required=True,
            help='The production root domain, e.g. campusflow.polynexus.in',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Print changes without writing to the database.',
        )

    def handle(self, *args, **options):
        base_domain = options['base_domain'].strip().lstrip('.')
        dry_run = options['dry_run']

        if dry_run:
            self.stdout.write(self.style.WARNING('[DRY RUN] No changes will be written.\n'))

        tenants = Tenant.objects.exclude(schema_name='public')

        if not tenants.exists():
            self.stdout.write(self.style.NOTICE('No non-public tenants found. Nothing to do.'))
            return

        updated = 0
        skipped = 0

        for tenant in tenants:
            target_domain = f"{tenant.schema_name}.{base_domain}"

            try:
                primary = tenant.get_primary_domain()
            except Exception:
                primary = None

            if primary is None:
                # No primary domain at all — create one
                self.stdout.write(
                    f"  [CREATE] Tenant '{tenant.name}' (schema={tenant.schema_name}): "
                    f"no primary domain found -> will create '{target_domain}'"
                )
                if not dry_run:
                    Domain.objects.create(domain=target_domain, tenant=tenant, is_primary=True)
                updated += 1
                continue

            if primary.domain == target_domain:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [OK]     Tenant '{tenant.name}' (schema={tenant.schema_name}): "
                        f"domain already correct ({primary.domain})"
                    )
                )
                skipped += 1
                continue

            old_domain = primary.domain
            self.stdout.write(
                f"  [UPDATE] Tenant '{tenant.name}' (schema={tenant.schema_name}): "
                f"'{old_domain}' -> '{target_domain}'"
            )
            if not dry_run:
                primary.domain = target_domain
                primary.save()
            updated += 1

        self.stdout.write('')
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'[DRY RUN] Would update {updated} domain(s). {skipped} already correct.'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Done. Updated {updated} domain(s). {skipped} already correct.'
                )
            )

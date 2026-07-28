"""
Management command: fix_domains
================================
Updates stale/development tenant domain records (e.g. *.localhost) and associated
tenant configuration / user email domains to their correct production equivalents.

Usage:
    python manage.py fix_domains --base-domain campusnexus.in

Options:
    --base-domain   The production root domain (e.g. campusnexus.in).
                    Each tenant will be assigned: {schema_name}.{base-domain}
    --dry-run       Print what would change without writing to the database.
"""

from django.core.management.base import BaseCommand
from tenants.models import Tenant, Domain
from django.contrib.auth.models import User
from django_tenants.utils import schema_context


class Command(BaseCommand):
    help = "Update stale tenant domain records and user emails to production-correct values."

    def add_arguments(self, parser):
        parser.add_argument(
            '--base-domain',
            type=str,
            required=True,
            help='The production root domain, e.g. campusnexus.in',
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

        # Fix public tenant primary domain if needed
        public_tenant = Tenant.objects.filter(schema_name='public').first()
        if public_tenant:
            target_public_domain = base_domain
            primary_pub = Domain.objects.filter(tenant=public_tenant, is_primary=True).first()
            if primary_pub and primary_pub.domain != target_public_domain:
                self.stdout.write(
                    f"  [UPDATE PUBLIC DOMAIN] '{primary_pub.domain}' -> '{target_public_domain}'"
                )
                if not dry_run:
                    primary_pub.domain = target_public_domain
                    primary_pub.save()

        tenants = Tenant.objects.exclude(schema_name='public')

        if not tenants.exists():
            self.stdout.write(self.style.NOTICE('No non-public tenants found.'))
            return

        updated_domains = 0
        skipped_domains = 0
        updated_emails = 0

        for tenant in tenants:
            target_tenant_domain = f"{tenant.schema_name}.{base_domain}"

            # 1. Update Domain table
            try:
                primary = tenant.get_primary_domain()
            except Exception:
                primary = None

            if primary is None:
                self.stdout.write(
                    f"  [CREATE DOMAIN] Tenant '{tenant.name}' (schema={tenant.schema_name}): "
                    f"no primary domain found -> will create '{target_tenant_domain}'"
                )
                if not dry_run:
                    Domain.objects.create(domain=target_tenant_domain, tenant=tenant, is_primary=True)
                updated_domains += 1
            elif primary.domain != target_tenant_domain:
                old_domain = primary.domain
                self.stdout.write(
                    f"  [UPDATE DOMAIN] Tenant '{tenant.name}' (schema={tenant.schema_name}): "
                    f"'{old_domain}' -> '{target_tenant_domain}'"
                )
                if not dry_run:
                    primary.domain = target_tenant_domain
                    primary.save()
                updated_domains += 1
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  [OK DOMAIN]     Tenant '{tenant.name}' (schema={tenant.schema_name}): "
                        f"domain is correct ({primary.domain})"
                    )
                )
                skipped_domains += 1

            # 2. Update Tenant permitted_email_domain & contact_email
            changed_fields = []
            if tenant.permitted_email_domain != target_tenant_domain:
                self.stdout.write(
                    f"  [UPDATE TENANT EMAIL DOMAIN] Tenant '{tenant.schema_name}': "
                    f"'{tenant.permitted_email_domain}' -> '{target_tenant_domain}'"
                )
                tenant.permitted_email_domain = target_tenant_domain
                changed_fields.append('permitted_email_domain')

            if tenant.contact_email and ('@localhost' in tenant.contact_email or '@demo.localhost' in tenant.contact_email):
                new_contact = tenant.contact_email.split('@')[0] + f"@{target_tenant_domain}"
                self.stdout.write(
                    f"  [UPDATE TENANT CONTACT EMAIL] Tenant '{tenant.schema_name}': "
                    f"'{tenant.contact_email}' -> '{new_contact}'"
                )
                tenant.contact_email = new_contact
                changed_fields.append('contact_email')

            if changed_fields and not dry_run:
                tenant.save(update_fields=changed_fields)

            # 3. Update User emails within tenant schema
            with schema_context(tenant.schema_name):
                users_with_local_email = User.objects.filter(email__icontains='localhost')
                for u in users_with_local_email:
                    prefix = u.email.split('@')[0] if '@' in u.email else u.username
                    new_email = f"{prefix}@{target_tenant_domain}"
                    self.stdout.write(
                        f"  [UPDATE USER EMAIL] User '{u.username}' in schema '{tenant.schema_name}': "
                        f"'{u.email}' -> '{new_email}'"
                    )
                    if not dry_run:
                        u.email = new_email
                        u.save(update_fields=['email'])
                    updated_emails += 1

        self.stdout.write('')
        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f'[DRY RUN] Would update {updated_domains} domain(s), {updated_emails} user email(s).'
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f'Done! Updated {updated_domains} domain(s) and {updated_emails} user email(s).'
                )
            )


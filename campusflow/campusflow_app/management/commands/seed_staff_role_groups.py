"""
Management command: seed_staff_role_groups

Backfills the functional non-teaching-staff Groups (Librarian, Hostel Warden,
Store Manager, Placement Officer, Fee Counter, Transport Coordinator,
Payroll Officer, Admissions Officer, Scholarship Officer, Accounts Officer —
see permissions.NON_TEACHING_STAFF_ROLES) into every existing tenant schema.

New tenants get these Groups automatically at provisioning time
(tenants/serializers.py), but that list didn't exist for tenants created
before this change — without this backfill, assign_role_permissions() would
raise "Group does not exist" the first time a College Admin tries to create
one of these roles in an older tenant.

Usage:
    python manage.py seed_staff_role_groups [--schema testcollege]
"""
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django_tenants.utils import schema_context

from campusflow_app.permissions import NON_TEACHING_STAFF_ROLES
from tenants.models import Tenant


class Command(BaseCommand):
    help = "Creates the functional non-teaching-staff Groups in every tenant schema that's missing them."

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema', type=str, default=None,
            help='Specific tenant schema to seed (if omitted, seeds all tenants)',
        )

    def handle(self, *args, **options):
        target_schema = options['schema']
        if target_schema:
            schemas = [target_schema]
        else:
            schemas = [s for s in Tenant.objects.values_list('schema_name', flat=True) if s != 'public']

        self.stdout.write(self.style.MIGRATE_HEADING(f"\nSeeding staff-role groups across schemas: {schemas}\n"))

        for schema in schemas:
            try:
                with schema_context(schema):
                    created_names = []
                    for role_name in NON_TEACHING_STAFF_ROLES:
                        _, created = Group.objects.get_or_create(name=role_name)
                        if created:
                            created_names.append(role_name)
                    if created_names:
                        self.stdout.write(self.style.SUCCESS(f"  {schema}: created {', '.join(created_names)}"))
                    else:
                        self.stdout.write(f"  {schema}: already up to date")
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"  {schema}: failed — {e}"))

        self.stdout.write(self.style.SUCCESS("\nDone.\n"))

from django.core.management.base import BaseCommand, CommandError
from tenants.models import Tenant, Domain


class Command(BaseCommand):
    help = "Create a new tenant (college) with a domain."

    def add_arguments(self, parser):
        parser.add_argument('--name', type=str, required=True, help='Name of the college/tenant')
        parser.add_argument('--schema', type=str, required=True, help='Schema name (lowercase, no spaces, e.g. "mit_college")')
        parser.add_argument('--domain', type=str, required=True, help='Domain for this tenant (e.g. "mit.localhost")')
        parser.add_argument('--code', type=str, default=None, help='Short code for the college (optional)')
        parser.add_argument('--email', type=str, default=None, help='Contact email (optional)')
        parser.add_argument('--address', type=str, default=None, help='Address (optional)')
        parser.add_argument('--is-primary', action='store_true', default=True, help='Mark domain as primary (default: True)')

    def handle(self, *args, **options):
        schema_name = options['schema'].lower().replace(' ', '_').replace('-', '_')

        # Validate schema name
        if not schema_name.isidentifier():
            raise CommandError(f"Invalid schema name '{schema_name}'. Use only letters, numbers, and underscores.")

        # Check if tenant already exists
        if Tenant.objects.filter(schema_name=schema_name).exists():
            raise CommandError(f"Tenant with schema '{schema_name}' already exists.")

        # Check if domain already exists
        if Domain.objects.filter(domain=options['domain']).exists():
            raise CommandError(f"Domain '{options['domain']}' already exists.")

        self.stdout.write(f"Creating tenant '{options['name']}' with schema '{schema_name}'...")

        # Create tenant (this also creates the schema and runs migrations)
        tenant = Tenant(
            name=options['name'],
            schema_name=schema_name,
            code=options.get('code'),
            contact_email=options.get('email'),
            address=options.get('address'),
        )
        tenant.save()

        # Create domain
        domain = Domain(
            domain=options['domain'],
            tenant=tenant,
            is_primary=options['is_primary'],
        )
        domain.save()

        self.stdout.write(self.style.SUCCESS(
            f"\n✅ Tenant created successfully!"
            f"\n   Name:    {tenant.name}"
            f"\n   Schema:  {tenant.schema_name}"
            f"\n   Domain:  {domain.domain}"
            f"\n   Primary: {domain.is_primary}"
        ))

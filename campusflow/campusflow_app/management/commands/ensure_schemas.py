from django.core.management.base import BaseCommand
from django.db import connection
from django_tenants.postgresql_backend.base import is_valid_schema_name
from django_tenants.utils import get_public_schema_name, get_tenant_model


class Command(BaseCommand):
    """
    Pre-flight for migrate_schemas (run by entrypoint.sh before it): make sure
    the public schema and every schema named in the tenant table exist.

    migrate_schemas points the connection at each schema and creates
    django_migrations there *before* any migrate command (including
    tenant_safe_migrate) gets to run, so a missing schema fails with
    "no schema has been selected to create in" and the container crash-loops.
    That happens when a Tenant row outlives its schema: a partial pg_restore,
    a manually dropped schema, or a tenant save whose schema creation failed.

    Creating the missing schema lets migrations proceed, but that college's
    data is NOT in it — the warning below is the cue to restore it from backup.
    Uses raw SQL only, so it works even when the public schema itself is gone.
    """

    help = "Create the public schema and any tenant schema that is missing, before migrate_schemas."

    def handle(self, *args, **options):
        public = get_public_schema_name()
        table = get_tenant_model()._meta.db_table

        with connection.cursor() as cursor:
            cursor.execute("SELECT nspname FROM pg_namespace")
            existing = {row[0] for row in cursor.fetchall()}

            wanted = [public]
            cursor.execute("SELECT to_regclass(%s)", [f'"{public}"."{table}"'])
            if cursor.fetchone()[0]:
                cursor.execute(f'SELECT schema_name FROM "{public}"."{table}"')
                wanted += [row[0] for row in cursor.fetchall() if row[0] != public]

            created = []
            for schema in wanted:
                if schema in existing:
                    continue
                if not is_valid_schema_name(schema):
                    self.stderr.write(self.style.ERROR(
                        f"  Tenant schema name {schema!r} is invalid; fix or delete that row in {table}."
                    ))
                    continue
                cursor.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')
                created.append(schema)

        if not created:
            self.stdout.write(f"  All {len(wanted)} schema(s) present.")
            return
        for schema in created:
            if schema == public:
                self.stdout.write(self.style.WARNING(f"  Created missing schema '{schema}'."))
            else:
                self.stdout.write(self.style.WARNING(
                    f"  Created missing schema '{schema}' for an existing tenant. It will be "
                    "migrated empty - restore this college's data from backup if it had any."
                ))

"""
Management command: seed_all_demo

One-shot orchestrator that runs every "well-behaved" seed command (the ones
that already take --schema/--tenant and are safe to re-run) against a single
tenant schema, in dependency order. Identical on a local dev machine and on
the VM — it's the same Django management command either way, so there's
nothing environment-specific to configure beyond which schema to target.

Deliberately does NOT include:
  - The tenant-creation flow (creating the Tenant/Domain rows themselves) —
    this command seeds an *existing* tenant's schema. Create the tenant first
    (via the normal signup flow, or python manage.py shell < seed_demo_data.py
    at the repo root for a from-scratch 'demo' tenant with its own Groups/
    Departments/base users already baked in).
  - seed_test_users.py / seed_large_users.py (root-level scripts) — these
    hardcode or require editing a TARGET_SCHEMA constant inside the file
    rather than taking --schema, so they can't be safely parameterized here.
  - test_data.py (root-level, "python manage.py shell < test_data.py") — a
    much heavier seed covering hostels/fees/library/bus/exams. Left as an
    explicit separate step so a slow, broad rewrite of demo data is always a
    deliberate choice, not a side effect of running this command.
  - populate_campusnexus_remote.py — hits a live remote API
    (https://api.campusnexus.in) over HTTP, not the local database. Never
    chained into an automated seeder; run it standalone and deliberately.

See Docs/seeding_guide.md for the full picture and exact VM usage.

Usage:
    python manage.py seed_all_demo --schema testcollege
    python manage.py seed_all_demo --schema demo --weeks 4
"""
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from tenants.models import Tenant

# (step name, callable) — order matters: groups before any user/profile
# creation, academic structure before the course/schedule data that hangs
# off it, audit logs last since they're meant to read as "recent activity"
# on top of everything else.
STEPS = [
    ("staff-role groups", lambda schema, weeks: call_command("seed_staff_role_groups", schema=schema)),
    ("academic spine", lambda schema, weeks: call_command("seed_academic_spine", tenant=schema)),
    ("demo dataset (courses/schedules/lectures)", lambda schema, weeks: call_command("seed_demo_data", schema=schema, weeks=weeks)),
    ("accreditation criteria", lambda schema, weeks: call_command("seed_accreditation_criteria")),
    ("compliance certificate types", lambda schema, weeks: call_command("seed_compliance_certificate_types")),
    ("audit logs", lambda schema, weeks: call_command("seed_audit_logs", schema=schema)),
]


class Command(BaseCommand):
    help = "Runs every well-behaved seed command against one tenant schema, in dependency order."

    def add_arguments(self, parser):
        parser.add_argument(
            "--schema", type=str, required=True,
            help="Tenant schema to seed. Must already exist (create the tenant first).",
        )
        parser.add_argument(
            "--weeks", type=int, default=2,
            help="Passed through to seed_demo_data: weeks of past lectures to create (default: 2).",
        )

    def handle(self, *args, **options):
        schema = options["schema"]
        weeks = options["weeks"]

        if not Tenant.objects.filter(schema_name=schema).exists():
            raise CommandError(
                f"No tenant with schema '{schema}' exists yet. Create the tenant first "
                f"(signup flow, or 'python manage.py shell < seed_demo_data.py' at the repo "
                f"root for a fresh 'demo' tenant), then re-run this command."
            )

        self.stdout.write(self.style.MIGRATE_HEADING(f"\nSeeding all demo data for schema '{schema}'\n"))

        results = []
        for name, step in STEPS:
            self.stdout.write(f"-> {name} ...")
            try:
                step(schema, weeks)
                results.append((name, True, None))
                self.stdout.write(self.style.SUCCESS(f"   done: {name}"))
            except Exception as e:
                results.append((name, False, str(e)))
                self.stdout.write(self.style.ERROR(f"   FAILED: {name} — {e}"))

        self.stdout.write(self.style.MIGRATE_HEADING("\nSummary\n"))
        failed = [r for r in results if not r[1]]
        for name, ok, err in results:
            mark = "OK  " if ok else "FAIL"
            self.stdout.write(f"  [{mark}] {name}")

        if failed:
            raise CommandError(f"\n{len(failed)} of {len(results)} step(s) failed — see above.")

        self.stdout.write(self.style.SUCCESS(f"\nAll {len(results)} steps completed for schema '{schema}'.\n"))

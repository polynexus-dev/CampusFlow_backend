"""
Management command: verify_academic_backfill

Step 3 of the parallel-run cutover. Checks the invariants a correct backfill
must satisfy, and exits non-zero if any hard invariant is violated — meant to
be run in CI or a cron job as a gate before any call site (starting with
BulkGenerateInvoicesView in a later change) is allowed to trust the FKs.

Checks:
  V1  Coverage          — informational: how many students have each FK set.
  V2  Mirror drift       — informational: legacy strings not yet in canonical
                           form. NOT a failure — pre-existing format variance
                           ("4th Semester" vs "Semester 4") is expected until a
                           row is saved or --normalize-legacy-strings has run;
                           it does not mean the FK itself is wrong.
  V3  Section ⊂ Batch    — HARD FAIL. A student's section must belong to their
                           own batch; this should be impossible by construction
                           (backfill_student_academics only ever resolves a
                           section within the batch it just resolved), so any
                           violation means something else wrote these FKs.
  V4  Program ⊂ Batch     — HARD FAIL, same reasoning as V3 for program vs the
                           batch's own program.
  V5  Fee structure parity — HARD FAIL. For every FeeStructure that has at
                           least one structured FK field set, the roster the
                           legacy strings would match must equal the roster the
                           FKs would match. This is the gate PR-4 needs before
                           any billing call site is cut over — a mismatch here
                           is a live under- or over-billing risk.
  V6  Unresolved worklist — informational: legacy value combinations backfill
                           could not resolve, for the admin to act on.

Usage:
    python manage.py verify_academic_backfill --tenant=all
"""

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context
from tenants.models import Tenant

from campusflow_app.models.fees import FeeStructure
from campusflow_app.models.profile import StudentProfile
from campusflow_app.services.academic_roster import resolve_student_roster


class Command(BaseCommand):
    help = "Verifies the academic backfill's invariants. Exits non-zero on any hard failure."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default="all")

    def handle(self, *args, **options):
        tenants = self._resolve_tenants(options["tenant"])
        failures = []

        for tenant in tenants:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {tenant.schema_name} ==="))
            with schema_context(tenant.schema_name):
                failures.extend(
                    f"{tenant.schema_name}: {msg}" for msg in self._verify_tenant()
                )

        if failures:
            self.stdout.write(self.style.ERROR(f"\n{len(failures)} hard failure(s):"))
            for f in failures:
                self.stdout.write(self.style.ERROR(f"  - {f}"))
            raise CommandError(f"{len(failures)} verification failure(s). See output above.")

        self.stdout.write(self.style.SUCCESS("\nAll hard invariants pass."))

    def _resolve_tenants(self, tenant_arg):
        if tenant_arg == "all":
            return list(Tenant.objects.exclude(schema_name="public"))
        tenant = Tenant.objects.filter(schema_name=tenant_arg).first()
        if not tenant:
            raise CommandError(f"No tenant with schema '{tenant_arg}' exists.")
        return [tenant]

    def _verify_tenant(self):
        """Returns a list of hard-failure messages (empty if all pass)."""
        failures = []
        self._v1_coverage()
        self._v2_mirror_drift()
        failures += self._v3_section_within_batch()
        failures += self._v4_program_matches_batch()
        failures += self._v5_fee_structure_parity()
        self._v6_unresolved_worklist()
        return failures

    # ── V1 ────────────────────────────────────────────────────────────

    def _v1_coverage(self):
        total = StudentProfile.objects.count()
        if total == 0:
            self.stdout.write("  V1 Coverage: no students in this tenant.")
            return
        has_program = StudentProfile.objects.filter(program__isnull=False).count()
        has_batch = StudentProfile.objects.filter(batch__isnull=False).count()
        has_section = StudentProfile.objects.filter(section__isnull=False).count()
        has_sem = StudentProfile.objects.filter(current_semester_number__isnull=False).count()
        self.stdout.write(
            f"  V1 Coverage: {total} students — "
            f"program {has_program} ({100*has_program//total}%), "
            f"batch {has_batch} ({100*has_batch//total}%), "
            f"section {has_section} ({100*has_section//total}%), "
            f"semester {has_sem} ({100*has_sem//total}%)"
        )

    # ── V2 ────────────────────────────────────────────────────────────

    def _v2_mirror_drift(self):
        drifted = 0
        for sp in StudentProfile.objects.filter(current_semester_number__isnull=False).only(
            "current_semester_number", "current_semester_year"
        ):
            expected = f"Semester {sp.current_semester_number}"
            if sp.current_semester_year != expected:
                drifted += 1
        self.stdout.write(
            f"  V2 Mirror drift: {drifted} row(s) with a non-canonical current_semester_year "
            f"(informational only — resolves as rows are saved or via --normalize-legacy-strings)."
        )

    # ── V3 ────────────────────────────────────────────────────────────

    def _v3_section_within_batch(self):
        failures = []
        count = 0
        for sp in StudentProfile.objects.filter(section__isnull=False, batch__isnull=False).select_related("section"):
            if sp.section.batch_id != sp.batch_id:
                count += 1
        if count:
            failures.append(f"V3: {count} student(s) whose section does not belong to their own batch.")
        self.stdout.write(f"  V3 Section-within-batch: {count} violation(s).")
        return failures

    # ── V4 ────────────────────────────────────────────────────────────

    def _v4_program_matches_batch(self):
        failures = []
        count = 0
        for sp in StudentProfile.objects.filter(batch__isnull=False, program__isnull=False).select_related("batch"):
            if sp.batch.program_id != sp.program_id:
                count += 1
        if count:
            failures.append(f"V4: {count} student(s) whose program does not match their batch's program.")
        self.stdout.write(f"  V4 Program-matches-batch: {count} violation(s).")
        return failures

    # ── V5 ────────────────────────────────────────────────────────────

    def _v5_fee_structure_parity(self):
        failures = []
        checked = 0
        for fs in FeeStructure.objects.all():
            has_any_fk = any([fs.program_id, fs.batch_id, fs.semester_number, fs.academic_year_ref_id])
            if not has_any_fk:
                continue  # not yet migrated for this structure — nothing to compare
            checked += 1

            _, diagnostics = resolve_student_roster(
                department_id=fs.department_id,
                program_id=fs.program_id, legacy_program=fs.program_enrolled_in,
                batch_id=fs.batch_id, legacy_batch=fs.batch_academic_year,
                semester_number=fs.semester_number, legacy_semester=fs.current_semester_year,
            )
            if diagnostics["unresolved_by_fk"] > 0:
                failures.append(
                    f"V5: FeeStructure '{fs.name}' (id={fs.id}) — "
                    f"{diagnostics['unresolved_by_fk']} of {diagnostics['matched']} matched students "
                    f"would be missed by FK-only matching."
                )
        self.stdout.write(
            f"  V5 Fee structure parity: checked {checked} structure(s) with an FK set, "
            f"{len(failures)} with a mismatch."
        )
        return failures

    # ── V6 ────────────────────────────────────────────────────────────

    def _v6_unresolved_worklist(self):
        rows = StudentProfile.objects.filter(batch__isnull=True).values(
            "program_enrolled_in", "batch_academic_year", "current_semester_year"
        )
        groups = defaultdict(int)
        for row in rows:
            key = (row["program_enrolled_in"], row["batch_academic_year"], row["current_semester_year"])
            groups[key] += 1

        if not groups:
            self.stdout.write("  V6 Unresolved worklist: empty — every student has a batch.")
            return

        self.stdout.write(f"  V6 Unresolved worklist: {len(groups)} distinct combination(s):")
        for (program, batch, semester), count in sorted(groups.items(), key=lambda kv: -kv[1])[:20]:
            self.stdout.write(f"    [{count:>4}] program='{program}' batch='{batch}' semester='{semester}'")

"""
Management command: seed_academic_spine

Step 1 of the parallel-run cutover for the four free-text StudentProfile
academic fields (program_enrolled_in, batch_academic_year, current_semester_year,
section_division). Run this BEFORE backfill_student_academics.

It does two things, and only two:

  1. Provisions AcademicYear/Term (via services.academics.get_current_term) and
     the default GradingScheme/GradeBand (via get_default_grading_scheme) for
     every tenant explicitly, rather than waiting for the first API hit to do
     it lazily. Idempotent — get_or_create underneath.

  2. Reports what Programs and Batches the existing legacy data implies, so an
     administrator can create the real Program/Regulation rows with informed
     judgment before backfill_student_academics tries to match against them.

It NEVER creates a Program, Regulation, Batch or Section. Inventing a Program
from a free-text string is worse than leaving a student unbackfilled — a wrong
program silently mis-grades a student against someone else's curriculum, while
an unbackfilled student is merely incomplete and visible as such in every
report this command and the backfill command produce.

Usage:
    python manage.py seed_academic_spine --tenant=all
    python manage.py seed_academic_spine --tenant=demo
"""

from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context
from tenants.models import Tenant

from campusflow_app.models.academics import Program
from campusflow_app.models.course import Course
from campusflow_app.models.profile import StudentProfile
from campusflow_app.services.academics import get_current_term, get_default_grading_scheme
from campusflow_app.utils.academic_parse import (
    normalize_program_text,
    parse_academic_year_or_batch_span,
)


class Command(BaseCommand):
    help = (
        "Provisions the academic calendar and default grading scheme, and reports "
        "the Program/Batch candidates implied by existing student data. Never "
        "creates a Program, Regulation, Batch or Section — report only for those."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--tenant", default="all",
            help="Schema name to run against, or 'all' for every non-public tenant.",
        )

    def handle(self, *args, **options):
        tenants = self._resolve_tenants(options["tenant"])
        for tenant in tenants:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {tenant.schema_name} ==="))
            with schema_context(tenant.schema_name):
                self._provision_calendar_and_grading()
                self._report_program_candidates()
                self._report_batch_candidates()

    def _resolve_tenants(self, tenant_arg):
        if tenant_arg == "all":
            return list(Tenant.objects.exclude(schema_name="public"))
        tenant = Tenant.objects.filter(schema_name=tenant_arg).first()
        if not tenant:
            raise CommandError(f"No tenant with schema '{tenant_arg}' exists.")
        return [tenant]

    def _provision_calendar_and_grading(self):
        term = get_current_term()
        scheme = get_default_grading_scheme()
        self.stdout.write(
            f"  Calendar: current term is '{term}'. "
            f"Grading: default scheme '{scheme}' with {scheme.bands.count()} bands."
        )

    def _report_program_candidates(self):
        rows = (
            StudentProfile.objects.filter(batch__isnull=True)
            .exclude(program_enrolled_in__isnull=True)
            .exclude(program_enrolled_in="")
            .values("program_enrolled_in", "department_id", "department__name")
        )

        # Group by (raw text, department) so the report is department-scoped —
        # the same string in two departments may resolve completely differently.
        groups = defaultdict(int)
        dept_names = {}
        for row in rows:
            key = (row["program_enrolled_in"], row["department_id"])
            groups[key] += 1
            dept_names[row["department_id"]] = row["department__name"]

        if not groups:
            self.stdout.write("  No unbackfilled program_enrolled_in values found.")
            return

        self.stdout.write(f"  {len(groups)} distinct (program_enrolled_in, department) pairs:")
        for (raw_text, dept_id), count in sorted(groups.items(), key=lambda kv: -kv[1]):
            dept_label = dept_names.get(dept_id) or "(no department)"
            classification = self._classify_program_text(raw_text, dept_id)
            self.stdout.write(f"    [{count:>4} students] '{raw_text}' / {dept_label} -> {classification}")

    def _classify_program_text(self, raw_text, department_id):
        """Mirrors the 3-tier matching backfill_student_academics will perform,
        so the report tells the admin exactly what will happen without writing
        anything. Never expands beyond reporting a classification string."""
        programs = Program.objects.filter(department_id=department_id) if department_id else Program.objects.all()

        exact = list(programs.filter(code__iexact=raw_text) | programs.filter(
            short_name__iexact=raw_text
        ) | programs.filter(name__iexact=raw_text))
        if len(exact) == 1:
            return f"MATCHES existing program '{exact[0]}'"
        if len(exact) > 1:
            return f"AMBIGUOUS — exactly matches {len(exact)} programs, will stay unresolved"

        courses = Course.objects.filter(department_id=department_id) if department_id else Course.objects.all()
        if courses.filter(course_name__iexact=raw_text).exists():
            fallback = programs.filter(is_active=True)
            if fallback.count() == 1:
                return (
                    f"looks like a COURSE NAME, not a program — will fall back to "
                    f"the department's only active program '{fallback.first()}'"
                )
            return "looks like a COURSE NAME, not a program — no unambiguous department fallback, will stay unresolved"

        normalized = normalize_program_text(raw_text)
        fuzzy_matches = [p for p in programs if normalize_program_text(p.name) == normalized
                          or normalize_program_text(p.short_name) == normalized
                          or normalize_program_text(p.code) == normalized]
        if len(fuzzy_matches) == 1:
            return f"fuzzy-matches existing program '{fuzzy_matches[0]}'"
        if len(fuzzy_matches) > 1:
            return f"AMBIGUOUS — fuzzy-matches {len(fuzzy_matches)} programs, will stay unresolved"

        return "NO MATCH — create a Program for this before running the backfill, or it will stay unresolved"

    def _report_batch_candidates(self):
        rows = (
            StudentProfile.objects.filter(batch__isnull=True)
            .exclude(batch_academic_year__isnull=True)
            .exclude(batch_academic_year="")
            .values_list("batch_academic_year", flat=True)
        )
        groups = defaultdict(int)
        for value in rows:
            groups[value] += 1

        if not groups:
            self.stdout.write("  No unbackfilled batch_academic_year values found.")
            return

        self.stdout.write(f"  {len(groups)} distinct batch_academic_year values:")
        for raw_text, count in sorted(groups.items(), key=lambda kv: -kv[1]):
            parsed = parse_academic_year_or_batch_span(raw_text)
            if parsed is None:
                label = "UNPARSEABLE — will stay unresolved"
            elif parsed["kind"] == "batch_span":
                label = f"batch span {parsed['start_year']}-{parsed['end_year']}"
            else:
                label = f"looks like an academic YEAR ({parsed['name']}), not a batch span"
            self.stdout.write(f"    [{count:>4} students] '{raw_text}' -> {label}")

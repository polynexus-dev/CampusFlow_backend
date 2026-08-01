"""
Management command: backfill_student_academics

Step 2 of the parallel-run cutover. Sets StudentProfile.program / batch /
section / current_semester_number from the four legacy free-text fields
(program_enrolled_in, batch_academic_year, current_semester_year,
section_division), for students that don't have them yet.

Run seed_academic_spine first, and create any Program/Regulation rows its
report says are missing — this command matches against what already exists and
never invents a Program. A wrong Program silently mis-grades a student against
someone else's curriculum; an unresolved student is merely incomplete, and is
listed as such in this command's own report every time it runs.

Idempotent and resumable: a student is only touched if at least one of the
five target fields would actually change, so re-running after creating more
Programs picks up exactly the newly-resolvable students and leaves everyone
else alone.

--dry-run resolves and reports without writing ANYTHING, including the Batch
and Section rows that a real run may create as a side effect of resolution —
not just the final StudentProfile update. A batch or section that "would be
created" is represented in the report by its would-be name, never by an
unsaved model instance, so a dry run genuinely cannot leave rows behind.

Non-dry-run writes to StudentProfile use bulk_update, which does NOT invoke
.save() and therefore does NOT fire the audit pre_save/post_save signals or
the _sync_legacy_academic_fields() mirror. That is deliberate: 2000 students
via .save() would be ~6000 SQL statements and 2000 AuditLog rows for a single
maintenance run; bulk_update is a handful of statements, and this command
writes one summary to stdout instead. It is also why the legacy strings are
left untouched by this command — they already hold the values used to derive
the FKs, and fall back into sync automatically the next time anything calls
.save() on a touched row (or immediately, via --normalize-legacy-strings).

Usage:
    python manage.py backfill_student_academics --tenant=demo --dry-run
    python manage.py backfill_student_academics --tenant=demo --report=/tmp/demo_backfill.csv
    python manage.py backfill_student_academics --tenant=all
"""

import csv

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django_tenants.utils import schema_context
from tenants.models import Tenant

from campusflow_app.models.academics import Batch, Program, Regulation, Section
from campusflow_app.models.course import Course
from campusflow_app.models.profile import StudentProfile
from campusflow_app.utils.academic_parse import (
    normalize_program_text,
    normalize_section_name,
    parse_academic_year_or_batch_span,
    parse_semester_number,
)


class Command(BaseCommand):
    help = (
        "Backfills StudentProfile.program/batch/section/current_semester_number "
        "from the legacy free-text academic fields. Never creates a Program."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default="all")
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Resolve and report, but write nothing — including Batch/Section rows.",
        )
        parser.add_argument(
            "--report", default=None,
            help="Path to write a per-student CSV report. The printed summary always happens either way.",
        )
        parser.add_argument(
            "--normalize-legacy-strings", action="store_true",
            help="After backfilling, also rewrite the legacy CharFields to canonical "
                 "form (e.g. '4th Semester' -> 'Semester 4') for every row touched.",
        )

    def handle(self, *args, **options):
        tenants = self._resolve_tenants(options["tenant"])
        for tenant in tenants:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {tenant.schema_name} ==="))
            with schema_context(tenant.schema_name):
                self._backfill_tenant(
                    dry_run=options["dry_run"],
                    report_path=options["report"],
                    normalize=options["normalize_legacy_strings"],
                )

    def _resolve_tenants(self, tenant_arg):
        if tenant_arg == "all":
            return list(Tenant.objects.exclude(schema_name="public"))
        tenant = Tenant.objects.filter(schema_name=tenant_arg).first()
        if not tenant:
            raise CommandError(f"No tenant with schema '{tenant_arg}' exists.")
        return [tenant]

    # ── per-tenant run ────────────────────────────────────────────────

    def _backfill_tenant(self, *, dry_run, report_path, normalize):
        students = StudentProfile.objects.filter(batch__isnull=True).select_related("department")
        total = students.count()
        if total == 0:
            self.stdout.write("  Nothing to backfill — every student already has a batch.")
            return

        rows = []          # per-student report rows
        to_update = []      # StudentProfile instances with a real, persisted FK assigned
        counts = {"program": 0, "batch": 0, "section": 0, "semester": 0}
        students_with_any_resolution = 0

        for student in students.iterator(chunk_size=500):
            resolution = self._resolve_student(student, dry_run=dry_run)
            rows.append(resolution)

            changed = False
            any_resolved = False

            if resolution["program_would_resolve"]:
                counts["program"] += 1
                any_resolved = True
            if resolution["program_obj"] is not None:
                student.program = resolution["program_obj"]
                changed = True

            if resolution["batch_would_resolve"]:
                counts["batch"] += 1
                any_resolved = True
            if resolution["batch_obj"] is not None:
                student.batch = resolution["batch_obj"]
                changed = True

            if resolution["section_would_resolve"]:
                counts["section"] += 1
                any_resolved = True
            if resolution["section_obj"] is not None:
                student.section = resolution["section_obj"]
                changed = True

            if resolution["semester_number"] is not None:
                counts["semester"] += 1
                any_resolved = True
                student.current_semester_number = resolution["semester_number"]
                changed = True

            if any_resolved:
                students_with_any_resolution += 1
            if changed:
                to_update.append(student)

        self._print_summary(total, counts, students_with_any_resolution, dry_run)

        if report_path:
            self._write_csv(report_path, rows)
            self.stdout.write(f"  Full per-student report written to {report_path}")

        if dry_run:
            self.stdout.write(self.style.WARNING("  --dry-run: no rows written."))
            return

        if to_update:
            StudentProfile.objects.bulk_update(
                to_update,
                ["program", "batch", "section", "current_semester_number"],
                batch_size=500,
            )
            self.stdout.write(self.style.SUCCESS(f"  Updated {len(to_update)} student rows."))

        if normalize:
            self._normalize_legacy_strings(to_update)

    # ── resolution ────────────────────────────────────────────────────

    def _resolve_student(self, student, *, dry_run):
        """
        Returns a dict with, for each of program/batch/section:
          - "<x>_obj": the real, already-persisted object if one exists or was
            just created (None in a dry run whenever the row would need to be
            newly created, since a dry run must not create it) — this is what
            gets assigned onto the student for bulk_update.
          - "<x>_would_resolve": True whenever resolution would succeed
            regardless of dry_run — this is what the summary counts and the
            CSV report use, so a dry run's numbers describe what a real run
            would do.
          - "<x>_reason": human-readable explanation, always present.
        """
        result = {
            "student_id": student.student_id,
            "department": student.department.name if student.department_id else "",
            "raw_program": student.program_enrolled_in or "",
            "raw_batch": student.batch_academic_year or "",
            "raw_semester": student.current_semester_year or "",
            "raw_section": student.section_division or "",
        }

        program, program_reason, program_would_resolve = self._resolve_program(
            student.program_enrolled_in, student.department_id
        )
        result.update(
            program_obj=program, program_reason=program_reason,
            program_would_resolve=program_would_resolve,
        )

        semester_number = parse_semester_number(student.current_semester_year)
        result["semester_number"] = semester_number

        # _resolve_program never writes, so program_would_resolve always equals
        # (program is not None) — no dry-run distinction needed for it.
        batch, batch_reason, batch_would_resolve = self._resolve_batch(
            student.batch_academic_year, program, dry_run=dry_run,
        )
        result.update(batch_obj=batch, batch_reason=batch_reason, batch_would_resolve=batch_would_resolve)

        section, section_reason, section_would_resolve = self._resolve_section(
            batch, batch_would_resolve, semester_number, student.section_division, dry_run=dry_run,
        )
        result.update(
            section_obj=section, section_reason=section_reason,
            section_would_resolve=section_would_resolve,
        )

        return result

    def _resolve_program(self, raw_text, department_id):
        """Never creates anything — a Program is always an admin's decision.
        Returns (obj_or_None, reason, would_resolve)."""
        if not raw_text:
            return None, "no value", False

        programs = Program.objects.filter(department_id=department_id) if department_id \
            else Program.objects.all()

        exact_matches = list(programs.filter(
            Q(code__iexact=raw_text) | Q(short_name__iexact=raw_text) | Q(name__iexact=raw_text)
        ))
        if len(exact_matches) == 1:
            return exact_matches[0], "exact match", True
        if len(exact_matches) > 1:
            return None, f"ambiguous — {len(exact_matches)} exact matches", False

        courses = Course.objects.filter(department_id=department_id) if department_id \
            else Course.objects.all()
        if courses.filter(course_name__iexact=raw_text).exists():
            # The field holds a subject name, not a program — never map it to
            # one. The only safe inference is the department's sole program.
            fallback = list(programs.filter(is_active=True))
            if len(fallback) == 1:
                return fallback[0], "value was a course name; used department's sole program", True
            return None, "value was a course name; no unambiguous department fallback", False

        normalized = normalize_program_text(raw_text)
        fuzzy = [
            p for p in programs
            if normalize_program_text(p.name) == normalized
            or normalize_program_text(p.short_name) == normalized
            or normalize_program_text(p.code) == normalized
        ]
        if len(fuzzy) == 1:
            return fuzzy[0], "fuzzy match", True
        if len(fuzzy) > 1:
            return None, f"ambiguous — {len(fuzzy)} fuzzy matches", False

        return None, "no program found — create one, then re-run", False

    def _resolve_batch(self, raw_text, program, *, dry_run):
        """Returns (obj_or_None, reason, would_resolve). Only creates a Batch
        when not dry_run; a dry run reports what it would create but leaves
        obj as None so nothing gets assigned or persisted."""
        if not raw_text:
            return None, "no value", False
        if program is None:
            return None, "program not resolved", False

        parsed = parse_academic_year_or_batch_span(raw_text)
        if parsed is None:
            return None, "unparseable", False

        if parsed["kind"] == "academic_year" and float(program.duration_years) != 1:
            # A single-year span is only unambiguously a batch for a one-year
            # program; for anything longer this is more likely the term the
            # student is currently in, not their admission cohort, and guessing
            # here would misfile them into a cohort they were never part of.
            return None, (
                f"'{raw_text}' looks like an academic year, not a batch span, for a "
                f"{program.duration_years}-year program — left unresolved"
            ), False

        admission_year, end_year = parsed["start_year"], parsed["end_year"]

        existing = Batch.objects.filter(program=program, admission_year=admission_year).first()
        if existing:
            return existing, "matched existing batch", True

        regulation = self._unambiguous_regulation_for_year(program, admission_year)
        if regulation is None:
            return None, (
                f"no single active regulation of {program.code} covers admission year "
                f"{admission_year} — create/adjust one, then re-run"
            ), False

        if dry_run:
            return None, f"would create a new batch under regulation {regulation.code} (dry-run)", True

        batch = Batch.objects.create(
            program=program, regulation=regulation, admission_year=admission_year,
            name=f"{admission_year}-{end_year}",
        )
        return batch, f"created new batch under regulation {regulation.code}", True

    def _resolve_section(self, batch, batch_would_resolve, semester_number, raw_section, *, dry_run):
        """Returns (obj_or_None, reason, would_resolve). Only creates a Section
        when not dry_run and a real batch already exists (a section cannot
        belong to a batch that only "would" exist)."""
        if not batch_would_resolve or semester_number is None:
            return None, "batch or semester not resolved", False

        section_name = normalize_section_name(raw_section)
        if not section_name:
            return None, "no section value to resolve", False

        if batch is None:
            # The batch itself would only be created in a real run.
            return None, "would create a section once its batch exists (dry-run)", True

        existing = Section.objects.filter(
            batch=batch, semester_number=semester_number, name=section_name
        ).first()
        if existing:
            return existing, "matched existing section", True

        if dry_run:
            return None, "would create a new section (dry-run)", True

        section = Section.objects.create(batch=batch, semester_number=semester_number, name=section_name)
        return section, "created new section", True

    def _unambiguous_regulation_for_year(self, program, admission_year):
        candidates = Regulation.objects.filter(
            program=program, effective_from_year__lte=admission_year
        ).filter(Q(effective_to_year__isnull=True) | Q(effective_to_year__gte=admission_year))
        matches = list(candidates)
        return matches[0] if len(matches) == 1 else None

    # ── reporting & cleanup ───────────────────────────────────────────

    def _print_summary(self, total, counts, students_with_any_resolution, dry_run):
        verb = "would resolve" if dry_run else "resolved"
        have_verb = "would have" if dry_run else "had"
        self.stdout.write(f"  {total} students without a batch.")
        self.stdout.write(f"    {counts['program']} {verb} a program")
        self.stdout.write(f"    {counts['batch']} {verb} a batch")
        self.stdout.write(f"    {counts['section']} {verb} a section")
        self.stdout.write(f"    {counts['semester']} {verb} a semester number")
        self.stdout.write(f"    {students_with_any_resolution} students {have_verb} at least one field resolved")
        self.stdout.write(f"    {total - students_with_any_resolution} students remain fully unresolved")

    def _write_csv(self, path, rows):
        fieldnames = [
            "student_id", "department", "raw_program", "raw_batch", "raw_semester", "raw_section",
            "program_would_resolve", "program_reason",
            "batch_would_resolve", "batch_reason",
            "section_would_resolve", "section_reason",
            "semester_number",
        ]
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for row in rows:
                writer.writerow({
                    "student_id": row["student_id"],
                    "department": row["department"],
                    "raw_program": row["raw_program"],
                    "raw_batch": row["raw_batch"],
                    "raw_semester": row["raw_semester"],
                    "raw_section": row["raw_section"],
                    "program_would_resolve": row["program_would_resolve"],
                    "program_reason": row["program_reason"],
                    "batch_would_resolve": row["batch_would_resolve"],
                    "batch_reason": row["batch_reason"],
                    "section_would_resolve": row["section_would_resolve"],
                    "section_reason": row["section_reason"],
                    "semester_number": row["semester_number"] or "",
                })

    def _normalize_legacy_strings(self, students):
        """Optional cosmetic pass: rewrite the legacy CharFields to canonical
        form for rows this run touched, via individual .save() calls so the
        existing _sync_legacy_academic_fields() hook does the formatting —
        rather than reimplementing that logic a second time here."""
        if not students:
            return
        for student in students:
            student.save()
        self.stdout.write(
            f"  Normalized legacy strings on {len(students)} rows via the save() mirror."
        )

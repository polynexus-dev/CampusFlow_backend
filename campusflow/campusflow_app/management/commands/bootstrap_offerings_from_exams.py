"""
Management command: bootstrap_offerings_from_exams

Derives CourseOffering + StudentCourseRegistration rows from data that already
exists: every student who has a StudentExamResult for an exam is provably
registered for that exam's course, in that exam's term. This gives the credit
engine a real roster on day one, without asking anyone to re-enter enrollment
data that already exists in a different shape.

Depends on backfill_student_academics having run first: a student's Batch can
only be inferred here from their OWN already-resolved `batch` FK (grouping the
exam's results by student.batch_id). A student who has not been backfilled
onto a Batch yet cannot be placed on a roster this way — not because their
data is wrong, but because there is nothing yet to say which Batch they
belong to. Re-run this command after a later backfill_student_academics pass
picks up more students; it is idempotent and only ever adds what is newly
resolvable.

Term resolution: an exam whose `term` FK is already set uses it directly.
Otherwise the legacy `academic_year` string is matched against an existing
AcademicYear.name, and the legacy `semester` string is parsed for its semester
number with the same parse_semester_number used by backfill_student_academics
("Semester 4", "4th Semester", "SEM-IV" all -> 4) — odd numbers map to that
year's odd Term, even numbers to its even Term. If either signal doesn't
resolve, the exam is skipped and reported, never guessed.

Usage:
    python manage.py bootstrap_offerings_from_exams --tenant=demo --dry-run
    python manage.py bootstrap_offerings_from_exams --tenant=all
"""

from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context
from tenants.models import Tenant

from campusflow_app.models.academics import AcademicYear, Term
from campusflow_app.models.exam import Exam
from campusflow_app.models.offerings import CourseOffering, StudentCourseRegistration
from campusflow_app.models.result import StudentExamResult
from campusflow_app.utils.academic_parse import parse_semester_number


class Command(BaseCommand):
    help = (
        "Derives CourseOffering/StudentCourseRegistration rows from existing "
        "exams and their results. Requires students to already carry a Batch "
        "FK (see backfill_student_academics)."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default="all")
        parser.add_argument(
            "--dry-run", action="store_true", help="Resolve and report, but create nothing.",
        )

    def handle(self, *args, **options):
        tenants = self._resolve_tenants(options["tenant"])
        for tenant in tenants:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {tenant.schema_name} ==="))
            with schema_context(tenant.schema_name):
                self._bootstrap_tenant(dry_run=options["dry_run"])

    def _resolve_tenants(self, tenant_arg):
        if tenant_arg == "all":
            return list(Tenant.objects.exclude(schema_name="public"))
        tenant = Tenant.objects.filter(schema_name=tenant_arg).first()
        if not tenant:
            raise CommandError(f"No tenant with schema '{tenant_arg}' exists.")
        return [tenant]

    def _bootstrap_tenant(self, *, dry_run):
        exams = Exam.objects.filter(results__isnull=False).distinct().select_related(
            "course", "term", "term__academic_year"
        )
        total = exams.count()
        if total == 0:
            self.stdout.write("  No exams with results found.")
            return

        offerings_created = 0
        registrations_created = 0
        skipped_no_term = 0
        skipped_no_batch = 0
        skipped_ambiguous_batch = 0

        for exam in exams:
            term = self._resolve_term(exam)
            if term is None:
                skipped_no_term += 1
                continue

            results = list(
                StudentExamResult.objects.filter(exam=exam).select_related("student")
            )
            batch_ids = {r.student.batch_id for r in results if r.student.batch_id}
            if not batch_ids:
                skipped_no_batch += 1
                continue
            if len(batch_ids) > 1:
                skipped_ambiguous_batch += 1
                continue
            batch_id = batch_ids.pop()

            if dry_run:
                offerings_created += 1
                registrations_created += sum(
                    1 for r in results if r.student.batch_id == batch_id
                )
                continue

            offering, _ = CourseOffering.objects.get_or_create(
                course=exam.course, term=term, batch_id=batch_id, section=None,
            )
            offerings_created += 1

            for result in results:
                if result.student.batch_id != batch_id:
                    continue
                _, created = StudentCourseRegistration.objects.get_or_create(
                    student=result.student, offering=offering, attempt_number=1,
                    defaults={"term": term, "status": StudentCourseRegistration.STATUS_REGISTERED},
                )
                if created:
                    registrations_created += 1

        verb = "would create/find" if dry_run else "created/found"
        self.stdout.write(f"  {total} exams with results considered.")
        self.stdout.write(f"    {offerings_created} offerings {verb}")
        self.stdout.write(f"    {registrations_created} registrations {verb}")
        self.stdout.write(f"    {skipped_no_term} exams skipped — no resolvable term")
        self.stdout.write(f"    {skipped_no_batch} exams skipped — no backfilled students among results")
        self.stdout.write(f"    {skipped_ambiguous_batch} exams skipped — results span more than one batch")
        if dry_run:
            self.stdout.write(self.style.WARNING("  --dry-run: nothing created."))

    def _resolve_term(self, exam):
        if exam.term_id:
            return exam.term

        if not exam.academic_year:
            return None
        academic_year = AcademicYear.objects.filter(name=exam.academic_year).first()
        if not academic_year:
            return None

        semester_number = parse_semester_number(exam.semester)
        if semester_number is None:
            return None
        sequence = 1 if semester_number % 2 == 1 else 2

        return Term.objects.filter(academic_year=academic_year, sequence=sequence).first()

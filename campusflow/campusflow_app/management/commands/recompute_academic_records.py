"""
Management command: recompute_academic_records

The explicit, audited correction path for CourseGradeAward / TermGradeSheet /
StudentAcademicSummary. `services.grading.publish_term_results` deliberately
never touches a registration that already has an award, so this command is
the only way an already-published award changes — a genuine correction (a
result correction approved after publish, credits changed under an unlocked
regulation, a GradeBand edited) is a deliberate, visible action here, never a
side effect of calling publish again.

--include-published is required to touch anything already published — the
same posture Regulation.is_locked already establishes on Course: results a
transcript was printed from do not move without an explicit, named action.

Usage:
    python manage.py recompute_academic_records --tenant=demo --term=5
    python manage.py recompute_academic_records --tenant=demo --term=5 --student=42 --include-published
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_tenants.utils import schema_context
from tenants.models import Tenant

from campusflow_app.models.academics import Term
from campusflow_app.models.grading import CourseGradeAward
from campusflow_app.models.offerings import StudentCourseRegistration
from campusflow_app.models.profile import StudentProfile
from campusflow_app.services.grading import compute_course_award, compute_cgpa, compute_term_gradesheet


class Command(BaseCommand):
    help = (
        "Explicitly recomputes course grade awards, term gradesheets and CGPA for "
        "one term. Required to touch anything already published."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default="all")
        parser.add_argument("--term", type=int, required=True, help="Term id to recompute.")
        parser.add_argument("--student", type=int, default=None, help="Limit to one StudentProfile id.")
        parser.add_argument(
            "--include-published", action="store_true",
            help="Also recompute registrations that already have a published award.",
        )

    def handle(self, *args, **options):
        tenants = self._resolve_tenants(options["tenant"])
        for tenant in tenants:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {tenant.schema_name} ==="))
            with schema_context(tenant.schema_name):
                self._recompute_tenant(
                    term_id=options["term"], student_id=options["student"],
                    include_published=options["include_published"],
                )

    def _resolve_tenants(self, tenant_arg):
        if tenant_arg == "all":
            return list(Tenant.objects.exclude(schema_name="public"))
        tenant = Tenant.objects.filter(schema_name=tenant_arg).first()
        if not tenant:
            raise CommandError(f"No tenant with schema '{tenant_arg}' exists.")
        return [tenant]

    def _recompute_tenant(self, *, term_id, student_id, include_published):
        term = Term.objects.filter(pk=term_id).first()
        if not term:
            self.stdout.write(self.style.WARNING(f"  No term with id {term_id} in this schema — skipped."))
            return

        registrations = StudentCourseRegistration.objects.filter(term=term).select_related(
            "student", "offering", "offering__course", "grade_award",
        )
        if student_id:
            registrations = registrations.filter(student_id=student_id)

        recomputed = 0
        removed = 0
        skipped_published = 0
        now = timezone.now()

        for registration in registrations:
            # getattr(..., default) does NOT work here: a reverse OneToOneField
            # accessor raises CourseGradeAward.DoesNotExist when absent, which
            # is not an AttributeError and so is not caught by getattr's default.
            try:
                existing = registration.grade_award
            except CourseGradeAward.DoesNotExist:
                existing = None

            if existing is not None and existing.is_published and not include_published:
                skipped_published += 1
                continue

            award = compute_course_award(registration)
            if award is None:
                if existing is not None:
                    existing.delete()
                    removed += 1
                continue

            award.is_published = True
            award.published_at = now
            if existing is not None:
                award.pk = existing.pk
            award.save()
            recomputed += 1

        affected_student_ids = set(registrations.values_list("student_id", flat=True))
        for student in StudentProfile.objects.filter(pk__in=affected_student_ids):
            compute_term_gradesheet(student, term, publish=True)
            compute_cgpa(student)

        self.stdout.write(
            f"  {recomputed} award(s) recomputed, {removed} removed (no longer resolvable), "
            f"{len(affected_student_ids)} student(s)' gradesheet and CGPA refreshed."
        )
        if skipped_published:
            self.stdout.write(
                f"  {skipped_published} already-published award(s) left untouched "
                f"(pass --include-published to recompute them too)."
            )

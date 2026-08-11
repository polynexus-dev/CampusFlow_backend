"""
Management command: recompute_risk_scores

Refreshes the cached StudentRiskScore for every active student (or one
department), the same "compute periodically, store, serve fast" pattern as
recompute_academic_records — meant to be invoked on a schedule by whatever
external scheduler already runs run_billing_cron/clear_old_logs; no in-repo
scheduling is set up for it.

Usage:
    python manage.py recompute_risk_scores --tenant=demo
    python manage.py recompute_risk_scores --tenant=demo --department=3
    python manage.py recompute_risk_scores --tenant=all
"""

from django.core.management.base import BaseCommand, CommandError
from django_tenants.utils import schema_context
from tenants.models import Tenant

from campusflow_app.models.risk_score import StudentRiskScore
from campusflow_app.services.risk_scoring import compute_at_risk_students


class Command(BaseCommand):
    help = "Recomputes the cached dropout/at-risk score for every active student."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", default="all")
        parser.add_argument("--department", type=int, default=None, help="Limit to one Department id.")

    def handle(self, *args, **options):
        tenants = self._resolve_tenants(options["tenant"])
        for tenant in tenants:
            self.stdout.write(self.style.MIGRATE_HEADING(f"\n=== {tenant.schema_name} ==="))
            with schema_context(tenant.schema_name):
                self._recompute_tenant(department_id=options["department"])

    def _resolve_tenants(self, tenant_arg):
        if tenant_arg == "all":
            return list(Tenant.objects.exclude(schema_name="public"))
        tenant = Tenant.objects.filter(schema_name=tenant_arg).first()
        if not tenant:
            raise CommandError(f"No tenant with schema '{tenant_arg}' exists.")
        return [tenant]

    def _recompute_tenant(self, *, department_id):
        scored = compute_at_risk_students(department_id=department_id)

        tier_counts = {"low": 0, "medium": 0, "high": 0}
        for student, score in scored:
            StudentRiskScore.objects.update_or_create(
                student=student,
                defaults={
                    "risk_score": score["risk_score"],
                    "risk_tier": score["risk_tier"],
                    "attendance_rate": score["attendance_rate"],
                    "fee_overdue_amount": score["fee_overdue_amount"],
                    "exam_trend_score": score["exam_trend_score"],
                    "assignment_submission_rate": score["assignment_submission_rate"],
                    "notes": score["notes"],
                },
            )
            tier_counts[score["risk_tier"]] += 1

        self.stdout.write(
            f"  {len(scored)} student(s) scored — "
            f"{tier_counts['high']} high, {tier_counts['medium']} medium, {tier_counts['low']} low risk."
        )

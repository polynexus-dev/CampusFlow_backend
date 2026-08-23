"""
Management command: seed_audit_logs
Seeds realistic audit log entries into tenant schemas for live dashboard audit trails.

Usage:
    python manage.py seed_audit_logs [--schema testcollege]
"""
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django.utils import timezone
from django_tenants.utils import schema_context
from tenants.models import Tenant
from campusflow_app.models.audit import AuditLog


SAMPLE_AUDIT_DATA = [
    {
        "action": "UPDATE",
        "model_name": "FeePayment",
        "object_repr": "Dr. Krishnan (HoD-CSE) approved 3 fee concessions",
        "endpoint": "/api/fees/approve/",
        "hours_ago": 0.3,
        "username": "deck_admin_demo"
    },
    {
        "action": "CREATE",
        "model_name": "IncomeEntry",
        "object_repr": "Accounts reconciled ₹2.1L UPI payments",
        "endpoint": "/api/finance/income/",
        "hours_ago": 1.5,
        "username": "deck_admin_demo"
    },
    {
        "action": "UPDATE",
        "model_name": "GradeBook",
        "object_repr": "System auto-locked Sem 8 grade entry",
        "endpoint": "/api/exams/lock/",
        "hours_ago": 3.0,
        "username": None
    },
    {
        "action": "CREATE",
        "model_name": "Attendance",
        "object_repr": "Prof. Sharma marked CS101 Data Structures attendance (48 students)",
        "endpoint": "/api/attendance/mark/",
        "hours_ago": 4.2,
        "username": "deck_admin_demo"
    },
    {
        "action": "UPDATE",
        "model_name": "HostelAllocation",
        "object_repr": "Hostel Warden allocated Room 304 in Block A to Student #STU-9021",
        "endpoint": "/api/hostel/allocations/",
        "hours_ago": 5.5,
        "username": "deck_admin_demo"
    },
    {
        "action": "UPDATE",
        "model_name": "LeaveRequest",
        "object_repr": "HoD EEE approved 2 casual leave applications for Faculty",
        "endpoint": "/api/leave/requests/action/",
        "hours_ago": 7.0,
        "username": "deck_admin_demo"
    },
    {
        "action": "CREATE",
        "model_name": "RecruitmentDrive",
        "object_repr": "Placement Officer posted Tata Consultancy Services Campus Recruitment Drive",
        "endpoint": "/api/tpo/drives/",
        "hours_ago": 9.2,
        "username": "deck_admin_demo"
    },
    {
        "action": "UPDATE",
        "model_name": "StudentProfile",
        "object_repr": "Academic Registrar verified and activated 14 student registrations",
        "endpoint": "/api/users/approve/",
        "hours_ago": 12.0,
        "username": "deck_admin_demo"
    },
]


class Command(BaseCommand):
    help = "Seed realistic audit trail log entries across tenant schemas."

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema', type=str, default=None,
            help='Specific tenant schema to seed (if omitted, seeds all active tenants)'
        )

    def handle(self, *args, **options):
        target_schema = options['schema']
        now = timezone.now()

        if target_schema:
            schemas = [target_schema]
        else:
            schemas = [s for s in Tenant.objects.values_list('schema_name', flat=True) if s != 'public']

        self.stdout.write(self.style.MIGRATE_HEADING(f"\nSeeding Audit Trail logs across schemas: {schemas}\n"))

        for schema in schemas:
            try:
                with schema_context(schema):
                    # Find a default admin/user for association
                    fallback_user = User.objects.filter(is_superuser=True).first() or User.objects.first()

                    created_count = 0
                    for entry in SAMPLE_AUDIT_DATA:
                        log_time = now - timedelta(hours=entry["hours_ago"])
                        assigned_user = None
                        if entry["username"]:
                            assigned_user = User.objects.filter(username=entry["username"]).first() or fallback_user
                        
                        # Check if a matching log representation already exists
                        exists = AuditLog.objects.filter(object_repr=entry["object_repr"]).exists()
                        if not exists:
                            log_obj = AuditLog.objects.create(
                                user=assigned_user,
                                action=entry["action"],
                                model_name=entry["model_name"],
                                object_repr=entry["object_repr"],
                                ip_address="127.0.0.1",
                                endpoint=entry["endpoint"],
                                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) CampusNexus/1.0"
                            )
                            # Override auto_now_add timestamp to realistic past relative time
                            AuditLog.objects.filter(id=log_obj.id).update(timestamp=log_time)
                            created_count += 1

                    self.stdout.write(self.style.SUCCESS(f"  [+] Schema '{schema}': Seeded {created_count} AuditLog records (Total in schema: {AuditLog.objects.count()})"))
            except Exception as e:
                self.stderr.write(f"  [-] Error seeding schema '{schema}': {e}")

        self.stdout.write(self.style.SUCCESS("\n=== AUDIT LOG SEEDING COMPLETE ===\n"))

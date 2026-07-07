from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from campusflow_app.models.audit import AuditLog
from django_tenants.utils import tenant_context
from tenants.models import Tenant

class Command(BaseCommand):
    help = 'Deletes AuditLog records older than 30 days across all tenant schemas.'

    def handle(self, *args, **options):
        cutoff_date = timezone.now() - timedelta(days=30)
        tenants = Tenant.objects.exclude(schema_name='public')
        
        for tenant in tenants:
            with tenant_context(tenant):
                deleted_count, _ = AuditLog.objects.filter(timestamp__lt=cutoff_date).delete()
                if deleted_count > 0:
                    self.stdout.write(self.style.SUCCESS(
                        f"Schema '{tenant.schema_name}': Successfully deleted {deleted_count} AuditLog records."
                    ))
        
        self.stdout.write(self.style.SUCCESS("AuditLog cleanup completed for all schemas."))

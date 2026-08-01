from django.core.management.base import BaseCommand
from django.core.mail import send_mail
from django_tenants.utils import tenant_context
from tenants.models import Tenant
from campusflow_app.models.compliance import ComplianceCertificate


class Command(BaseCommand):
    help = "Daily cron job: emails the College Admin when a compliance certificate is expiring soon or has expired."

    def handle(self, *args, **options):
        tenants = Tenant.objects.exclude(schema_name='public')

        for tenant in tenants:
            with tenant_context(tenant):
                certs = ComplianceCertificate.objects.filter(
                    valid_until__isnull=False
                ).select_related('certificate_type')
                flagged = [
                    c for c in certs
                    if c.status in (ComplianceCertificate.STATUS_EXPIRING_SOON, ComplianceCertificate.STATUS_EXPIRED)
                ]

                if not flagged:
                    continue

                self.send_expiry_digest(tenant, flagged)
                self.stdout.write(self.style.SUCCESS(
                    f"Schema '{tenant.schema_name}': {len(flagged)} certificate(s) flagged for renewal."
                ))

        self.stdout.write(self.style.SUCCESS("Certificate expiry check completed for all schemas."))

    def send_expiry_digest(self, tenant, flagged):
        try:
            lines = []
            for cert in flagged:
                status_label = "EXPIRED" if cert.status == ComplianceCertificate.STATUS_EXPIRED else "Expiring Soon"
                valid_until = cert.valid_until.strftime('%d %b %Y') if cert.valid_until else "—"
                lines.append(f"  - {cert.certificate_type.name} (valid until {valid_until}) — {status_label}")

            body_text = (
                f"Dear College Administrator,\n\n"
                f"The following compliance certificates/licenses for {tenant.name} need attention:\n\n"
                + "\n".join(lines) +
                f"\n\nPlease renew and re-upload them under Compliance Documents on CampusNexus.\n\n"
                f"CampusNexus — Polynexus Technologies Private Limited"
            )
            send_mail(
                f"ACTION NEEDED: {len(flagged)} compliance certificate(s) expiring - {tenant.name}",
                body_text,
                None,
                [tenant.contact_email or "admin@polynexus.in"],
                fail_silently=True
            )
        except Exception as e:
            self.stdout.write(f"Error sending certificate expiry digest for {tenant.name}: {str(e)}")

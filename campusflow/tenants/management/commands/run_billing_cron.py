import datetime
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django_tenants.utils import schema_context
from tenants.models import Tenant, Invoice

class Command(BaseCommand):
    help = "Daily cron job to handle trial expiry, billing suspensions, and payment reminders."

    def handle(self, *args, **options):
        today = timezone.now().date()
        self.stdout.write(f"[{timezone.now()}] Starting billing cron job...")

        # 1. Check for trials and subscriptions that expired today or earlier
        expired_trials = Tenant.objects.filter(
            subscription_status='trial',
            trial_end_date__lt=today,
            is_active=True
        )
        for tenant in expired_trials:
            tenant.subscription_status = 'suspended'
            tenant.is_active = False
            tenant.save(update_fields=['subscription_status', 'is_active'])
            self.send_suspension_email(tenant, "Trial Expired")
            self.stdout.write(f"Suspended trial tenant: {tenant.name}")

        expired_subs = Tenant.objects.filter(
            subscription_status='active',
            subscription_end_date__lt=today,
            is_active=True
        )
        for tenant in expired_subs:
            tenant.subscription_status = 'suspended'
            tenant.is_active = False
            tenant.save(update_fields=['subscription_status', 'is_active'])
            self.send_suspension_email(tenant, "Subscription Expired")
            self.stdout.write(f"Suspended active tenant: {tenant.name}")

        # 2. Auto-generate invoices for active subscriptions 7 days before they expire
        approaching_expiry = Tenant.objects.filter(
            subscription_status='active',
            subscription_end_date=today + datetime.timedelta(days=7)
        )
        for tenant in approaching_expiry:
            # Check if an invoice for the next period already exists
            next_period_start = tenant.subscription_end_date
            invoice_exists = Invoice.objects.filter(
                tenant=tenant,
                billing_period_start=next_period_start
            ).exists()

            if not invoice_exists:
                # Count active students in tenant schema
                from campusflow_app.models.profile import StudentProfile
                student_count = 0
                with schema_context(tenant.schema_name):
                    try:
                        student_count = StudentProfile.objects.count()
                    except Exception:
                        pass
                
                # Calculate billing amount
                rate = tenant.billing_student_rate or 50.00
                amount = student_count * rate
                if amount < 5000.00:
                    amount = 5000.00  # Minimum base fee

                billing_period_end = next_period_start + datetime.timedelta(days=30 if tenant.billing_cycle == 'monthly' else 365)
                due_date = next_period_start + datetime.timedelta(days=7)

                inv_num = f"INV-{tenant.code or 'CN'}-{next_period_start.strftime('%Y%m%d')}"
                Invoice.objects.create(
                    tenant=tenant,
                    invoice_number=inv_num,
                    amount=amount,
                    billing_period_start=next_period_start,
                    billing_period_end=billing_period_end,
                    due_date=due_date,
                    status='pending_payment'
                )
                self.stdout.write(f"Auto-generated invoice {inv_num} for {tenant.name}")

        # 3. Send warning payment reminders for invoices due in 3 days
        due_invoices = Invoice.objects.filter(
            status='pending_payment',
            due_date=today + datetime.timedelta(days=3)
        )
        for invoice in due_invoices:
            self.send_reminder_email(invoice)
            self.stdout.write(f"Sent reminder for Invoice {invoice.invoice_number} to {invoice.tenant.name}")

        self.stdout.write("Billing cron job completed successfully.")

    def send_suspension_email(self, tenant, reason_prefix):
        try:
            subject = f"ACTION REQUIRED: CampusNexus Account Suspended - {reason_prefix}"
            body_text = (
                f"Dear Principal / College Administrator,\n\n"
                f"Your CampusNexus access has been temporarily suspended because your {reason_prefix.lower()} "
                f"period has expired and payment has not been received.\n\n"
                f"To restore service immediately, please transfer the subscription fee to our Bank Account:\n"
                f"Bank Name: State Bank of India\n"
                f"Account Name: Polynexus Technologies Private Limited\n"
                f"Account Number: 41234567890\n"
                f"IFSC Code: SBIN0001234\n\n"
                f"Once completed, upload the receipt screenshot in your Portal Settings to resume service.\n\n"
                f"Polynexus Technologies Private Limited"
            )
            # Use fallback direct send_mail
            from django.core.mail import send_mail
            send_mail(
                subject,
                body_text,
                None,
                [tenant.contact_email or "admin@polynexus.in"],
                fail_silently=True
            )
        except Exception as e:
            self.stdout.write(f"Error sending suspension email: {str(e)}")

    def send_reminder_email(self, invoice):
        try:
            context = {
                'invoice_number': invoice.invoice_number,
                'amount': invoice.amount,
                'due_date': invoice.due_date.strftime('%B %d, %Y')
            }
            html_content = render_to_string('emails/billing_reminder.html', context)
            text_content = f"Payment Reminder: Invoice {invoice.invoice_number} of Rs. {invoice.amount} is due on {invoice.due_date}."

            msg = EmailMultiAlternatives(
                subject=f"Urgent: Payment Reminder - Invoice #{invoice.invoice_number} - CampusNexus",
                body=text_content,
                from_email=None,
                to=[invoice.tenant.contact_email or "admin@polynexus.in"]
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send()
        except Exception as e:
            self.stdout.write(f"Error sending reminder email: {str(e)}")

import datetime
from django.contrib.auth.models import Group, User
from django.test import override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from rest_framework import status
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework_simplejwt.tokens import RefreshToken
from tenants.models import Tenant, Invoice

class DictCache:
    def __init__(self):
        self.data = {}
    def get(self, key, default=None):
        return self.data.get(key, default)
    def set(self, key, value, timeout=None):
        self.data[key] = value
    def delete(self, key):
        self.data.pop(key, None)

TEST_BANK_DETAILS = {
    "bank_name": "Test Bank",
    "account_name": "Polynexus Technologies Private Limited",
    "account_number": "000111222333",
    "ifsc_code": "TEST0000001",
    "branch": "Test Branch",
}


class BillingSystemTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        from unittest.mock import patch
        self.cache_patcher = patch('django.core.cache.cache')
        self.mock_cache = self.cache_patcher.start()
        self.dict_cache = DictCache()
        self.mock_cache.get.side_effect = self.dict_cache.get
        self.mock_cache.set.side_effect = self.dict_cache.set
        self.mock_cache.delete.side_effect = self.dict_cache.delete

        self.tenant.permitted_email_domain = 'college.edu'
        self.tenant.subscription_status = 'trial'
        self.tenant.trial_start_date = datetime.date(2026, 7, 1)
        self.tenant.trial_end_date = datetime.date(2026, 7, 15)
        self.tenant.save()

        # Create central superuser (SaaS Admin) in public schema database
        with schema_context('public'):
            self.superuser = User.objects.create_superuser(
                username='saas_boss',
                email='boss@polynexus.in',
                password='BossPassword123'
            )
            self.superuser_token = RefreshToken.for_user(self.superuser)
            self.superuser_token['tenant_schema'] = 'public'
            self.superuser_access = str(self.superuser_token.access_token)

        # Create a test invoice for the tenant
        self.invoice = Invoice.objects.create(
            tenant=self.tenant,
            invoice_number='INV-TEST-0001',
            amount=5000.00,
            billing_period_start=datetime.date(2026, 7, 1),
            billing_period_end=datetime.date(2026, 7, 30),
            due_date=datetime.date(2026, 7, 10),
            status='pending_payment'
        )

    def tearDown(self):
        self.cache_patcher.stop()
        super().tearDown()

    def _tenant_token(self, username, group_name):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(username=username, email=f'{username}@college.edu', password='Password123')
            group, _ = Group.objects.get_or_create(name=group_name)
            user.groups.add(group)
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
            return str(token.access_token)

    @override_settings(POLYNEXUS_BANK_DETAILS=TEST_BANK_DETAILS)
    def test_invoice_list_and_bank_details(self):
        access_token = self._tenant_token('col_admin', 'Management')
        
        # Test GET client invoice list inside tenant schema
        url = reverse('invoice_list')
        response = self.client.get(
            url,
            HTTP_AUTHORIZATION=f'Bearer {access_token}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('bank_details', response.data)
        self.assertEqual(response.data['bank_details']['bank_name'], 'Test Bank')
        self.assertEqual(len(response.data['invoices']), 1)

    @override_settings(POLYNEXUS_BANK_DETAILS=None)
    def test_invoice_list_hides_unconfigured_bank_details(self):
        access_token = self._tenant_token('col_admin3', 'Administrator')
        response = self.client.get(reverse('invoice_list'), HTTP_AUTHORIZATION=f'Bearer {access_token}')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data['bank_details'])

    def test_student_cannot_view_or_upload_subscription_invoices(self):
        access_token = self._tenant_token('some_student', 'student')
        response = self.client.get(reverse('invoice_list'), HTTP_AUTHORIZATION=f'Bearer {access_token}')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

        fake_receipt = SimpleUploadedFile(name="receipt.pdf", content=b"x", content_type="application/pdf")
        response = self.client.post(
            reverse('invoice_upload_receipt', kwargs={'pk': self.invoice.pk}),
            {'bank_receipt': fake_receipt, 'utr_number': 'UTR999'},
            HTTP_AUTHORIZATION=f'Bearer {access_token}',
            format='multipart',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'pending_payment')

    def test_upload_invoice_receipt(self):
        access_token = self._tenant_token('col_admin2', 'Management')

        # Create fake screenshot file
        fake_receipt = SimpleUploadedFile(
            name="receipt.pdf",
            content=b"file_content",
            content_type="application/pdf"
        )

        url = reverse('invoice_upload_receipt', kwargs={'pk': self.invoice.pk})
        response = self.client.post(
            url,
            {'bank_receipt': fake_receipt, 'utr_number': 'UTR123456789'},
            HTTP_AUTHORIZATION=f'Bearer {access_token}',
            format='multipart'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Refresh invoice from DB and assert status
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'under_review')
        self.assertEqual(self.invoice.utr_number, 'UTR123456789')

    def test_saas_admin_invoice_list(self):
        url = reverse('saas_invoice_list')
        response = self.client.get(
            url,
            HTTP_AUTHORIZATION=f'Bearer {self.superuser_access}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)

    def test_saas_admin_approve_invoice(self):
        # Set invoice to under review first
        self.invoice.status = 'under_review'
        self.invoice.save()

        url = reverse('saas_invoice_approve', kwargs={'pk': self.invoice.pk})
        response = self.client.post(
            url,
            HTTP_AUTHORIZATION=f'Bearer {self.superuser_access}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert status becomes paid and subscription extended
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'paid')

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'active')
        self.assertIsNotNone(self.tenant.subscription_end_date)

    def test_saas_admin_reject_invoice(self):
        self.invoice.status = 'under_review'
        self.invoice.save()

        url = reverse('saas_invoice_reject', kwargs={'pk': self.invoice.pk})
        response = self.client.post(
            url,
            {'reason': 'Receipt blurred'},
            HTTP_AUTHORIZATION=f'Bearer {self.superuser_access}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Assert returns to pending
        self.invoice.refresh_from_db()
        self.assertEqual(self.invoice.status, 'pending_payment')
        self.assertIsNone(self.invoice.bank_receipt.name or None)

    def test_billing_cron_suspension(self):
        # Set trial date to yesterday to force expiration
        self.tenant.trial_end_date = datetime.date(2026, 7, 5) # Past date
        self.tenant.save()

        # Run command
        call_command('run_billing_cron')

        self.tenant.refresh_from_db()
        self.assertEqual(self.tenant.subscription_status, 'suspended')
        self.assertFalse(self.tenant.is_active)

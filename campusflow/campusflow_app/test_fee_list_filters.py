"""
Paging and filters on the fee invoice / receipt lists (views/fees.py:
OptionalPagePagination, _search_terms, _date_range).
"""

import datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import FeePayment, StudentFeeInvoice
from .models.profile import AdministratorProfile, StudentProfile


class FeeListFilterTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        self.tenant.subscribed_modules = ["fees"]
        self.tenant.save(update_fields=["subscribed_modules"])
        with schema_context(self.tenant.schema_name):
            self.admin = self._user("fee_admin", "Administrator", "Asha", "Admin")
            AdministratorProfile.objects.create(user=self.admin, employee_id="ADM-9", status="active")
            self.megha = self._student("stu_megha", "Megha", "Gupta", "CSE001")
            self.ravi = self._student("stu_ravi", "Ravi", "Kumar", "CSE002")

            aug, sep = datetime.date(2026, 8, 15), datetime.date(2026, 9, 15)
            self.megha_aug = self._invoice(self.megha, "INV-1001", aug, StudentFeeInvoice.STATUS_UNPAID)
            self._invoice(self.megha, "INV-1002", sep, StudentFeeInvoice.STATUS_PAID)
            self._invoice(self.ravi, "INV-1003", aug, StudentFeeInvoice.STATUS_PARTIALLY_PAID)
            FeePayment.objects.create(invoice=self.megha_aug, amount_paid=Decimal("100"), payment_method="upi")
            ravi_invoice = StudentFeeInvoice.objects.get(invoice_number="INV-1003")
            FeePayment.objects.create(invoice=ravi_invoice, amount_paid=Decimal("200"), payment_method="cash")

    def _user(self, username, role, first, last):
        user = User.objects.create_user(username=username, password="pw12345!", first_name=first, last_name=last)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def _student(self, username, first, last, roll):
        user = self._user(username, "student", first, last)
        StudentProfile.objects.create(user=user, student_id=roll, status="active")
        return user

    def _invoice(self, student, number, due, state):
        return StudentFeeInvoice.objects.create(
            student=student, invoice_number=number, due_date=due,
            total_amount=Decimal("1000"), status=state,
        )

    def _get(self, name, user=None, **params):
        with schema_context(self.tenant.schema_name):
            token = RefreshToken.for_user(user or self.admin)
        token["tenant_schema"] = self.tenant.schema_name
        response = self.client.get(reverse(name), params, HTTP_AUTHORIZATION=f"Bearer {token.access_token}")
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.data)
        return response.data

    def _invoice_numbers(self, **params):
        data = self._get("student-fee-invoice-list", page=1, **params)
        return {row["invoice_number"] for row in data["results"]}

    def test_without_page_the_list_is_unchanged(self):
        data = self._get("student-fee-invoice-list")
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 3)

    def test_page_returns_count_and_one_page(self):
        data = self._get("student-fee-invoice-list", page=1, page_size=2)
        self.assertEqual(data["count"], 3)
        self.assertEqual(len(data["results"]), 2)
        self.assertIsNotNone(data["next"])

    def test_search_by_full_name_roll_number_or_invoice_number(self):
        self.assertEqual(self._invoice_numbers(q="megha gupta"), {"INV-1001", "INV-1002"})
        self.assertEqual(self._invoice_numbers(q="CSE002"), {"INV-1003"})
        self.assertEqual(self._invoice_numbers(q="1002"), {"INV-1002"})
        self.assertEqual(self._invoice_numbers(q="gupta 1003"), set())

    def test_outstanding_means_unpaid_or_partly_paid(self):
        self.assertEqual(self._invoice_numbers(status="outstanding"), {"INV-1001", "INV-1003"})
        self.assertEqual(self._invoice_numbers(status="paid"), {"INV-1002"})

    def test_due_date_range(self):
        self.assertEqual(self._invoice_numbers(date_from="2026-09-01"), {"INV-1002"})
        self.assertEqual(self._invoice_numbers(date_to="2026-08-31"), {"INV-1001", "INV-1003"})
        self.assertEqual(len(self._invoice_numbers(date_from="not-a-date")), 3)

    def test_student_filters_stay_inside_their_own_invoices(self):
        data = self._get("student-fee-invoice-list", user=self.megha, page=1, q="kumar")
        self.assertEqual(data["count"], 0)

    def test_payments_filter_by_method_and_search(self):
        data = self._get("fee-payment-list", page=1, method="cash")
        self.assertEqual([row["invoice_number"] for row in data["results"]], ["INV-1003"])
        data = self._get("fee-payment-list", page=1, q="megha")
        self.assertEqual([row["invoice_number"] for row in data["results"]], ["INV-1001"])

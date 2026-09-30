import os
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'campusflow.settings')
django.setup()

from django.contrib.auth.models import User
from django_tenants.utils import schema_context
from campusflow_app.models import Notification, SalaryStructure, Payslip

with schema_context('demo'):
    # Targets: all staff / faculty / admin / demo users
    target_usernames = [
        'demo_student', 'demo_student2', 'demo_student3',
        'demo_faculty', 'demo_faculty2', 'demo_hod', 'demo_admin', 'demo_mgmt', 'demo_support'
    ]

    target_users = User.objects.filter(username__in=target_usernames)

    print(f"Found {target_users.count()} target demo users.")

    for u in target_users:
        # 1. Seed Notifications
        notifications_data = [
            {
                "title": "Bus Boarded Successfully",
                "body": "You boarded Bus Route B-102 at Campus Main Gate at 08:35 AM.",
                "category": "bus_boarding",
                "data": {"trip_id": 101, "route": "Route B-102", "bus_number": "MH-12-CF-8899"},
                "is_read": False,
            },
            {
                "title": "Mid-Term Exam Results Published",
                "body": "Your Mid-Term results for Computer Networks (CS401) have been published. Grade: A (88/100).",
                "category": "marks_published",
                "data": {"exam_id": 4, "course_code": "CS401", "score": 88},
                "is_read": False,
            },
            {
                "title": "New Assignment: Binary Search Trees",
                "body": "Dr. Jane Doe posted Assignment #3 for CS101. Due Date: Oct 10, 2026.",
                "category": "homework",
                "data": {"assignment_id": 12, "course_code": "CS101"},
                "is_read": True,
            },
            {
                "title": "Fee Payment Reminder",
                "body": "Semester 4 Tuition & Lab fee invoice #INV-2026-092 (Rs 45,000) is due on Oct 15, 2026.",
                "category": "fees",
                "data": {"invoice_id": "INV-2026-092", "amount": 45000},
                "is_read": False,
            },
            {
                "title": "September 2026 Salary Credited",
                "body": "Your net salary of Rs 83,000 for September 2026 has been credited to your bank account.",
                "category": "payroll",
                "data": {"month": 9, "year": 2026, "net_payable": 83000},
                "is_read": False,
            },
        ]

        for n_data in notifications_data:
            Notification.objects.create(
                recipient=u,
                title=n_data["title"],
                body=n_data["body"],
                category=n_data["category"],
                data=n_data["data"],
                is_read=n_data["is_read"],
            )

        # 2. Seed Salary Structure & Payslips
        salary_struct, _ = SalaryStructure.objects.get_or_create(
            user=u,
            defaults={
                "basic_pay": 55000.00,
                "hra": 18000.00,
                "da": 12000.00,
                "ta": 5000.00,
                "other_allowances": 3000.00,
                "pf_deduction": 4500.00,
                "esi_deduction": 1200.00,
                "tds_deduction": 3500.00,
                "other_deductions": 800.00,
            }
        )

        months = [
            (7, 2026, 22, 22, 0, 0, "paid"),
            (8, 2026, 21, 20, 1, 0, "paid"),
            (9, 2026, 22, 21, 0, 1, "paid"),
        ]

        for month, year, w_days, p_days, l_days, a_days, status in months:
            gross = salary_struct.gross_salary
            tot_ded = salary_struct.total_deductions
            abs_ded = (gross / w_days) * a_days
            net = gross - tot_ded - abs_ded

            Payslip.objects.get_or_create(
                user=u,
                month=month,
                year=year,
                defaults={
                    "total_working_days": w_days,
                    "present_days": p_days,
                    "leave_days": l_days,
                    "absent_days": a_days,
                    "gross_salary": gross,
                    "total_deductions": tot_ded,
                    "pf_deduction": salary_struct.pf_deduction,
                    "esi_deduction": salary_struct.esi_deduction,
                    "tds_deduction": salary_struct.tds_deduction,
                    "absence_deduction": abs_ded,
                    "net_payable": net,
                    "status": status,
                }
            )

    print("[SUCCESS] Seeded payslips & notifications for all demo accounts!")

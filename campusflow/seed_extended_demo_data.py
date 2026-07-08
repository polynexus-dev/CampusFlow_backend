"""
CampusFlow Extended Demo Data Seeder
====================================
Populates rich demo data for ALL modules that are currently empty:
  - More Announcements (5 total)
  - More Assignments (3 total with submissions)
  - Bus Routes, Subscriptions & Attendance
  - Fee Categories, Structures, Invoices & Payments/Receipts
  - Library Books, Copies & Issue Records

Run with:
  python manage.py shell < seed_extended_demo_data.py
"""

import os, sys, django, random, uuid
import datetime
from datetime import date, time, timedelta
from decimal import Decimal

if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
    django.setup()

from django_tenants.utils import schema_context
from django.utils import timezone

SCHEMA = 'demo'

print(f"Switching to schema '{SCHEMA}'...")
with schema_context(SCHEMA):
    from django.contrib.auth.models import User
    from campusflow_app.models import (
        Department, Course, Classroom, Schedule, Lecture,
        StudentProfile, TeachingStaffProfile,
        Announcement, Assignment, AssignmentSubmission,
        BusRoute, BusSubscription, BusAttendance, BusLocation,
        FeeCategory, FeeStructure, FeeStructureItem,
        StudentFeeInvoice, StudentFeeInvoiceItem, FeePayment,
        Book, BookCopy, BookIssue,
    )

    today = date.today()
    now = timezone.now()

    # Fetch existing users
    u_admin    = User.objects.get(username='demo_admin')
    u_hod      = User.objects.get(username='demo_hod')
    u_faculty  = User.objects.get(username='demo_faculty')
    u_faculty2 = User.objects.get(username='demo_faculty2')
    u_support  = User.objects.get(username='demo_support')
    u_student  = User.objects.get(username='demo_student')
    u_student2 = User.objects.get(username='demo_student2')
    u_student3 = User.objects.get(username='demo_student3')

    sp1 = StudentProfile.objects.get(user=u_student)
    sp2 = StudentProfile.objects.get(user=u_student2)
    sp3 = StudentProfile.objects.get(user=u_student3)

    dept_cs = Department.objects.get(code='CS')
    dept_it = Department.objects.get(code='IT')

    course_cs101 = Course.objects.get(course_code='CS101')
    course_cs201 = Course.objects.get(course_code='CS201')
    course_it101 = Course.objects.get(course_code='IT101')
    course_it201 = Course.objects.get(course_code='IT201')

    # ════════════════════════════════════════════════════════════════════
    # 1. ANNOUNCEMENTS (add 3 more)
    # ════════════════════════════════════════════════════════════════════
    announcements_data = [
        {
            'title': 'Library Extended Hours During Exams',
            'content': 'The central library will remain open until 10:00 PM during the midterm examination period (starting next Monday). Students are encouraged to use the reading halls and digital resources.',
            'author': u_support,
            'priority': 'medium',
            'is_pinned': False,
        },
        {
            'title': 'Annual Sports Day Registration Open',
            'content': 'Registrations for the Annual Sports Day 2025 are now open. Participate in Cricket, Football, Basketball, Badminton, Table Tennis, and Track & Field events. Register via the Student Portal by end of this week.',
            'author': u_admin,
            'priority': 'low',
            'is_pinned': False,
        },
        {
            'title': 'Bus Route Change - Route 3 Temporarily Diverted',
            'content': 'Due to road construction on MG Road, Route 3 (Nagpur Station - College) will be diverted via Sitabuldi from tomorrow. The estimated delay is 10-15 minutes. Please plan accordingly.',
            'author': u_admin,
            'priority': 'high',
            'is_pinned': True,
        },
    ]
    for ad in announcements_data:
        Announcement.objects.get_or_create(title=ad['title'], defaults=ad)
    print("✅ Created additional Announcements (5 total).")

    # ════════════════════════════════════════════════════════════════════
    # 2. MORE ASSIGNMENTS & SUBMISSIONS
    # ════════════════════════════════════════════════════════════════════
    a2, _ = Assignment.objects.get_or_create(
        title="Assignment 2: Binary Tree Traversals",
        course=course_cs101,
        defaults={
            'description': "Implement Inorder, Preorder, and Postorder traversal algorithms. Write unit tests for edge cases (empty tree, single node). Submit a zip file.",
            'department': dept_cs,
            'due_date': now + timedelta(days=7),
            'created_by': u_faculty
        }
    )
    AssignmentSubmission.objects.get_or_create(
        assignment=a2, student=u_student,
        defaults={'text_submission': "All traversals implemented with test cases.", 'status': 'submitted'}
    )

    a3, _ = Assignment.objects.get_or_create(
        title="Assignment 3: SQL Query Optimization",
        course=course_cs201,
        defaults={
            'description': "Given a slow-performing database schema, write optimized SQL queries using indexes, joins, and subqueries. Explain your optimization strategy in a 500-word report.",
            'department': dept_cs,
            'due_date': now + timedelta(days=14),
            'created_by': u_faculty
        }
    )

    a4, _ = Assignment.objects.get_or_create(
        title="Web Technologies Lab: Responsive Portfolio",
        course=course_it101,
        defaults={
            'description': "Build a responsive personal portfolio website using HTML5, CSS3 (Flexbox/Grid), and vanilla JS. Host it on GitHub Pages and submit the live URL.",
            'department': dept_it,
            'due_date': now + timedelta(days=10),
            'created_by': u_faculty2
        }
    )
    AssignmentSubmission.objects.get_or_create(
        assignment=a4, student=u_student3,
        defaults={'text_submission': "Portfolio deployed at https://charlie-demo.github.io/portfolio", 'grade': 'A+', 'feedback': 'Clean design, great responsiveness.', 'status': 'graded'}
    )
    print("✅ Created additional Assignments & Submissions.")

    # ════════════════════════════════════════════════════════════════════
    # 3. BUS ROUTES, SUBSCRIPTIONS & ATTENDANCE
    # ════════════════════════════════════════════════════════════════════
    route1, _ = BusRoute.objects.get_or_create(
        name="Route 1 - Wardha Road",
        defaults={
            'driver': u_support,
            'stops': [
                {"name": "Wardha Road Terminal", "lat": 21.1458, "lng": 79.0882},
                {"name": "Ambazari Lake", "lat": 21.1350, "lng": 79.0500},
                {"name": "Law College Square", "lat": 21.1400, "lng": 79.0650},
                {"name": "Demo College Gate", "lat": 21.1500, "lng": 79.0900},
            ],
            'is_active': True,
        }
    )
    route2, _ = BusRoute.objects.get_or_create(
        name="Route 2 - Sadar",
        defaults={
            'driver': u_support,
            'stops': [
                {"name": "Sadar Bus Stand", "lat": 21.1550, "lng": 79.0800},
                {"name": "Civil Lines", "lat": 21.1520, "lng": 79.0750},
                {"name": "Ramdaspeth", "lat": 21.1480, "lng": 79.0830},
                {"name": "Demo College Gate", "lat": 21.1500, "lng": 79.0900},
            ],
            'is_active': True,
        }
    )
    route3, _ = BusRoute.objects.get_or_create(
        name="Route 3 - Nagpur Station",
        defaults={
            'driver': u_support,
            'stops': [
                {"name": "Nagpur Railway Station", "lat": 21.1466, "lng": 79.0849},
                {"name": "Sitabuldi", "lat": 21.1430, "lng": 79.0790},
                {"name": "Dharampeth", "lat": 21.1410, "lng": 79.0700},
                {"name": "Demo College Gate", "lat": 21.1500, "lng": 79.0900},
            ],
            'is_active': True,
        }
    )

    # Subscriptions
    BusSubscription.objects.get_or_create(
        user=u_student, route=route1,
        defaults={'status': 'active', 'boarding_stop': 'Wardha Road Terminal', 'valid_from': today - timedelta(days=90), 'valid_until': today + timedelta(days=90), 'notes': 'Semester 4 bus pass'}
    )
    BusSubscription.objects.get_or_create(
        user=u_student2, route=route2,
        defaults={'status': 'active', 'boarding_stop': 'Civil Lines', 'valid_from': today - timedelta(days=90), 'valid_until': today + timedelta(days=90), 'notes': 'Semester 4 bus pass'}
    )
    BusSubscription.objects.get_or_create(
        user=u_student3, route=route3,
        defaults={'status': 'active', 'boarding_stop': 'Nagpur Railway Station', 'valid_from': today - timedelta(days=90), 'valid_until': today + timedelta(days=90), 'notes': 'Semester 4 bus pass'}
    )

    # Bus attendance for last 5 days
    for day_offset in range(5):
        scan_date = now - timedelta(days=day_offset, hours=random.randint(0, 2))
        for usr, rt in [(u_student, route1), (u_student2, route2), (u_student3, route3)]:
            if not BusAttendance.objects.filter(user=usr, route=rt, scanned_at__date=scan_date.date()).exists():
                BusAttendance.objects.create(
                    user=usr, route=rt,
                    device_id=f"DEVICE_{usr.username.upper()}"
                )

    # Live bus location (simulate)
    BusLocation.objects.update_or_create(
        user=u_support,
        defaults={'lat': 21.1480, 'lng': 79.0830, 'route': route1}
    )
    print("✅ Created Bus Routes, Subscriptions, Attendance & Live Location.")

    # ════════════════════════════════════════════════════════════════════
    # 4. FEES: Categories, Structures, Invoices, Payments & Receipts
    # ════════════════════════════════════════════════════════════════════
    cat_tuition, _  = FeeCategory.objects.get_or_create(name='Tuition Fee',  defaults={'description': 'Semester tuition charges'})
    cat_exam, _     = FeeCategory.objects.get_or_create(name='Exam Fee',     defaults={'description': 'Examination and evaluation charges'})
    cat_library, _  = FeeCategory.objects.get_or_create(name='Library Fee',  defaults={'description': 'Library access and resources'})
    cat_bus, _      = FeeCategory.objects.get_or_create(name='Bus Fee',      defaults={'description': 'Campus bus transport charges'})
    cat_lab, _      = FeeCategory.objects.get_or_create(name='Lab Fee',      defaults={'description': 'Laboratory equipment and consumables'})
    cat_sports, _   = FeeCategory.objects.get_or_create(name='Sports Fee',   defaults={'description': 'Sports facilities and equipment'})

    # Fee Structure for CS Semester 4
    fs_cs4, _ = FeeStructure.objects.get_or_create(
        name='CS B.Tech - Semester 4 (2024-2025)',
        defaults={
            'department': dept_cs,
            'batch_academic_year': '2024-2025',
            'program_enrolled_in': 'B.Tech CS',
            'current_semester_year': 'Semester 4',
        }
    )
    fee_items_cs = [
        (cat_tuition, Decimal('45000.00')),
        (cat_exam,    Decimal('3500.00')),
        (cat_library, Decimal('2000.00')),
        (cat_bus,     Decimal('8000.00')),
        (cat_lab,     Decimal('5000.00')),
        (cat_sports,  Decimal('1500.00')),
    ]
    for cat, amount in fee_items_cs:
        FeeStructureItem.objects.get_or_create(
            fee_structure=fs_cs4, category=cat,
            defaults={'amount': amount}
        )

    total_cs = sum(a for _, a in fee_items_cs)

    # Generate invoices for students
    for stu_user, stu_label in [(u_student, 'Alice'), (u_student2, 'Bob')]:
        inv, inv_created = StudentFeeInvoice.objects.get_or_create(
            student=stu_user,
            fee_structure=fs_cs4,
            defaults={
                'due_date': today + timedelta(days=30),
                'total_amount': total_cs,
                'discount_amount': Decimal('0.00'),
                'status': 'unpaid',
            }
        )
        if inv_created:
            for cat, amount in fee_items_cs:
                StudentFeeInvoiceItem.objects.create(invoice=inv, category=cat, amount=amount)

    # Alice: partially paid (tuition only)
    inv_alice = StudentFeeInvoice.objects.filter(student=u_student, fee_structure=fs_cs4).first()
    if inv_alice and inv_alice.status == 'unpaid':
        FeePayment.objects.create(
            invoice=inv_alice,
            amount_paid=Decimal('45000.00'),
            payment_method='upi',
            transaction_reference='UPI-DEMO-TXN-001',
            remarks='Tuition fee paid via UPI',
            collected_by=u_admin,
        )

    # Bob: fully paid
    inv_bob = StudentFeeInvoice.objects.filter(student=u_student2, fee_structure=fs_cs4).first()
    if inv_bob and inv_bob.status == 'unpaid':
        FeePayment.objects.create(
            invoice=inv_bob,
            amount_paid=total_cs,
            payment_method='net_banking',
            transaction_reference='NEFT-DEMO-TXN-002',
            remarks='Full semester fees paid via Net Banking',
            collected_by=u_admin,
        )

    # IT student invoice
    fs_it4, _ = FeeStructure.objects.get_or_create(
        name='IT B.Tech - Semester 4 (2024-2025)',
        defaults={
            'department': dept_it,
            'batch_academic_year': '2024-2025',
            'program_enrolled_in': 'B.Tech IT',
            'current_semester_year': 'Semester 4',
        }
    )
    fee_items_it = [
        (cat_tuition, Decimal('42000.00')),
        (cat_exam,    Decimal('3000.00')),
        (cat_library, Decimal('2000.00')),
        (cat_bus,     Decimal('8000.00')),
        (cat_lab,     Decimal('4000.00')),
        (cat_sports,  Decimal('1500.00')),
    ]
    total_it = sum(a for _, a in fee_items_it)
    for cat, amount in fee_items_it:
        FeeStructureItem.objects.get_or_create(fee_structure=fs_it4, category=cat, defaults={'amount': amount})

    inv_charlie, inv_created = StudentFeeInvoice.objects.get_or_create(
        student=u_student3, fee_structure=fs_it4,
        defaults={
            'due_date': today + timedelta(days=30),
            'total_amount': total_it,
            'discount_amount': Decimal('2000.00'),
            'status': 'unpaid',
        }
    )
    if inv_created:
        for cat, amount in fee_items_it:
            StudentFeeInvoiceItem.objects.create(invoice=inv_charlie, category=cat, amount=amount)

    print("✅ Created Fee Categories, Structures, Invoices & Payment Receipts.")

    # ════════════════════════════════════════════════════════════════════
    # 5. LIBRARY: Books, Copies & Issue Records
    # ════════════════════════════════════════════════════════════════════
    books_data = [
        {'title': 'Introduction to Algorithms',           'author': 'Thomas H. Cormen',       'isbn': '978-0262033848', 'publisher': 'MIT Press',     'total_copies': 5, 'available_copies': 3},
        {'title': 'Database System Concepts',              'author': 'Abraham Silberschatz',    'isbn': '978-0078022159', 'publisher': 'McGraw-Hill',   'total_copies': 4, 'available_copies': 2},
        {'title': 'Operating System Concepts',             'author': 'Abraham Silberschatz',    'isbn': '978-1119800361', 'publisher': 'Wiley',         'total_copies': 3, 'available_copies': 2},
        {'title': 'Computer Networks',                     'author': 'Andrew S. Tanenbaum',     'isbn': '978-0132126953', 'publisher': 'Pearson',       'total_copies': 4, 'available_copies': 3},
        {'title': 'Artificial Intelligence: A Modern Approach', 'author': 'Stuart Russell',     'isbn': '978-0134610993', 'publisher': 'Pearson',       'total_copies': 3, 'available_copies': 2},
        {'title': 'Clean Code',                            'author': 'Robert C. Martin',        'isbn': '978-0132350884', 'publisher': 'Prentice Hall', 'total_copies': 6, 'available_copies': 4},
        {'title': 'Design Patterns',                       'author': 'Erich Gamma',             'isbn': '978-0201633610', 'publisher': 'Addison-Wesley','total_copies': 3, 'available_copies': 2},
        {'title': 'The Pragmatic Programmer',              'author': 'David Thomas',            'isbn': '978-0135957059', 'publisher': 'Addison-Wesley','total_copies': 4, 'available_copies': 3},
    ]

    book_objs = {}
    for bd in books_data:
        book, _ = Book.objects.get_or_create(isbn=bd['isbn'], defaults=bd)
        book_objs[bd['isbn']] = book

    # Create individual copies with barcodes
    for isbn, book in book_objs.items():
        for i in range(1, book.total_copies + 1):
            barcode = f"{isbn[-4:]}-{i:03d}"
            BookCopy.objects.get_or_create(
                book=book, barcode=barcode,
                defaults={'status': 'Available'}
            )

    # Issue some books to students
    # Alice: 2 books issued
    copy1 = BookCopy.objects.filter(book=book_objs['978-0262033848'], status='Available').first()
    if copy1:
        issue, created = BookIssue.objects.get_or_create(
            book_copy=copy1, student=sp1, status='Issued',
            defaults={'due_date': today + timedelta(days=14), 'fine_amount': Decimal('0.00')}
        )
        if created:
            copy1.status = 'Issued'
            copy1.save()

    copy2 = BookCopy.objects.filter(book=book_objs['978-0132350884'], status='Available').first()
    if copy2:
        issue, created = BookIssue.objects.get_or_create(
            book_copy=copy2, student=sp1, status='Issued',
            defaults={'due_date': today + timedelta(days=14), 'fine_amount': Decimal('0.00')}
        )
        if created:
            copy2.status = 'Issued'
            copy2.save()

    # Bob: 1 book returned with fine
    copy3 = BookCopy.objects.filter(book=book_objs['978-0078022159'], status='Available').first()
    if copy3:
        issue, created = BookIssue.objects.get_or_create(
            book_copy=copy3, student=sp2, status='Returned',
            defaults={
                'due_date': today - timedelta(days=5),
                'returned_date': today,
                'fine_amount': Decimal('50.00'),
            }
        )

    # Charlie: 1 book currently issued
    copy4 = BookCopy.objects.filter(book=book_objs['978-0134610993'], status='Available').first()
    if copy4:
        issue, created = BookIssue.objects.get_or_create(
            book_copy=copy4, student=sp3, status='Issued',
            defaults={'due_date': today + timedelta(days=21), 'fine_amount': Decimal('0.00')}
        )
        if created:
            copy4.status = 'Issued'
            copy4.save()

    print("✅ Created Library Books, Copies & Issue Records.")

    # ════════════════════════════════════════════════════════════════════
    # DONE
    # ════════════════════════════════════════════════════════════════════
    print("\n" + "="*60)
    print("EXTENDED DEMO DATA SEEDING COMPLETE!")
    print("="*60)
    print(f"  Announcements : 5 total")
    print(f"  Assignments   : 4 total with submissions")
    print(f"  Bus Routes    : 3 routes, 3 subscriptions, attendance logs")
    print(f"  Fee Invoices  : 3 invoices (Alice=partial, Bob=paid, Charlie=unpaid)")
    print(f"  Library       : 8 books, copies, 4 issue records")
    print("="*60)

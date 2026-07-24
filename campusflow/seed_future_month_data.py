"""
CampusFlow Future Month Data Seeder
====================================
Populates future lectures (next 30 days), weekly schedules, upcoming assignments,
announcements, and library books/copies/issues.

Usage:
  python seed_future_month_data.py
"""

import os
import sys
import random
import string
import datetime
from datetime import date, time, timedelta

if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
    import django
    django.setup()

from django_tenants.utils import schema_context
from django.utils import timezone
from tenants.models import Tenant

# Target schemas: all non-public tenants or 'demo'
tenants = Tenant.objects.exclude(schema_name='public')
if not tenants.exists():
    schemas = ['public']
else:
    schemas = [t.schema_name for t in tenants]

print(f"Targeting schemas for seeding: {schemas}")

for SCHEMA in schemas:
    print(f"\n==========================================")
    print(f"Seeding Future Month Data for Schema: '{SCHEMA}'")
    print(f"==========================================")

    with schema_context(SCHEMA):
        from django.contrib.auth.models import User, Group
        from campusflow_app.models import (
            Department, Course, Classroom, Schedule, Lecture,
            StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile,
            Announcement, Assignment, AssignmentSubmission,
            Book, BookCopy, BookIssue
        )

        today = date.today()
        now = timezone.now()

        # ── 1. Ensure basic infrastructure & accounts ──────────────────────
        dept_cs, _ = Department.objects.get_or_create(code='CS', defaults={'name': 'Computer Science', 'status': 'Active'})
        dept_it, _ = Department.objects.get_or_create(code='IT', defaults={'name': 'Information Technology', 'status': 'Active'})
        dept_me, _ = Department.objects.get_or_create(code='ME', defaults={'name': 'Mechanical Engineering', 'status': 'Active'})

        # Faculty
        fac_user = User.objects.filter(username__contains='faculty').first() or User.objects.filter(is_staff=True).first()
        if not fac_user:
            fac_user = User.objects.create_user('demo_faculty_main', 'faculty@demo.localhost', 'admin123', is_staff=True)

        # Support Staff (Librarian)
        sup_user = User.objects.filter(username__contains='support').first() or fac_user

        # Students
        student_profiles = list(StudentProfile.objects.all())
        if not student_profiles:
            print("No student profiles found.")

        # Courses
        courses_data = [
            ('CS101', 'Data Structures & Algorithms', dept_cs),
            ('CS201', 'Database Management Systems', dept_cs),
            ('CS301', 'Operating Systems', dept_cs),
            ('IT101', 'Web Technologies', dept_it),
            ('IT201', 'Cloud Computing', dept_it),
            ('ME101', 'Thermodynamics', dept_me),
        ]
        course_objs = {}
        for code, name, dept in courses_data:
            obj, _ = Course.objects.get_or_create(course_code=code, defaults={'course_name': name, 'department': dept})
            course_objs[code] = obj

        # Classrooms
        classrooms_data = [
            ('Room 101', 'R101'),
            ('Room 102', 'R102'),
            ('Lab A', 'LABA'),
            ('Lab B', 'LABB'),
            ('Auditorium 1', 'AUD1'),
        ]
        room_objs = {}
        for name, code in classrooms_data:
            obj, _ = Classroom.objects.get_or_create(code=code, defaults={'name': name})
            room_objs[code] = obj

        # ── 2. Timetable / Weekly Schedules ──────────────────────────────
        schedules_spec = [
            ('Monday', '09:00', '10:00', 'CS101', 'R101'),
            ('Monday', '10:00', '11:00', 'CS201', 'R102'),
            ('Monday', '11:15', '12:15', 'IT101', 'LABA'),
            ('Monday', '14:00', '15:00', 'CS301', 'LABB'),

            ('Tuesday', '09:00', '10:00', 'IT101', 'R101'),
            ('Tuesday', '10:00', '11:00', 'IT201', 'R102'),
            ('Tuesday', '14:00', '16:00', 'CS101', 'LABA'),

            ('Wednesday', '09:00', '10:00', 'CS201', 'R101'),
            ('Wednesday', '10:00', '11:00', 'CS301', 'R102'),
            ('Wednesday', '11:15', '12:15', 'ME101', 'AUD1'),
            ('Wednesday', '14:00', '15:00', 'IT201', 'LABB'),

            ('Thursday', '09:00', '10:00', 'CS101', 'R101'),
            ('Thursday', '11:00', '12:00', 'IT201', 'R102'),
            ('Thursday', '14:00', '15:30', 'CS201', 'LABA'),

            ('Friday', '09:00', '10:00', 'IT101', 'R101'),
            ('Friday', '10:00', '11:00', 'CS301', 'R102'),
            ('Friday', '11:15', '12:15', 'ME101', 'AUD1'),
            ('Friday', '14:00', '15:00', 'CS101', 'LABB'),

            ('Saturday', '10:00', '12:00', 'CS301', 'AUD1'),
        ]

        schedule_objs = []
        for day, s_str, e_str, ccode, rcode in schedules_spec:
            sch, created = Schedule.objects.get_or_create(
                course=course_objs[ccode],
                classroom=room_objs[rcode],
                day_of_week=day,
                start_time=time.fromisoformat(s_str),
                defaults={
                    'faculty': fac_user,
                    'end_time': time.fromisoformat(e_str),
                    'semester': 'Semester 4',
                    'academic_year': '2025-2026',
                }
            )
            schedule_objs.append(sch)
        print(f"[+] Synced {len(schedule_objs)} Weekly Timetable Schedules.")

        # ── 3. Lectures from TODAY to Next 30 Days ─────────────────────────
        lectures_count = 0

        # Iterate 30 days starting from today
        for day_offset in range(0, 31):
            curr_date = today + timedelta(days=day_offset)
            curr_day_name = curr_date.strftime('%A')

            # Find schedules for this day of week
            day_schedules = [s for s in schedule_objs if s.day_of_week == curr_day_name]
            for s in day_schedules:
                start_dt = datetime.datetime.combine(curr_date, s.start_time)
                end_dt = datetime.datetime.combine(curr_date, s.end_time)

                lecture_name = f"{s.course.course_name} ({s.course.course_code})"
                lec = Lecture.objects.filter(start_time=start_dt, classroom=s.classroom).first()
                if not lec:
                    suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
                    code_str = f"L{s.course.course_code[2:]}{curr_date.strftime('%d%m')}{suffix}"
                    Lecture.objects.create(
                        name=lecture_name,
                        subject=s.course.course_name,
                        faculty=s.faculty or fac_user,
                        classroom=s.classroom,
                        start_time=start_dt,
                        end_time=end_dt,
                        code=code_str
                    )
                    lectures_count += 1

        print(f"[+] Generated {lectures_count} Lectures for the next 30 days (from {today} to {today + timedelta(days=30)}).")

        # ── 4. Announcements for Next 1 Month ─────────────────────────────
        announcements = [
            {
                'title': 'Midterm Examination Timetable Released',
                'content': 'The midterm examinations for Semester 4 will commence from the 15th of next month. All students must check their portals for individual seating arrangements and hall tickets.',
                'priority': 'urgent',
                'is_pinned': True,
                'expires_at': timezone.now() + timedelta(days=25)
            },
            {
                'title': 'Annual Campus Hackathon 2026',
                'content': 'Join us for a 36-hour codefest! Solve real-world challenges in AI, Cloud, and Web. Exciting cash prizes and internship opportunities. Registrations close in 2 weeks.',
                'priority': 'high',
                'is_pinned': True,
                'expires_at': timezone.now() + timedelta(days=20)
            },
            {
                'title': 'Guest Lecture: Scalable System Design & Microservices',
                'content': 'Industry expert from PolyNexus Systems will deliver a hands-on guest session in Auditorium 1 this Thursday at 2:00 PM. Attendance is compulsory for CS & IT students.',
                'priority': 'high',
                'is_pinned': False,
                'expires_at': timezone.now() + timedelta(days=7)
            },
            {
                'title': 'Central Library Book Circulation Notice',
                'content': 'All borrowed books due before the end of this month must be returned or renewed online to avoid late fines of Rs. 10/day.',
                'priority': 'normal',
                'is_pinned': False,
                'expires_at': timezone.now() + timedelta(days=30)
            },
            {
                'title': 'Hostel Maintenance & Security Audit',
                'content': 'Routine inspection of hostel rooms and wi-fi infrastructure will take place this weekend. Students are requested to cooperate with facility staff.',
                'priority': 'low',
                'is_pinned': False,
                'expires_at': timezone.now() + timedelta(days=10)
            }
        ]

        for item in announcements:
            Announcement.objects.get_or_create(
                title=item['title'],
                defaults={
                    'content': item['content'],
                    'author': fac_user,
                    'priority': item['priority'],
                    'is_pinned': item['is_pinned'],
                    'expires_at': item['expires_at']
                }
            )
        print("[+] Synced Announcements for the upcoming month.")

        # ── 5. Assignments for Next 1 Month ────────────────────────────────
        assignments_data = [
            {
                'title': 'Assignment 1: B-Tree & Red-Black Tree Implementation',
                'description': 'Implement balanced search trees in Python or C++. Submit clean code along with complexity analysis in PDF format.',
                'course': course_objs['CS101'],
                'dept': dept_cs,
                'due_date': timezone.now() + timedelta(days=5),
            },
            {
                'title': 'Assignment 2: SQL Query Optimization & Indexing',
                'description': 'Analyze execution plans for 10 complex multi-table queries. Optimize using indexes and partitioned schemas.',
                'course': course_objs['CS201'],
                'dept': dept_cs,
                'due_date': timezone.now() + timedelta(days=12),
            },
            {
                'title': 'Assignment 3: RESTful API & JWT Authentication App',
                'description': 'Build a Node.js/Django backend API with JWT authentication, role-based access control, and Swagger documentation.',
                'course': course_objs['IT101'],
                'dept': dept_it,
                'due_date': timezone.now() + timedelta(days=18),
            },
            {
                'title': 'Assignment 4: Docker & Kubernetes Microservice Deployment',
                'description': 'Containerize a multi-service app using Docker Compose and deploy to a local Minikube cluster with horizontal scaling.',
                'course': course_objs['IT201'],
                'dept': dept_it,
                'due_date': timezone.now() + timedelta(days=25),
            },
            {
                'title': 'Assignment 5: Operating System Process Scheduler Simulator',
                'description': 'Simulate Round Robin, Shortest Job First (SJF), and Priority Scheduling algorithms in Python.',
                'course': course_objs['CS301'],
                'dept': dept_cs,
                'due_date': timezone.now() + timedelta(days=28),
            },
        ]

        for ad in assignments_data:
            Assignment.objects.get_or_create(
                title=ad['title'],
                defaults={
                    'description': ad['description'],
                    'course': ad['course'],
                    'department': ad['dept'],
                    'due_date': ad['due_date'],
                    'created_by': fac_user
                }
            )
        print("[+] Synced Assignments due over the next month.")

        # ── 6. Library Books, Stock Copies & Issue Records ──────────────────
        books_data = [
            ('Introduction to Algorithms', 'Thomas H. Cormen', '978-0262033848', 'MIT Press', 10, 7),
            ('Clean Code: A Handbook of Agile Software Craftsmanship', 'Robert C. Martin', '978-0132350884', 'Prentice Hall', 8, 5),
            ('Design Patterns: Elements of Reusable Object-Oriented Software', 'Erich Gamma et al.', '978-0201633610', 'Addison-Wesley', 6, 4),
            ('Database System Concepts', 'Abraham Silberschatz', '978-0073523323', 'McGraw-Hill', 12, 9),
            ('Operating System Concepts', 'Abraham Silberschatz', '978-1118063330', 'Wiley', 10, 8),
            ('Computer Networks', 'Andrew S. Tanenbaum', '978-0132126953', 'Pearson', 7, 5),
            ('Artificial Intelligence: A Modern Approach', 'Stuart Russell', '978-0134610993', 'Pearson', 5, 3),
            ('Python Crash Course', 'Eric Matthes', '978-1593279288', 'No Starch Press', 15, 12),
        ]

        for b_title, b_author, b_isbn, b_pub, total_c, avail_c in books_data:
            book_obj, created = Book.objects.get_or_create(
                isbn=b_isbn,
                defaults={
                    'title': b_title,
                    'author': b_author,
                    'publisher': b_pub,
                    'total_copies': total_c,
                    'available_copies': avail_c
                }
            )

            # Ensure copies exist
            existing_copies = list(book_obj.copies.all())
            copies_needed = total_c - len(existing_copies)
            for i in range(copies_needed):
                barcode = f"BC-{b_isbn[-6:]}-{len(existing_copies) + i + 1:02d}"
                status_choice = 'Available' if i < avail_c else 'Issued'
                copy_obj = BookCopy.objects.create(
                    book=book_obj,
                    barcode=barcode,
                    status=status_choice
                )

                # If copy status is Issued, create issue record with student
                if status_choice == 'Issued' and student_profiles:
                    chosen_student = random.choice(student_profiles)
                    issued_d = today - timedelta(days=random.randint(1, 10))
                    due_d = issued_d + timedelta(days=14)
                    BookIssue.objects.create(
                        book_copy=copy_obj,
                        student=chosen_student,
                        due_date=due_d,
                        status='Issued'
                    )

        print("[+] Synced Library Books, Stock Copies, and Student Issue Records.")

print("\n[SUCCESS] ALL DUMMY DATA FOR NEXT 1 MONTH SEEDED SUCCESSFULLY!")

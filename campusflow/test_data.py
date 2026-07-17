"""
CampusFlow Comprehensive Test Data Seeder (Django Shell)
======================================================
This script dynamically finds all active tenants, identifies their existing
students, faculty, and support staff, and populates rich test data across
all modules:
  - Departments & Courses
  - Classrooms & Schedules
  - Lectures (past and today)
  - Attendance (past logs & active sessions)
  - Hostels, Rooms, and allocations
  - Fees (categories, structures, bulk generated invoices, and payments)
  - Bus routes, subscriptions, and attendance logs
  - Library books, copies, and issues
  - Exams & Results
  - Announcements, Assignments & Submissions
  - Leaves (types, balances, requests)

Run on the VM with:
  python manage.py shell < seed_all_test_data.py
"""

import os
import sys
import django
import random
import uuid
import datetime
from datetime import date, time, timedelta
from decimal import Decimal

# Set up django if run as standalone script
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
    django.setup()

from django_tenants.utils import schema_context
from tenants.models import Tenant
from django.contrib.auth.models import User, Group, Permission
from django.utils import timezone

# ── Synced Tenant Check ──────────────────────────────────────────────────────
active_tenants = Tenant.objects.exclude(schema_name='public')
if not active_tenants.exists():
    print("❌ No active tenants found! Please create a tenant first.")
    sys.exit(1)

print(f"Found active tenants: {[t.schema_name for t in active_tenants]}")

for tenant in active_tenants:
    print(f"\n" + "="*80)
    print(f"🌱 SEEDING TEST DATA FOR TENANT: '{tenant.name}' ({tenant.schema_name})")
    print("="*80)
    
    with schema_context(tenant.schema_name):
        from campusflow_app.models import (
            Department, Course, Classroom, Schedule, Lecture,
            StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile,
            ManagementProfile, AdministratorProfile, DepartmentHeadProfile,
            Attendance, FaceAttendanceLog, AttendanceSession,
            Announcement, LeaveType, LeaveBalance, LeaveRequest,
            ExamType, Exam, Assignment, AssignmentSubmission,
            ManualAttendanceRequest, Location,
            Hostel, HostelRoom, HostelAllocation,
            FeeCategory, FeeStructure, FeeStructureItem,
            StudentFeeInvoice, StudentFeeInvoiceItem, FeePayment,
            Book, BookCopy, BookIssue,
            BusRoute, BusSubscription, BusAttendance, BusLocation, BusTrip
        )

        today = date.today()
        now_dt = timezone.now()

        # ── 1. Create Default Users if None Exist ──────────────────────────────
        print("Checking existing users...")
        students = list(StudentProfile.objects.filter(status='active'))
        faculty = list(TeachingStaffProfile.objects.filter(status='active'))
        support = list(NonTeachingStaffProfile.objects.filter(status='active'))
        admins = list(AdministratorProfile.objects.filter(status='active'))

        # Create basic roles groups
        group_map = {}
        for role_name in ['student', 'Faculty', 'Support Staff', 'Management', 'Administrator', 'Department Head']:
            grp, _ = Group.objects.get_or_create(name=role_name)
            group_map[role_name] = grp

        def assign_role(u, rname):
            u.groups.clear()
            u.groups.add(group_map[rname])
            u.save()

        # Generate fallback HOD user if needed
        u_hod_user = User.objects.filter(groups__name='Department Head').first()
        if not u_hod_user:
            u_hod_user, created = User.objects.get_or_create(
                username='demo_hod_test',
                defaults={'email': f'hod_test@{tenant.permitted_email_domain}', 'first_name': 'Robert', 'last_name': 'HOD', 'is_active': True}
            )
            if created:
                u_hod_user.set_password('Password123')
                u_hod_user.save()
            assign_role(u_hod_user, 'Department Head')

        # Fallback Admin
        u_admin_user = User.objects.filter(groups__name='Administrator').first()
        if not u_admin_user:
            u_admin_user = User.objects.filter(is_superuser=True).first()
            if not u_admin_user:
                u_admin_user, created = User.objects.get_or_create(
                    username='demo_admin_test',
                    defaults={'email': f'admin_test@{tenant.permitted_email_domain}', 'first_name': 'System', 'last_name': 'Admin', 'is_active': True, 'is_staff': True}
                )
                if created:
                    u_admin_user.set_password('Password123')
                    u_admin_user.save()
                assign_role(u_admin_user, 'Administrator')

        # Create HOD profile
        dept_head_profile, _ = DepartmentHeadProfile.objects.get_or_create(
            user=u_hod_user,
            defaults={'employee_id': 'TEST-HOD-001', 'status': 'active', 'designation': 'HOD Computer Science'}
        )

        # Ensure we have at least 3 departments
        dept_cs, _ = Department.objects.get_or_create(code='CS', defaults={'name': 'Computer Science', 'status': 'Active', 'hod': u_hod_user})
        dept_it, _ = Department.objects.get_or_create(code='IT', defaults={'name': 'Information Technology', 'status': 'Active', 'hod': u_hod_user})
        dept_me, _ = Department.objects.get_or_create(code='ME', defaults={'name': 'Mechanical Engineering', 'status': 'Active'})
        print("✅ Departments Synced (CS, IT, ME).")

        # Map HOD profile department
        if not dept_head_profile.department:
            dept_head_profile.department = dept_cs
            dept_head_profile.save()

        # If no students, register dummy ones
        if not students:
            print("No students found. Creating dummy students for testing...")
            for i in range(1, 4):
                stu_user, created = User.objects.get_or_create(
                    username=f'test_student_{i}',
                    defaults={'email': f'student{i}@{tenant.permitted_email_domain}', 'first_name': f'Student{i}', 'last_name': 'Test', 'is_active': True}
                )
                if created:
                    stu_user.set_password('Password123')
                    stu_user.save()
                assign_role(stu_user, 'student')
                
                sp, _ = StudentProfile.objects.get_or_create(
                    user=stu_user,
                    defaults={
                        'student_id': f'STU-TEST-00{i}',
                        'admission_number': f'ADM-TEST-00{i}',
                        'status': 'active',
                        'department': dept_cs if i < 3 else dept_it,
                        'program_enrolled_in': 'B.Tech CS' if i < 3 else 'B.Tech IT',
                        'batch_academic_year': '2024-2025',
                        'current_semester_year': 'Semester 4',
                        'section_division': 'A',
                        'is_face_registered': True,
                        'locked_device_id': f'DEVICE_TEST_{i}'
                    }
                )
                students.append(sp)
            print(f"✅ Created {len(students)} test student profiles.")

        # If no faculty, register dummy ones
        if not faculty:
            print("No faculty found. Creating dummy faculty for testing...")
            for i in range(1, 3):
                fac_user, created = User.objects.get_or_create(
                    username=f'test_faculty_{i}',
                    defaults={'email': f'faculty{i}@{tenant.permitted_email_domain}', 'first_name': f'Professor{i}', 'last_name': 'Test', 'is_active': True}
                )
                if created:
                    fac_user.set_password('Password123')
                    fac_user.save()
                assign_role(fac_user, 'Faculty')
                
                fp, _ = TeachingStaffProfile.objects.get_or_create(
                    user=fac_user,
                    defaults={
                        'employee_id': f'FAC-TEST-00{i}',
                        'status': 'active',
                        'designation': 'Assistant Professor',
                        'department': dept_cs if i == 1 else dept_it,
                        'qualifications': 'M.Tech',
                        'experience_years': 5
                    }
                )
                faculty.append(fp)
            print(f"✅ Created {len(faculty)} test faculty profiles.")

        # If no support staff, register dummy ones
        if not support:
            print("No support staff found. Creating dummy support staff for testing...")
            for i in range(1, 3):
                sup_user, created = User.objects.get_or_create(
                    username=f'test_support_{i}',
                    defaults={'email': f'support{i}@{tenant.permitted_email_domain}', 'first_name': f'Support{i}', 'last_name': 'Test', 'is_active': True}
                )
                if created:
                    sup_user.set_password('Password123')
                    sup_user.save()
                assign_role(sup_user, 'Support Staff')
                
                spp, _ = NonTeachingStaffProfile.objects.get_or_create(
                    user=sup_user,
                    defaults={
                        'employee_id': f'SUP-TEST-00{i}',
                        'status': 'active',
                        'designation': 'Bus Driver' if i == 1 else 'Conductor'
                    }
                )
                support.append(spp)
            print(f"✅ Created {len(support)} test support staff profiles.")

        # Extract underlying users
        u_students = [sp.user for sp in students]
        u_faculty = [fp.user for fp in faculty]
        u_support = [spp.user for spp in support]

        # ── 2. Courses & Classrooms ───────────────────────────────────────────
        course_cs101, _ = Course.objects.get_or_create(course_code='CS101', defaults={'course_name': 'Data Structures & Algorithms', 'department': dept_cs})
        course_cs201, _ = Course.objects.get_or_create(course_code='CS201', defaults={'course_name': 'Database Management Systems', 'department': dept_cs})
        course_it101, _ = Course.objects.get_or_create(course_code='IT101', defaults={'course_name': 'Web Technologies', 'department': dept_it})
        
        classroom_r101, _ = Classroom.objects.get_or_create(code='R101', defaults={'name': 'Room 101'})
        classroom_r102, _ = Classroom.objects.get_or_create(code='R102', defaults={'name': 'Room 102'})
        classroom_lab, _ = Classroom.objects.get_or_create(code='LABA', defaults={'name': 'Lab A'})
        print("✅ Courses & Classrooms Synced.")

        # ── 3. Check-In Locations (Geofences) ──────────────────────────────────
        loc_premises, _ = Location.objects.get_or_create(
            location_id=f"none_Main_Gate_21.15_79.09",
            defaults={
                'name': 'Main Gate Premises',
                'latitude': 21.1500,
                'longitude': 79.0900,
                'geofence_radius_meters': 50,
                'is_premises_entry': True
            }
        )
        loc_classroom, _ = Location.objects.get_or_create(
            location_id=f"{dept_cs.id}_R101_21.1501_79.0901",
            defaults={
                'name': 'Room 101 Geofence',
                'latitude': 21.1501,
                'longitude': 79.0901,
                'geofence_radius_meters': 15,
                'is_classroom_entry': True,
                'department_owner': dept_cs
            }
        )
        print("✅ Check-in Locations configured.")

        # ── 4. Weekly Timetables & Schedules ──────────────────────────────────
        timetable = [
            ('Monday', '09:00', '10:00', course_cs101, classroom_r101, u_faculty[0]),
            ('Monday', '10:00', '11:00', course_cs201, classroom_r102, u_faculty[0]),
            ('Tuesday', '09:00', '10:00', course_it101, classroom_r101, u_faculty[1] if len(u_faculty) > 1 else u_faculty[0]),
            ('Wednesday', '14:00', '15:00', course_cs101, classroom_lab, u_faculty[0]),
        ]
        schedules = []
        for day, start_time_str, end_time_str, course, classroom, fac in timetable:
            sch, _ = Schedule.objects.get_or_create(
                course=course,
                classroom=classroom,
                day_of_week=day,
                start_time=time.fromisoformat(start_time_str),
                defaults={
                    'faculty': fac,
                    'end_time': time.fromisoformat(end_time_str),
                    'semester': 'Semester 4',
                    'academic_year': '2024-2025'
                }
            )
            schedules.append(sch)
        print("✅ Weekly Schedules configured.")

        # ── 5. Lectures & Simulated Past Attendance Logs ───────────────────────
        monday = today - timedelta(days=today.weekday())
        DAY_IDX = {d: i for i, d in enumerate(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])}
        
        lectures_created = 0
        attendances_created = 0
        
        # Seed lectures for the past 2 weeks
        for week_offset in [-2, -1, 0]:
            week_monday = monday + timedelta(weeks=week_offset)
            for day, start_time_str, end_time_str, course, classroom, fac in timetable:
                lecture_date = week_monday + timedelta(days=DAY_IDX[day])
                # Only seed for past lectures or today
                if lecture_date > today:
                    continue

                start_dt = datetime.datetime.combine(lecture_date, time.fromisoformat(start_time_str))
                end_dt = datetime.datetime.combine(lecture_date, time.fromisoformat(end_time_str))
                
                # Create Lecture
                suffix = ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=5))
                code_str = f"L{course.course_code[2:]}{lecture_date.strftime('%d%m')}{suffix}"
                
                lec, created = Lecture.objects.get_or_create(
                    start_time=start_dt,
                    classroom=classroom,
                    defaults={
                        'name': f"{course.course_name} Session",
                        'subject': course.course_name,
                        'faculty': fac,
                        'end_time': end_dt,
                        'code': code_str
                    }
                )
                if created:
                    lectures_created += 1

                # Select students belonging to this department
                dept_students = [sp for sp in students if sp.department == course.department]
                for sp in dept_students:
                    # Randomly mark present (85% attendance rate)
                    if random.random() < 0.85:
                        att, att_created = Attendance.objects.get_or_create(
                            user=sp.user,
                            lecture=lec,
                            defaults={
                                'check_in_time': start_dt + timedelta(minutes=random.randint(1, 12)),
                                'is_geofence_valid': True,
                                'device_id': sp.locked_device_id or 'DEVICE_MOCK_123',
                                'verification_method': 'face_geofence'
                            }
                        )
                        if att_created:
                            attendances_created += 1
                        
                        # Face Log
                        FaceAttendanceLog.objects.get_or_create(
                            student=sp,
                            lecture=lec,
                            defaults={
                                'confidence_score': round(random.uniform(0.80, 0.99), 2),
                                'is_verified': True,
                                'liveness_passed': True,
                                'timestamp': att.check_in_time if att_created else start_dt
                            }
                        )
        print(f"✅ Generated {lectures_created} Lectures and {attendances_created} Attendance Records.")

        # Live Attendance Session for today if we are during lecture hour
        now_time = datetime.datetime.now()
        active_lec = Lecture.objects.filter(start_time__lte=now_time, end_time__gte=now_time).first()
        if active_lec:
            AttendanceSession.objects.get_or_create(
                lecture=active_lec,
                defaults={
                    'started_by': active_lec.faculty,
                    'duration_minutes': 60,
                    'latitude': 21.1501,
                    'longitude': 79.0901,
                    'radius_meters': 100,
                    'is_active': True
                }
            )
            print(f"✅ Started active Attendance Session for lecture: {active_lec.name}")

        # ── 6. Hostel Module ──────────────────────────────────────────────────
        hostel_boys, _ = Hostel.objects.get_or_create(
            name="Ramanujan Boys Hostel",
            defaults={'gender_type': 'Boys', 'capacity': 120, 'address': 'Campus North Wing'}
        )
        hostel_girls, _ = Hostel.objects.get_or_create(
            name="Kalpana Girls Hostel",
            defaults={'gender_type': 'Girls', 'capacity': 100, 'address': 'Campus South Wing'}
        )
        
        # Add Rooms
        for room_no in ['101', '102', '103', '201']:
            HostelRoom.objects.get_or_create(
                hostel=hostel_boys,
                room_number=room_no,
                defaults={'capacity': 3, 'rent_per_semester': Decimal('22000.00')}
            )
            HostelRoom.objects.get_or_create(
                hostel=hostel_girls,
                room_number=room_no,
                defaults={'capacity': 2, 'rent_per_semester': Decimal('26000.00')}
            )

        # Allocate some rooms to existing students
        room_b101 = HostelRoom.objects.get(hostel=hostel_boys, room_number='101')
        room_g101 = HostelRoom.objects.get(hostel=hostel_girls, room_number='101')
        
        allocated_count = 0
        for sp in students:
            target_room = room_g101 if sp.gender == 'Female' else room_b101
            if target_room.occupied_beds < target_room.capacity:
                alloc, created = HostelAllocation.objects.get_or_create(
                    student=sp,
                    room=target_room,
                    defaults={'status': 'Allocated', 'allocated_date': today - timedelta(days=60)}
                )
                if created:
                    target_room.occupied_beds += 1
                    target_room.save()
                    allocated_count += 1
        print(f"✅ Hostels seeded. Allocated {allocated_count} students to rooms.")

        # ── 7. Fees Module ────────────────────────────────────────────────────
        cat_tuition, _ = FeeCategory.objects.get_or_create(name='Tuition Fee', defaults={'description': 'Standard semester tuition fees'})
        cat_exam, _ = FeeCategory.objects.get_or_create(name='Exam Fee', defaults={'description': 'Midterm & Endterm exams charges'})
        cat_bus, _ = FeeCategory.objects.get_or_create(name='Bus Fee', defaults={'description': 'Transportation fee'})
        cat_hostel, _ = FeeCategory.objects.get_or_create(name='Hostel Rent', defaults={'description': 'Hostel lodging fee'})
        
        # Fee structure for CS B.Tech Semester 4
        fee_struct, _ = FeeStructure.objects.get_or_create(
            name='B.Tech CS - Semester 4 Standard',
            defaults={
                'department': dept_cs,
                'batch_academic_year': '2024-2025',
                'program_enrolled_in': 'B.Tech CS',
                'current_semester_year': 'Semester 4'
            }
        )
        
        FeeStructureItem.objects.get_or_create(fee_structure=fee_struct, category=cat_tuition, defaults={'amount': Decimal('48000.00')})
        FeeStructureItem.objects.get_or_create(fee_structure=fee_struct, category=cat_exam, defaults={'amount': Decimal('4500.00')})
        FeeStructureItem.objects.get_or_create(fee_structure=fee_struct, category=cat_bus, defaults={'amount': Decimal('8500.00')})
        FeeStructureItem.objects.get_or_create(fee_structure=fee_struct, category=cat_hostel, defaults={'amount': Decimal('22000.00')})
        
        total_fees = Decimal('83000.00')
        
        # Generate invoices & payments
        invoices_created = 0
        payments_recorded = 0
        for sp in students:
            if sp.department == dept_cs:
                invoice, created = StudentFeeInvoice.objects.get_or_create(
                    student=sp.user,
                    fee_structure=fee_struct,
                    defaults={
                        'invoice_number': f"INV-{tenant.code.upper()}-{sp.student_id[-4:]}",
                        'due_date': today + timedelta(days=30),
                        'total_amount': total_fees,
                        'discount_amount': Decimal('0.00'),
                        'status': 'unpaid'
                    }
                )
                if created:
                    invoices_created += 1
                    StudentFeeInvoiceItem.objects.create(invoice=invoice, category=cat_tuition, amount=Decimal('48000.00'))
                    StudentFeeInvoiceItem.objects.create(invoice=invoice, category=cat_exam, amount=Decimal('4500.00'))
                    StudentFeeInvoiceItem.objects.create(invoice=invoice, category=cat_bus, amount=Decimal('8500.00'))
                    StudentFeeInvoiceItem.objects.create(invoice=invoice, category=cat_hostel, amount=Decimal('22000.00'))
                
                # Partially pay student 1, fully pay student 2
                if invoice.status == 'unpaid':
                    if sp == students[0]:
                        # Partially paid
                        FeePayment.objects.create(
                            invoice=invoice,
                            amount_paid=Decimal('50000.00'),
                            payment_method='upi',
                            transaction_reference=f"UPI-TXN-{uuid.uuid4().hex[:10].upper()}",
                            remarks='Partial fee payment (Tuition)',
                            collected_by=u_admin_user
                        )
                        invoice.paid_amount = Decimal('50000.00')
                        invoice.status = 'partially_paid'
                        invoice.save()
                        payments_recorded += 1
                    elif len(students) > 1 and sp == students[1]:
                        # Fully paid
                        FeePayment.objects.create(
                            invoice=invoice,
                            amount_paid=total_fees,
                            payment_method='net_banking',
                            transaction_reference=f"NEFT-TXN-{uuid.uuid4().hex[:10].upper()}",
                            remarks='Full fee payment',
                            collected_by=u_admin_user
                        )
                        invoice.paid_amount = total_fees
                        invoice.status = 'paid'
                        invoice.save()
                        payments_recorded += 1
        print(f"✅ Fees category, structure, {invoices_created} invoices, and {payments_recorded} payments created.")

        # ── 8. Bus/Transit Tracking Module ───────────────────────────────────
        # Ensure we have driver and conductor users
        driver_user = u_support[0] if u_support else u_admin_user
        conductor_user = u_support[1] if len(u_support) > 1 else u_admin_user

        route1, _ = BusRoute.objects.get_or_create(
            name="Transit Route 1 - Civil Lines",
            defaults={
                'driver': driver_user,
                'conductor': conductor_user,
                'stops': [
                    {"name": "Civil Lines Station", "lat": 21.1550, "lng": 79.0800},
                    {"name": "Ambazari Square", "lat": 21.1350, "lng": 79.0500},
                    {"name": "College Gate", "lat": 21.1500, "lng": 79.0900}
                ],
                'is_active': True
            }
        )
        
        # Add bus subscriptions for all CS students
        subs_created = 0
        for sp in students:
            if sp.department == dept_cs:
                sub, created = BusSubscription.objects.get_or_create(
                    user=sp.user,
                    route=route1,
                    defaults={
                        'status': 'active',
                        'boarding_stop': 'Civil Lines Station',
                        'valid_from': today - timedelta(days=90),
                        'valid_until': today + timedelta(days=90),
                        'notes': 'Semester 4 active subscription'
                    }
                )
                if created:
                    subs_created += 1

        # Simulate last 5 days bus attendance boarding events
        bus_scans = 0
        for day_offset in range(5):
            scan_date = now_dt - timedelta(days=day_offset, hours=random.randint(0, 1))
            for sp in students:
                if sp.department == dept_cs:
                    # check if record exists
                    exists = BusAttendance.objects.filter(user=sp.user, route=route1, scanned_at__date=scan_date.date()).exists()
                    if not exists:
                        BusAttendance.objects.create(
                            user=sp.user,
                            route=route1,
                            device_id=f"BUS_DEV_{sp.user.username.upper()}"
                        )
                        bus_scans += 1
                        
        # Live position update
        BusLocation.objects.update_or_create(
            user=driver_user,
            defaults={'lat': 21.1550, 'lng': 79.0800, 'route': route1}
        )
        print(f"✅ Transit routes, {subs_created} subscriptions, and {bus_scans} scans seeded.")

        # ── 9. Library Module ─────────────────────────────────────────────────
        books_data = [
            {'title': 'Introduction to Algorithms (4th Ed)', 'author': 'Thomas H. Cormen', 'isbn': '978-0262033848', 'publisher': 'MIT Press', 'total_copies': 6, 'available_copies': 4},
            {'title': 'Database System Concepts (7th Ed)', 'author': 'Abraham Silberschatz', 'isbn': '978-0078022159', 'publisher': 'McGraw-Hill', 'total_copies': 4, 'available_copies': 3},
            {'title': 'Operating System Concepts (10th Ed)', 'author': 'Abraham Silberschatz', 'isbn': '978-1119800361', 'publisher': 'Wiley', 'total_copies': 3, 'available_copies': 3}
        ]
        
        books_seeded = 0
        copies_seeded = 0
        issues_seeded = 0
        for bd in books_data:
            book, created = Book.objects.get_or_create(isbn=bd['isbn'], defaults=bd)
            if created:
                books_seeded += 1
                # Create copies
                for c_idx in range(1, bd['total_copies'] + 1):
                    BookCopy.objects.create(
                        book=book,
                        barcode=f"{bd['isbn'][-4:]}-{c_idx:03d}",
                        status='Available'
                    )
                    copies_seeded += 1

        # Issue some books to students
        student_sp = students[0]
        avail_copy = BookCopy.objects.filter(status='Available').first()
        if avail_copy:
            issue, created = BookIssue.objects.get_or_create(
                book_copy=avail_copy,
                student=student_sp,
                defaults={
                    'due_date': today + timedelta(days=14),
                    'status': 'Issued',
                    'fine_amount': Decimal('0.00')
                }
            )
            if created:
                avail_copy.status = 'Issued'
                avail_copy.save()
                issues_seeded += 1
        print(f"✅ Library: {books_seeded} books, {copies_seeded} copies, {issues_seeded} issues generated.")

        # ── 10. Exams & Results ───────────────────────────────────────────────
        et_mid, _ = ExamType.objects.get_or_create(code='MID', defaults={'name': 'Mid-Term Exam'})
        et_end, _ = ExamType.objects.get_or_create(code='END', defaults={'name': 'End Semester Exam'})
        
        exam1, _ = Exam.objects.get_or_create(
            name="Data Structures Midterm",
            exam_type=et_mid,
            course=course_cs101,
            defaults={
                'department': dept_cs,
                'date': today + timedelta(days=5),
                'start_time': time(10, 0),
                'end_time': time(12, 0),
                'classroom': classroom_r101,
                'total_marks': 50,
                'passing_marks': 18,
                'semester': 'Semester 4',
                'academic_year': '2024-2025',
                'invigilator': u_faculty[0],
                'created_by': u_hod_user,
                'status': 'scheduled'
            }
        )
        print("✅ Exams scheduled.")

        # ── 11. Announcements, Assignments & Submissions ──────────────────────
        Announcement.objects.get_or_create(
            title="SaaS Portal Go-Live Announcement",
            defaults={
                'content': "We are excited to launch the new smart campus ERP portal. Please verify your profiles, check-in using QR codes, and view fee invoices.",
                'author': u_admin_user,
                'priority': 'high',
                'is_pinned': True
            }
        )

        assign_cs101, _ = Assignment.objects.get_or_create(
            title="Stack & Queue Implementation in Python",
            course=course_cs101,
            defaults={
                'description': "Implement Stack and Queue using dynamic arrays and lists. Submit code zip file.",
                'department': dept_cs,
                'due_date': now_dt + timedelta(days=3),
                'created_by': u_faculty[0]
            }
        )
        
        # Submissions
        for sp in students:
            if sp.department == dept_cs:
                AssignmentSubmission.objects.get_or_create(
                    assignment=assign_cs101,
                    student=sp.user,
                    defaults={
                        'text_submission': "Implemented all classes, tested stack overflow and underflow conditions.",
                        'grade': 'A' if sp == students[0] else 'B',
                        'feedback': 'Good structure and performance.' if sp == students[0] else 'Keep it up.',
                        'status': 'graded'
                    }
                )
        print("✅ Announcements, Assignments and Submissions completed.")

        # ── 12. Leaves Module ─────────────────────────────────────────────────
        lt_cl, _ = LeaveType.objects.get_or_create(code='CL', defaults={'name': 'Casual Leave', 'max_days': 12, 'is_paid': True})
        lt_sl, _ = LeaveType.objects.get_or_create(code='SL', defaults={'name': 'Sick Leave', 'max_days': 10, 'is_paid': True})
        
        # Assign Leave Balance & Request for faculty
        for fac_user in u_faculty:
            LeaveBalance.objects.get_or_create(
                user=fac_user,
                leave_type=lt_cl,
                academic_year='2024-2025',
                defaults={'allocated': 12, 'used': 2}
            )
            LeaveBalance.objects.get_or_create(
                user=fac_user,
                leave_type=lt_sl,
                academic_year='2024-2025',
                defaults={'allocated': 10, 'used': 0}
            )
            
            # Pending request
            LeaveRequest.objects.get_or_create(
                user=fac_user,
                leave_type=lt_cl,
                start_date=today + timedelta(days=4),
                end_date=today + timedelta(days=5),
                defaults={
                    'reason': 'Attending higher education credentials conference.',
                    'status': 'pending'
                }
            )
        print("✅ Leaves modules seeded.")
        
        print(f"🎉 SUCCESS: Test data successfully seeded for tenant '{tenant.schema_name}'!")

print("\n" + "="*80)
print("🏁 GLOBAL SEEDING COMPLETE FOR ALL TENANTS!")
print("="*80)

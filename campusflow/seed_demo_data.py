"""
CampusFlow Demo Data Seeder
==========================
Creates the 'demo' tenant and seeds it with rich, premium, and comprehensive
demo data including:
  - 'demo' Tenant (College) & domains (demo.localhost & staging domain)
  - All standard Groups (student, Faculty, Support Staff, Management, Administrator, Department Head)
  - 3 Departments (CS, IT, ME)
  - Active Users with Profiles for every role (demo_admin, demo_mgmt, demo_hod, demo_faculty, demo_student, etc.)
  - Courses, Classrooms, and Schedules
  - Weekly timetables & simulated past attendance logs + marks
  - Active attendance sessions for today
  - Announcements, Exams, Assignments & Submissions, and Leaves.

Run with:
  python manage.py shell < seed_demo_data.py
    OR
  python seed_demo_data.py
"""

import os
import sys
import django

# Set up django if run as standalone script
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
    django.setup()

from tenants.models import Tenant, Domain
from django_tenants.utils import schema_context
from django.contrib.auth.models import User, Group, Permission
from django.contrib.contenttypes.models import ContentType
import uuid
import datetime
from datetime import date, time, timedelta

SCHEMA = 'demo'
TENANT_NAME = 'Demo College'
TENANT_CODE = 'demo'

# Find the domain from public schema, to match hostnames automatically
public_tenant = Tenant.objects.filter(schema_name='public').first()
public_domain_name = 'localhost'
if public_tenant:
    pd = Domain.objects.filter(tenant=public_tenant, is_primary=True).first()
    if pd:
        public_domain_name = pd.domain

# Determine domains to create for the demo tenant
domains_to_create = ['demo.localhost']
if public_domain_name != 'localhost':
    domains_to_create.append(f"demo.{public_domain_name}")

# ── 1. Create/Get Tenant ──────────────────────────────────────────────────────
tenant = Tenant.objects.filter(schema_name=SCHEMA).first()
if not tenant:
    print(f"Creating tenant '{SCHEMA}'...")
    tenant = Tenant.objects.create(
        schema_name=SCHEMA,
        name=TENANT_NAME,
        code=TENANT_CODE,
        address="123 Education Lane, Demo City",
        contact_email="admin@demo.localhost",
        permitted_email_domain="demo.localhost",
        timezone="Asia/Kolkata"
    )
    print(f"✅ Tenant '{SCHEMA}' created successfully.")
else:
    print(f"✅ Tenant '{SCHEMA}' already exists.")

# Ensure primary and secondary domains exist
for i, dom in enumerate(domains_to_create):
    is_primary = (i == 0)
    domain_obj = Domain.objects.filter(domain=dom).first()
    if not domain_obj:
        Domain.objects.create(
            domain=dom,
            tenant=tenant,
            is_primary=is_primary
        )
        print(f"✅ Domain '{dom}' created.")
    else:
        print(f"✅ Domain '{dom}' already exists.")

# ── 2. Switch Context and Populate Demo Data ──────────────────────────────────
print(f"Switching context to schema '{SCHEMA}'...")
with schema_context(SCHEMA):
    from django.contrib.auth.models import Group, User
    from campusflow_app.models import (
        Department, Course, Classroom, Schedule, Lecture,
        StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile,
        ManagementProfile, AdministratorProfile, DepartmentHeadProfile,
        Attendance, FaceAttendanceLog, AttendanceSession,
        Announcement, LeaveType, LeaveBalance, LeaveRequest,
        ExamType, Exam, Assignment, AssignmentSubmission,
        ManualAttendanceRequest
    )

    # A. Role Groups
    roles = ['student', 'Faculty', 'Support Staff', 'Management', 'Administrator', 'Department Head']
    group_map = {}
    for role_name in roles:
        grp, created = Group.objects.get_or_create(name=role_name)
        group_map[role_name] = grp
        if created:
            print(f"   Created group '{role_name}'")

    # Helper function to assign user to group
    def assign_user_to_role(u, rname):
        u.groups.clear()
        u.groups.add(group_map[rname])
        # Add basic permissions from the group
        group_permissions_codenames = group_map[rname].permissions.values_list('codename', flat=True)
        u.user_permissions.set(Permission.objects.filter(codename__in=group_permissions_codenames))
        u.save()

    # B. Departments
    dept_cs, _ = Department.objects.get_or_create(code='CS', defaults={'name': 'Computer Science', 'status': 'Active'})
    dept_it, _ = Department.objects.get_or_create(code='IT', defaults={'name': 'Information Technology', 'status': 'Active'})
    dept_me, _ = Department.objects.get_or_create(code='ME', defaults={'name': 'Mechanical Engineering', 'status': 'Active'})
    print("✅ Departments synced (CS, IT, ME).")

    # C. Users & Profiles
    
    # Administrator (demo_admin)
    u_admin, created = User.objects.get_or_create(
        username='demo_admin',
        defaults={
            'email': 'admin@demo.localhost',
            'first_name': 'Demo',
            'last_name': 'Admin',
            'is_staff': True,
            'is_active': True
        }
    )
    if created:
        u_admin.set_password('admin123')
        u_admin.save()
    assign_user_to_role(u_admin, 'Administrator')
    profile_admin, _ = AdministratorProfile.objects.get_or_create(
        user=u_admin,
        defaults={
            'employee_id': 'DEMO-ADM-001',
            'status': 'active',
            'designation': 'System Administrator'
        }
    )
    print("   ✅ User 'demo_admin' (Administrator) created/active.")

    # Management (demo_mgmt)
    u_mgmt, created = User.objects.get_or_create(
        username='demo_mgmt',
        defaults={
            'email': 'mgmt@demo.localhost',
            'first_name': 'Demo',
            'last_name': 'Director',
            'is_active': True
        }
    )
    if created:
        u_mgmt.set_password('admin123')
        u_mgmt.save()
    assign_user_to_role(u_mgmt, 'Management')
    profile_mgmt, _ = ManagementProfile.objects.get_or_create(
        user=u_mgmt,
        defaults={
            'employee_id': 'DEMO-MGT-001',
            'status': 'active',
            'designation': 'College Director'
        }
    )
    print("   ✅ User 'demo_mgmt' (Management) created/active.")

    # Department Head (demo_hod)
    u_hod, created = User.objects.get_or_create(
        username='demo_hod',
        defaults={
            'email': 'hod@demo.localhost',
            'first_name': 'Dr. Robert',
            'last_name': 'HOD',
            'is_active': True
        }
    )
    if created:
        u_hod.set_password('admin123')
        u_hod.save()
    assign_user_to_role(u_hod, 'Department Head')
    profile_hod, _ = DepartmentHeadProfile.objects.get_or_create(
        user=u_hod,
        defaults={
            'employee_id': 'DEMO-HOD-001',
            'status': 'active',
            'designation': 'Head of Computer Science',
            'department': dept_cs
        }
    )
    print("   ✅ User 'demo_hod' (Department Head) created/active.")

    # Faculty (demo_faculty)
    u_faculty, created = User.objects.get_or_create(
        username='demo_faculty',
        defaults={
            'email': 'faculty@demo.localhost',
            'first_name': 'Dr. Jane',
            'last_name': 'Doe',
            'is_active': True
        }
    )
    if created:
        u_faculty.set_password('admin123')
        u_faculty.save()
    assign_user_to_role(u_faculty, 'Faculty')
    profile_faculty, _ = TeachingStaffProfile.objects.get_or_create(
        user=u_faculty,
        defaults={
            'employee_id': 'DEMO-FAC-001',
            'status': 'active',
            'designation': 'Associate Professor',
            'department': dept_cs,
            'qualifications': 'Ph.D. in Computer Science',
            'experience_years': 8
        }
    )
    print("   ✅ User 'demo_faculty' (Faculty - CS) created/active.")

    # Faculty 2 (demo_faculty2)
    u_faculty2, created = User.objects.get_or_create(
        username='demo_faculty2',
        defaults={
            'email': 'faculty2@demo.localhost',
            'first_name': 'Prof. John',
            'last_name': 'Smith',
            'is_active': True
        }
    )
    if created:
        u_faculty2.set_password('admin123')
        u_faculty2.save()
    assign_user_to_role(u_faculty2, 'Faculty')
    profile_faculty2, _ = TeachingStaffProfile.objects.get_or_create(
        user=u_faculty2,
        defaults={
            'employee_id': 'DEMO-FAC-002',
            'status': 'active',
            'designation': 'Assistant Professor',
            'department': dept_it,
            'qualifications': 'M.Tech in Information Technology',
            'experience_years': 4
        }
    )
    print("   ✅ User 'demo_faculty2' (Faculty - IT) created/active.")

    # Support Staff (demo_support)
    u_support, created = User.objects.get_or_create(
        username='demo_support',
        defaults={
            'email': 'support@demo.localhost',
            'first_name': 'Sarah',
            'last_name': 'Connor',
            'is_active': True
        }
    )
    if created:
        u_support.set_password('admin123')
        u_support.save()
    assign_user_to_role(u_support, 'Support Staff')
    profile_support, _ = NonTeachingStaffProfile.objects.get_or_create(
        user=u_support,
        defaults={
            'employee_id': 'DEMO-SUP-001',
            'status': 'active',
            'designation': 'Librarian'
        }
    )
    print("   ✅ User 'demo_support' (Support Staff) created/active.")

    # Student 1 (demo_student)
    u_student, created = User.objects.get_or_create(
        username='demo_student',
        defaults={
            'email': 'student@demo.localhost',
            'first_name': 'Alice',
            'last_name': 'Johnson',
            'is_active': True
        }
    )
    if created:
        u_student.set_password('admin123')
        u_student.save()
    assign_user_to_role(u_student, 'student')
    profile_student, _ = StudentProfile.objects.get_or_create(
        user=u_student,
        defaults={
            'student_id': 'DEMO-STU-001',
            'status': 'active',
            'department': dept_cs,
            'program_enrolled_in': 'B.Tech CS',
            'is_face_registered': True,
            'locked_device_id': 'DEVICE_ALICE_123'
        }
    )
    print("   ✅ User 'demo_student' (Student - CS) created/active.")

    # Student 2 (demo_student2)
    u_student2, created = User.objects.get_or_create(
        username='demo_student2',
        defaults={
            'email': 'student2@demo.localhost',
            'first_name': 'Bob',
            'last_name': 'Wilson',
            'is_active': True
        }
    )
    if created:
        u_student2.set_password('admin123')
        u_student2.save()
    assign_user_to_role(u_student2, 'student')
    profile_student2, _ = StudentProfile.objects.get_or_create(
        user=u_student2,
        defaults={
            'student_id': 'DEMO-STU-002',
            'status': 'active',
            'department': dept_cs,
            'program_enrolled_in': 'B.Tech CS',
            'is_face_registered': True,
            'locked_device_id': 'DEVICE_BOB_456'
        }
    )
    print("   ✅ User 'demo_student2' (Student - CS) created/active.")

    # Student 3 (demo_student3)
    u_student3, created = User.objects.get_or_create(
        username='demo_student3',
        defaults={
            'email': 'student3@demo.localhost',
            'first_name': 'Charlie',
            'last_name': 'Brown',
            'is_active': True
        }
    )
    if created:
        u_student3.set_password('admin123')
        u_student3.save()
    assign_user_to_role(u_student3, 'student')
    profile_student3, _ = StudentProfile.objects.get_or_create(
        user=u_student3,
        defaults={
            'student_id': 'DEMO-STU-003',
            'status': 'active',
            'department': dept_it,
            'program_enrolled_in': 'B.Tech IT',
            'is_face_registered': True,
            'locked_device_id': 'DEVICE_CHARLIE_789'
        }
    )
    print("   ✅ User 'demo_student3' (Student - IT) created/active.")

    # D. Courses
    courses = [
        ('CS101', 'Data Structures & Algorithms', dept_cs),
        ('CS201', 'Database Management Systems', dept_cs),
        ('CS301', 'Operating Systems', dept_cs),
        ('IT101', 'Web Technologies', dept_it),
        ('IT201', 'Cloud Computing', dept_it),
    ]
    course_objs = {}
    for code, name, dept in courses:
        obj, created = Course.objects.get_or_create(
            course_code=code,
            defaults={'course_name': name, 'department': dept}
        )
        course_objs[code] = obj
        if created:
            print(f"   Created Course {code}: {name}")

    # E. Classrooms
    rooms = [
        ('Room 101', 'R101'),
        ('Room 102', 'R102'),
        ('Lab A', 'LABA'),
    ]
    room_objs = {}
    for name, code in rooms:
        obj, created = Classroom.objects.get_or_create(
            code=code,
            defaults={'name': name}
        )
        room_objs[code] = obj
        if created:
            print(f"   Created Classroom {code}: {name}")

    # F. Weekly Schedules
    timetable = [
        ('Monday', '09:00', '10:00', 'CS101', 'R101', u_faculty),
        ('Monday', '10:00', '11:00', 'CS201', 'R102', u_faculty),
        ('Tuesday', '09:00', '10:00', 'IT101', 'R101', u_faculty2),
        ('Tuesday', '14:00', '15:00', 'CS101', 'LABA', u_faculty),
        ('Wednesday', '09:00', '10:00', 'CS201', 'R101', u_faculty),
        ('Thursday', '11:00', '12:00', 'IT201', 'R102', u_faculty2),
    ]
    schedule_objs = []
    for day, s_str, e_str, ccode, rcode, fac in timetable:
        obj, created = Schedule.objects.get_or_create(
            course=course_objs[ccode],
            classroom=room_objs[rcode],
            day_of_week=day,
            start_time=time.fromisoformat(s_str),
            defaults={
                'faculty': fac,
                'end_time': time.fromisoformat(e_str),
                'semester': 'Semester 4',
                'academic_year': '2025-2026',
            }
        )
        schedule_objs.append(obj)
        if created:
            print(f"   Created Schedule: {day} {s_str}-{e_str} for {ccode}")

    # G. Lectures & Past Attendance
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    DAY_IDX = {d: i for i, d in enumerate(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])}

    import random
    import string
    
    lectures_created = 0
    attendances_created = 0
    
    for week_offset in [-1, 0]:
        week_monday = monday + timedelta(weeks=week_offset)
        for day, s_str, e_str, ccode, rcode, fac in timetable:
            lecture_date = week_monday + timedelta(days=DAY_IDX[day])
            # Only create lectures in the past or today
            if lecture_date > today:
                continue

            start_dt = datetime.datetime.combine(lecture_date, time.fromisoformat(s_str))
            end_dt = datetime.datetime.combine(lecture_date, time.fromisoformat(e_str))
            course = course_objs[ccode]
            room = room_objs[rcode]
            
            lecture_name = f"{course.course_name} Session"
            lec = Lecture.objects.filter(start_time=start_dt, classroom=room).first()
            if not lec:
                suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
                code_str = f"L{ccode[2:]}{lecture_date.strftime('%d%m')}{suffix}"
                lec = Lecture.objects.create(
                    name=lecture_name,
                    subject=course.course_name,
                    faculty=fac,
                    classroom=room,
                    start_time=start_dt,
                    end_time=end_dt,
                    code=code_str
                )
                lectures_created += 1

            # Match students by department
            student_profiles = []
            if course.department == dept_cs:
                student_profiles = [profile_student, profile_student2]
            elif course.department == dept_it:
                student_profiles = [profile_student3]

            for sp in student_profiles:
                # Mark attendance
                att, att_created = Attendance.objects.get_or_create(
                    user=sp.user,
                    lecture=lec,
                    defaults={
                        'check_in_time': start_dt + timedelta(minutes=random.randint(1, 10)),
                        'is_geofence_valid': True,
                        'device_id': sp.locked_device_id or 'DEVICE_MOCK_123',
                        'verification_method': 'face_geofence'
                    }
                )
                if att_created:
                    attendances_created += 1
                    
                # Create face log
                FaceAttendanceLog.objects.get_or_create(
                    student=sp,
                    lecture=lec,
                    defaults={
                        'confidence_score': round(random.uniform(0.75, 0.98), 2),
                        'is_verified': True,
                        'liveness_passed': True,
                        'timestamp': att.check_in_time
                    }
                )

    print(f"✅ Generated {lectures_created} Lectures and {attendances_created} Attendance Records.")

    # H. Active Attendance Sessions (for today)
    now = datetime.datetime.now()
    active_lectures = Lecture.objects.filter(start_time__lte=now, end_time__gte=now)
    for al in active_lectures:
        session, created = AttendanceSession.objects.get_or_create(
            lecture=al,
            defaults={
                'started_by': al.faculty,
                'duration_minutes': 60,
                'latitude': 12.9716,
                'longitude': 77.5946,
                'radius_meters': 100,
                'is_active': True
            }
        )
        if created:
            print(f"   Active session started for lecture: {al.name}")

    # I. Announcements
    Announcement.objects.get_or_create(
        title="Welcome to CampusFlow!",
        defaults={
            'content': "We are excited to launch the new smart attendance and campus ERP portal. Please ensure you register your face via the mobile app for seamless geofenced check-ins.",
            'author': u_admin,
            'priority': 'high',
            'is_pinned': True
        }
    )
    Announcement.objects.get_or_create(
        title="Midterm Examination Schedule",
        defaults={
            'content': "The midterm examinations for Semester 4 are scheduled to begin next week. The room allocation and detailed schedules are posted under the Exams tab.",
            'author': u_hod,
            'priority': 'urgent',
            'is_pinned': False
        }
    )
    print("✅ Created Announcements.")

    # J. Leave Types & Mock Requests
    lt_cl, _ = LeaveType.objects.get_or_create(
        code='CL',
        defaults={'name': 'Casual Leave', 'max_days': 12, 'is_paid': True}
    )
    lt_sl, _ = LeaveType.objects.get_or_create(
        code='SL',
        defaults={'name': 'Sick Leave', 'max_days': 10, 'is_paid': True}
    )
    
    LeaveBalance.objects.get_or_create(
        user=u_faculty,
        leave_type=lt_cl,
        academic_year='2025-2026',
        defaults={'allocated': 12, 'used': 2}
    )
    LeaveBalance.objects.get_or_create(
        user=u_faculty,
        leave_type=lt_sl,
        academic_year='2025-2026',
        defaults={'allocated': 10, 'used': 1}
    )
    
    LeaveRequest.objects.get_or_create(
        user=u_faculty,
        leave_type=lt_cl,
        start_date=today + timedelta(days=2),
        end_date=today + timedelta(days=3),
        defaults={
            'reason': 'Attending a Research Conference on Machine Learning.',
            'status': 'pending'
        }
    )
    print("✅ Created Leave Request workflow.")

    # K. Exams
    et_mid, _ = ExamType.objects.get_or_create(code='MID', defaults={'name': 'Mid-Term Exam'})
    et_end, _ = ExamType.objects.get_or_create(code='END', defaults={'name': 'End Semester Exam'})
    
    Exam.objects.get_or_create(
        name="Data Structures Midterm",
        exam_type=et_mid,
        course=course_objs['CS101'],
        defaults={
            'department': dept_cs,
            'date': today + timedelta(days=5),
            'start_time': time(10, 0),
            'end_time': time(12, 0),
            'classroom': room_objs['R101'],
            'total_marks': 50,
            'passing_marks': 18,
            'semester': 'Semester 4',
            'academic_year': '2025-2026',
            'invigilator': u_faculty2,
            'created_by': u_hod,
            'status': 'scheduled'
        }
    )
    print("✅ Created Exams.")

    # L. Assignments & Submissions
    assignment_cs101, _ = Assignment.objects.get_or_create(
        title="Assignment 1: Stack & Queue Implementations",
        course=course_objs['CS101'],
        defaults={
            'description': "Implement Stack and Queue using arrays and linked lists in Python. Submit code files.",
            'department': dept_cs,
            'due_date': now + timedelta(days=3),
            'created_by': u_faculty
        }
    )
    
    AssignmentSubmission.objects.get_or_create(
        assignment=assignment_cs101,
        student=u_student,
        defaults={
            'text_submission': "Implemented all required classes and tests. Code uploaded.",
            'grade': 'A',
            'feedback': 'Excellent implementation and clean code.',
            'status': 'graded'
        }
    )
    
    AssignmentSubmission.objects.get_or_create(
        assignment=assignment_cs101,
        student=u_student2,
        defaults={
            'text_submission': "Submitted the code, waiting for review.",
            'status': 'submitted'
        }
    )
    print("✅ Created Assignments & Submissions.")

    print("\n" + "="*60)
    print("DEMO SEEDING COMPLETE FOR TENANT 'demo'!")
    print("="*60)
    print(f"Admin User      : demo_admin   / admin123")
    print(f"HOD User        : demo_hod     / admin123")
    print(f"Faculty User    : demo_faculty / admin123")
    print(f"Student User    : demo_student / admin123")
    print("="*60)

"""
CampusFlow Demo Data Seeder
==========================
Creates the 'demo' tenant and seeds it with rich, premium, and comprehensive
demo data including:
  - 'demo' Tenant (College) & domains (demo.localhost & staging domain)
  - All standard Groups (student, Faculty, Support Staff, Management,
    Administrator, Department Head)
  - 12 Departments (CS, IT, ME, EE, CE, ECE, CHE, BIO, AERO, AI, DS, CY)
  - ~2,400 Students (~200 per department) with complete StudentProfiles
  - 120 Faculty members (10 per department) + HODs for each department
  - Courses, Classrooms, Schedules, and Timetables
  - Simulated past attendance logs + active attendance sessions for today
  - Announcements, Exams, Assignments & Submissions, and Leaves.

Run with:
  python manage.py shell < seed_demo_data.py
    OR
  python seed_demo_data.py
"""

import datetime
from datetime import date, time, timedelta
import os
import random
import string
import sys

# Ensure UTF-8 output handling on Windows terminals
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

import django

# Set up django if run as standalone script
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
    django.setup()

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group, Permission, User
from django.contrib.contenttypes.models import ContentType
from django_tenants.utils import schema_context
from tenants.models import Domain, Tenant


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

active_email_domain = (
    f"demo.{public_domain_name}"
    if public_domain_name != 'localhost'
    else 'demo.localhost'
)

# ── 1. Create/Get Tenant ──────────────────────────────────────────────────────
tenant = Tenant.objects.filter(schema_name=SCHEMA).first()
if not tenant:
    print(f"Creating tenant '{SCHEMA}'...")
    tenant = Tenant.objects.create(
        schema_name=SCHEMA,
        name=TENANT_NAME,
        code=TENANT_CODE,
        address="123 Education Lane, Demo City",
        contact_email=f"admin@{active_email_domain}",
        permitted_email_domain=active_email_domain,
        timezone="Asia/Kolkata"
    )
    print(f"✅ Tenant '{SCHEMA}' created successfully.")
else:
    print(f"✅ Tenant '{SCHEMA}' already exists.")
    if tenant.permitted_email_domain != active_email_domain:
        print(f"   Updating permitted_email_domain: '{tenant.permitted_email_domain}' -> '{active_email_domain}'")
        tenant.permitted_email_domain = active_email_domain
        tenant.save(update_fields=['permitted_email_domain'])

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
    from campusflow_app.models import (
        AdministratorProfile,
        Announcement,
        Assignment,
        AssignmentSubmission,
        Attendance,
        AttendanceSession,
        Classroom,
        Course,
        Department,
        DepartmentHeadProfile,
        Exam,
        ExamType,
        FaceAttendanceLog,
        LeaveBalance,
        LeaveRequest,
        LeaveType,
        Lecture,
        ManagementProfile,
        NonTeachingStaffProfile,
        Schedule,
        StudentProfile,
        TeachingStaffProfile,
    )

    # Idempotency check: Skip if already fully seeded (~2,400 students across 12 departments)
    existing_students = StudentProfile.objects.count()
    existing_depts = Department.objects.filter(status='Active').count()
    if existing_students >= 2400 and existing_depts >= 12:
        print(f"✅ Tenant '{SCHEMA}' already fully seeded ({existing_students} students, {existing_depts} departments). Skipping.")
        sys.exit(0)

    print(f"   Current status: {existing_students} students, {existing_depts} departments. Proceeding with seeding...")

    # A. Role Groups
    roles = ['student', 'Faculty', 'Support Staff', 'Management', 'Administrator', 'Department Head']
    group_map = {}
    for role_name in roles:
        grp, created = Group.objects.get_or_create(name=role_name)
        group_map[role_name] = grp
        if created:
            print(f"   Created group '{role_name}'")

    def assign_user_to_role(user_obj, rname):
        user_obj.groups.clear()
        user_obj.groups.add(group_map[rname])
        group_permissions_codenames = group_map[rname].permissions.values_list('codename', flat=True)
        user_obj.user_permissions.set(Permission.objects.filter(codename__in=group_permissions_codenames))
        user_obj.save()

    # B. 12 Departments
    DEPARTMENTS_INFO = [
        ('CS', 'Computer Science & Engineering'),
        ('IT', 'Information Technology'),
        ('ME', 'Mechanical Engineering'),
        ('EE', 'Electrical Engineering'),
        ('CE', 'Civil Engineering'),
        ('ECE', 'Electronics & Communication Engineering'),
        ('CHE', 'Chemical Engineering'),
        ('BIO', 'Biotechnology & Bioengineering'),
        ('AERO', 'Aerospace Engineering'),
        ('AI', 'Artificial Intelligence & Machine Learning'),
        ('DS', 'Data Science & Analytics'),
        ('CY', 'Cyber Security & Forensic Science'),
    ]

    dept_objs = {}
    for code, name in DEPARTMENTS_INFO:
        dept, _ = Department.objects.get_or_create(
            code=code,
            defaults={'name': name, 'status': 'Active'}
        )
        dept_objs[code] = dept
    print(f"✅ Synced {len(dept_objs)} Departments.")

    dept_cs = dept_objs['CS']
    dept_it = dept_objs['IT']
    dept_me = dept_objs['ME']

    # C. Standard Core Users & Profiles
    u_admin, created = User.objects.get_or_create(
        username='demo_admin',
        defaults={
            'email': f'admin@{active_email_domain}',
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
    AdministratorProfile.objects.get_or_create(
        user=u_admin,
        defaults={
            'employee_id': 'DEMO-ADM-001',
            'status': 'active',
            'designation': 'System Administrator'
        }
    )

    u_mgmt, created = User.objects.get_or_create(
        username='demo_mgmt',
        defaults={
            'email': f'mgmt@{active_email_domain}',
            'first_name': 'Demo',
            'last_name': 'Director',
            'is_active': True
        }
    )
    if created:
        u_mgmt.set_password('admin123')
        u_mgmt.save()
    assign_user_to_role(u_mgmt, 'Management')
    ManagementProfile.objects.get_or_create(
        user=u_mgmt,
        defaults={
            'employee_id': 'DEMO-MGT-001',
            'status': 'active',
            'designation': 'College Director'
        }
    )

    u_hod, created = User.objects.get_or_create(
        username='demo_hod',
        defaults={
            'email': f'hod@{active_email_domain}',
            'first_name': 'Dr. Robert',
            'last_name': 'Vance',
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
    if dept_cs.hod != u_hod:
        dept_cs.hod = u_hod
        dept_cs.save(update_fields=['hod'])

    # HODs for remaining 11 departments
    hashed_default_pw = make_password('admin123')
    for code, dept in dept_objs.items():
        if code == 'CS':
            continue
        username = f"hod_{code.lower()}"
        hod_user, created_h = User.objects.get_or_create(
            username=username,
            defaults={
                'email': f"hod_{code.lower()}@{active_email_domain}",
                'first_name': f'Head Of',
                'last_name': f'{code} Dept',
                'password': hashed_default_pw,
                'is_active': True
            }
        )
        if created_h:
            assign_user_to_role(hod_user, 'Department Head')
        DepartmentHeadProfile.objects.get_or_create(
            user=hod_user,
            defaults={
                'employee_id': f'DEMO-HOD-{code}',
                'status': 'active',
                'designation': f'Head of {dept.name}',
                'department': dept
            }
        )
        if dept.hod != hod_user:
            dept.hod = hod_user
            dept.save(update_fields=['hod'])

    u_faculty, created = User.objects.get_or_create(
        username='demo_faculty',
        defaults={
            'email': f'faculty@{active_email_domain}',
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

    u_faculty2, created = User.objects.get_or_create(
        username='demo_faculty2',
        defaults={
            'email': f'faculty2@{active_email_domain}',
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

    u_support, created = User.objects.get_or_create(
        username='demo_support',
        defaults={
            'email': f'support@{active_email_domain}',
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

    # Core demo student users
    u_student, created = User.objects.get_or_create(
        username='demo_student',
        defaults={
            'email': f'student@{active_email_domain}',
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
            'program_enrolled_in': 'B.Tech Computer Science & Engineering',
            'batch_academic_year': '2024-2025',
            'current_semester_year': 'Semester 4',
            'section_division': 'A',
            'is_face_registered': True,
            'locked_device_id': 'DEVICE_ALICE_123'
        }
    )

    u_student2, created = User.objects.get_or_create(
        username='demo_student2',
        defaults={
            'email': f'student2@{active_email_domain}',
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
            'program_enrolled_in': 'B.Tech Computer Science & Engineering',
            'batch_academic_year': '2024-2025',
            'current_semester_year': 'Semester 4',
            'section_division': 'B',
            'is_face_registered': True,
            'locked_device_id': 'DEVICE_BOB_456'
        }
    )

    u_student3, created = User.objects.get_or_create(
        username='demo_student3',
        defaults={
            'email': f'student3@{active_email_domain}',
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
            'program_enrolled_in': 'B.Tech Information Technology',
            'batch_academic_year': '2024-2025',
            'current_semester_year': 'Semester 4',
            'section_division': 'A',
            'is_face_registered': True,
            'locked_device_id': 'DEVICE_CHARLIE_789'
        }
    )
    print("✅ Created core demo users (admin, mgmt, hods, faculty, students).")

    # D. Courses for all 12 Departments
    COURSES_DATA = {
        'CS': [
            ('CS101', 'Data Structures & Algorithms'),
            ('CS201', 'Database Management Systems'),
            ('CS301', 'Operating Systems'),
            ('CS401', 'Computer Networks'),
            ('CS501', 'Software Engineering'),
        ],
        'IT': [
            ('IT101', 'Web Technologies'),
            ('IT201', 'Cloud Computing'),
            ('IT301', 'Information Security'),
            ('IT401', 'Mobile App Development'),
        ],
        'ME': [
            ('ME101', 'Thermodynamics'),
            ('ME201', 'Fluid Mechanics'),
            ('ME301', 'Machine Design'),
            ('ME401', 'Manufacturing Processes'),
        ],
        'EE': [
            ('EE101', 'Basic Electrical Engineering'),
            ('EE201', 'Circuit Theory'),
            ('EE301', 'Power Systems Analysis'),
            ('EE401', 'Control Systems'),
        ],
        'CE': [
            ('CE101', 'Engineering Mechanics'),
            ('CE201', 'Surveying & Geomatics'),
            ('CE301', 'Structural Analysis'),
            ('CE401', 'Geotechnical Engineering'),
        ],
        'ECE': [
            ('ECE101', 'Analog Electronics'),
            ('ECE201', 'Digital Signal Processing'),
            ('ECE301', 'Microprocessors & Microcontrollers'),
            ('ECE401', 'Wireless Communications'),
        ],
        'CHE': [
            ('CHE101', 'Chemical Process Calculations'),
            ('CHE201', 'Heat Transfer Operations'),
            ('CHE301', 'Mass Transfer Operations'),
            ('CHE401', 'Chemical Reaction Engineering'),
        ],
        'BIO': [
            ('BIO101', 'Cell Biology & Genetics'),
            ('BIO201', 'Biochemistry'),
            ('BIO301', 'Bioprocess Engineering'),
            ('BIO401', 'Bioinformatics'),
        ],
        'AERO': [
            ('AERO101', 'Introduction to Flight Mechanics'),
            ('AERO201', 'Aerodynamics'),
            ('AERO301', 'Rocket Propulsion'),
            ('AERO401', 'Aircraft Structures'),
        ],
        'AI': [
            ('AI101', 'Introduction to Artificial Intelligence'),
            ('AI201', 'Machine Learning Foundations'),
            ('AI301', 'Deep Learning & Neural Networks'),
            ('AI401', 'Computer Vision & NLP'),
        ],
        'DS': [
            ('DS101', 'Statistical Methods for Data Science'),
            ('DS201', 'Big Data Analytics'),
            ('DS301', 'Data Visualization & Wrangling'),
            ('DS401', 'Predictive Modeling'),
        ],
        'CY': [
            ('CY101', 'Introduction to Cybersecurity'),
            ('CY201', 'Ethical Hacking & Penetration Testing'),
            ('CY301', 'Digital Forensics'),
            ('CY401', 'Applied Cryptography'),
        ],
    }

    course_objs = {}
    courses_by_dept = {}
    for code, dept in dept_objs.items():
        courses_by_dept[code] = []
        c_list = COURSES_DATA.get(code, [])
        for ccode, cname in c_list:
            obj, _ = Course.objects.get_or_create(
                course_code=ccode,
                defaults={'course_name': cname, 'department': dept}
            )
            course_objs[ccode] = obj
            courses_by_dept[code].append(obj)
    print(f"✅ Synced {len(course_objs)} Courses across 12 departments.")

    # E. Bulk Seed ~2,400 Students and 120 Faculty
    target_total_students = 2400
    target_faculty_per_dept = 10

    FIRST_NAMES = [
        'Aarav', 'Vihaan', 'Aditya', 'Sai', 'Arjun', 'Aryan', 'Reyansh', 'Krishna', 'Ishaan', 'Shaurya',
        'Ananya', 'Diya', 'Pari', 'Pihu', 'Ira', 'Avani', 'Riya', 'Kavya', 'Saanvi', 'Kiara',
        'Amit', 'Rahul', 'Sneha', 'Priya', 'Rohan', 'Neha', 'Abhishek', 'Pooja', 'Vikram', 'Divya',
        'Deepak', 'Jyoti', 'Sanjay', 'Kiran', 'Rajesh', 'Sunita', 'Aniket', 'Aishwarya', 'Vijay', 'Shalini'
    ]
    LAST_NAMES = [
        'Sharma', 'Verma', 'Gupta', 'Patel', 'Joshi', 'Mehra', 'Singh', 'Kumar', 'Choudhary', 'Deshmukh',
        'Kulkarni', 'Nair', 'Pillai', 'Rao', 'Reddy', 'Grover', 'Kapoor', 'Malhotra', 'Sen', 'Banerjee',
        'Chatterjee', 'Das', 'Roy', 'Mishra', 'Trivedi', 'Yadav', 'Prasad', 'Bose', 'Mukherjee'
    ]

    bulk_user_password = make_password('Password123')

    # Seed Faculty across departments
    print("   Bulk generating Faculty users and profiles...")
    fac_users_to_create = []
    fac_metadata = []

    for code, dept in dept_objs.items():
        for f_idx in range(target_faculty_per_dept):
            username = f"fac_{code.lower()}_{f_idx+1:02d}"
            if not User.objects.filter(username=username).exists():
                fn = random.choice(FIRST_NAMES)
                ln = random.choice(LAST_NAMES)
                user_obj = User(
                    username=username,
                    email=f"{username}@{active_email_domain}",
                    password=bulk_user_password,
                    first_name=fn,
                    last_name=ln,
                    is_active=True
                )
                fac_users_to_create.append(user_obj)
                fac_metadata.append((username, dept, f"FAC-{code}-{f_idx+1:03d}"))

    if fac_users_to_create:
        created_fac_users = User.objects.bulk_create(fac_users_to_create, batch_size=500)
        fac_user_map = {u.username: u for u in created_fac_users}

        faculty_group = group_map['Faculty']
        fac_group_relations = [
            User.groups.through(user_id=u.id, group_id=faculty_group.id)
            for u in created_fac_users
        ]
        User.groups.through.objects.bulk_create(fac_group_relations, batch_size=500)

        fac_profiles = [
            TeachingStaffProfile(
                user=fac_user_map[uname],
                employee_id=emp_id,
                department=dept,
                designation=random.choice(['Assistant Professor', 'Associate Professor', 'Professor']),
                staff_role="lecturer",
                status="active"
            )
            for uname, dept, emp_id in fac_metadata
        ]
        TeachingStaffProfile.objects.bulk_create(fac_profiles, batch_size=500)
        print(f"   ✅ Created {len(fac_profiles)} Faculty profiles.")

    # Seed ~2,400 Students (~200 per department)
    needed_students = target_total_students - StudentProfile.objects.count()
    if needed_students > 0:
        print(f"   Bulk generating {needed_students} Student users and profiles...")
        students_per_dept = max(1, needed_students // len(dept_objs))

        stu_users_to_create = []
        stu_metadata = []
        stu_global_idx = StudentProfile.objects.count() + 1

        semesters = ['Semester 1', 'Semester 2', 'Semester 3', 'Semester 4', 'Semester 5', 'Semester 6', 'Semester 7', 'Semester 8']
        batches = ['2022-2026', '2023-2027', '2024-2028', '2025-2029']

        for code, dept in dept_objs.items():
            dept_courses = courses_by_dept[code]
            for _ in range(students_per_dept):
                username = f"stu_{stu_global_idx:05d}"
                fn = random.choice(FIRST_NAMES)
                ln = random.choice(LAST_NAMES)
                user_obj = User(
                    username=username,
                    email=f"student_{stu_global_idx:05d}@{active_email_domain}",
                    password=bulk_user_password,
                    first_name=fn,
                    last_name=ln,
                    is_active=True
                )
                stu_users_to_create.append(user_obj)
                
                program_name = f"B.Tech {dept.name}"
                stu_id = f"STU-{code}-{stu_global_idx:05d}"
                aadhaar = f"9{stu_global_idx:011d}"
                biometric = f"BIO-{code}-{stu_global_idx:05d}"
                
                stu_metadata.append((
                    username,
                    dept,
                    program_name,
                    random.choice(batches),
                    random.choice(semesters),
                    stu_id,
                    aadhaar,
                    biometric
                ))
                stu_global_idx += 1

        if stu_users_to_create:
            created_stu_users = User.objects.bulk_create(stu_users_to_create, batch_size=1000)
            stu_user_map = {u.username: u for u in created_stu_users}

            student_group = group_map['student']
            stu_group_relations = [
                User.groups.through(user_id=u.id, group_id=student_group.id)
                for u in created_stu_users
            ]
            User.groups.through.objects.bulk_create(stu_group_relations, batch_size=1000)

            stu_profiles = [
                StudentProfile(
                    user=stu_user_map[uname],
                    student_id=s_id,
                    department=dept,
                    program_enrolled_in=prog,
                    batch_academic_year=batch,
                    current_semester_year=sem,
                    status="active",
                    aadhaar_number=aadhaar,
                    biometric_id=biometric,
                    is_face_registered=True
                )
                for uname, dept, prog, batch, sem, s_id, aadhaar, biometric in stu_metadata
            ]
            StudentProfile.objects.bulk_create(stu_profiles, batch_size=1000)
            print(f"   ✅ Created {len(stu_profiles)} Student profiles.")

    print(f"✅ Total Students in schema '{SCHEMA}': {StudentProfile.objects.count()}")

    # F. Classrooms
    rooms = [
        ('Room 101', 'R101'),
        ('Room 102', 'R102'),
        ('Room 201', 'R201'),
        ('Room 202', 'R202'),
        ('Lab A', 'LABA'),
        ('Lab B', 'LABB'),
        ('Auditorium Main', 'AUD1'),
    ]
    room_objs = {}
    for name, code in rooms:
        obj, _ = Classroom.objects.get_or_create(
            code=code,
            defaults={'name': name}
        )
        room_objs[code] = obj
    print(f"✅ Classrooms synced ({len(room_objs)} rooms).")

    # G. Timetable & Schedules
    timetable = [
        ('Monday', '09:00', '10:00', 'CS101', 'R101', u_faculty),
        ('Monday', '10:00', '11:00', 'CS201', 'R102', u_faculty),
        ('Tuesday', '09:00', '10:00', 'IT101', 'R101', u_faculty2),
        ('Tuesday', '14:00', '15:00', 'CS101', 'LABA', u_faculty),
        ('Wednesday', '09:00', '10:00', 'CS201', 'R101', u_faculty),
        ('Thursday', '11:00', '12:00', 'IT201', 'R102', u_faculty2),
        ('Friday', '10:00', '11:00', 'ME101', 'R201', u_faculty),
    ]

    schedule_objs = []
    for day, s_str, e_str, ccode, rcode, fac in timetable:
        if ccode in course_objs and rcode in room_objs:
            obj, _ = Schedule.objects.get_or_create(
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
    print(f"✅ Schedules synced ({len(schedule_objs)} schedule items).")

    # H. Past Lectures & Attendance Logs
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    DAY_IDX = {d: i for i, d in enumerate(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])}

    lectures_created = 0
    attendances_created = 0

    for week_offset in [-1, 0]:
        week_monday = monday + timedelta(weeks=week_offset)
        for day, s_str, e_str, ccode, rcode, fac in timetable:
            if ccode not in course_objs or rcode not in room_objs:
                continue

            lecture_date = week_monday + timedelta(days=DAY_IDX[day])
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

            student_profiles = [profile_student, profile_student2, profile_student3]
            for sp in student_profiles:
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

    # I. Active Attendance Sessions for Today
    now = datetime.datetime.now()
    active_lectures = Lecture.objects.filter(start_time__lte=now, end_time__gte=now)
    for al in active_lectures:
        session, created_sess = AttendanceSession.objects.get_or_create(
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
        if created_sess:
            print(f"   Active session started for lecture: {al.name}")

    # J. Announcements
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

    # K. Leave Types & Mock Requests
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

    # L. Exams & Assignments
    et_mid, _ = ExamType.objects.get_or_create(code='MID', defaults={'name': 'Mid-Term Exam'})
    
    if 'CS101' in course_objs and 'R101' in room_objs:
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

    if 'CS101' in course_objs:
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

    print("\n" + "=" * 60)
    print("DEMO SEEDING COMPLETE FOR TENANT 'demo'!")
    print(f"Total Departments : {Department.objects.filter(status='Active').count()}")
    print(f"Total Students    : {StudentProfile.objects.count()}")
    print(f"Total Faculty     : {TeachingStaffProfile.objects.count()}")
    print("=" * 60)
    print("Admin User      : demo_admin   / admin123")
    print("HOD User        : demo_hod     / admin123")
    print("Faculty User    : demo_faculty / admin123")
    print("Student User    : demo_student / admin123")
    print("=" * 60)

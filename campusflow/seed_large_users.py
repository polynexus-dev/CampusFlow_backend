import os
import sys
import django
import random
import argparse

# Set up django if run as standalone script
if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
    django.setup()

from django_tenants.utils import schema_context
from django.contrib.auth.models import User, Group
from django.contrib.auth.hashers import make_password

from campusflow_app.models.department import Department
from campusflow_app.models.course import Course
from campusflow_app.models.profile import (
    StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile
)

# Parse args or set defaults
schema = 'demo'
count = 5000

if __name__ == "__main__":
    # Bypassed if executed via python manage.py shell
    if len(sys.argv) > 1 and "manage.py" not in sys.argv[0] and "shell" not in sys.argv:
        parser = argparse.ArgumentParser(description="Seed large number of users.")
        parser.add_argument("--schema", default="demo", help="Tenant schema to seed")
        parser.add_argument("--count", type=int, default=5000, help="Number of users to seed")
        args = parser.parse_args()
        schema = args.schema
        count = args.count

print(f"Target Schema: {schema}")
print(f"Target Count : {count} users")

with schema_context(schema):
    # 1. Ensure groups/roles exist
    roles = ['student', 'Faculty', 'Support Staff']
    group_map = {}
    for role_name in roles:
        group, created = Group.objects.get_or_create(name=role_name)
        group_map[role_name] = group
        if created:
            print(f"Created Group Role: {role_name}")

    # 2. Ensure Departments (Branches) exist
    DEPARTMENTS_DATA = [
        ('CS', 'Computer Science'),
        ('IT', 'Information Technology'),
        ('ME', 'Mechanical Engineering'),
        ('EE', 'Electrical Engineering'),
        ('CE', 'Civil Engineering'),
    ]
    departments = []
    for code, name in DEPARTMENTS_DATA:
        dept, created = Department.objects.get_or_create(
            code=code,
            defaults={'name': name, 'status': 'Active'}
        )
        departments.append(dept)
        if created:
            print(f"Created Department: {name} ({code})")

    # 3. Ensure Courses exist for each department
    COURSES_DATA = {
        'CS': [
            ('CS101', 'Data Structures & Algorithms'),
            ('CS201', 'Database Management Systems'),
            ('CS301', 'Operating Systems'),
            ('CS401', 'Computer Networks'),
            ('CS501', 'Software Engineering'),
        ],
        'IT': [
            ('IT101', 'Introduction to Information Technology'),
            ('IT201', 'Web Technologies'),
            ('IT301', 'Cloud Computing Concepts'),
            ('IT401', 'Information Security'),
            ('IT501', 'Mobile Applications Development'),
        ],
        'ME': [
            ('ME101', 'Thermodynamics'),
            ('ME201', 'Fluid Mechanics'),
            ('ME301', 'Machine Design'),
            ('ME401', 'Manufacturing Processes'),
            ('ME501', 'CAD/CAM Systems'),
        ],
        'EE': [
            ('EE101', 'Basic Electrical Engineering'),
            ('EE201', 'Circuit Theory'),
            ('EE301', 'Power Systems Analysis'),
            ('EE401', 'Control Systems'),
            ('EE501', 'Electrical Machines'),
        ],
        'CE': [
            ('CE101', 'Engineering Mechanics'),
            ('CE201', 'Surveying & Geomatics'),
            ('CE301', 'Structural Analysis'),
            ('CE401', 'Geotechnical Engineering'),
            ('CE501', 'Environmental Engineering'),
        ]
    }
    
    courses_by_dept = {}
    for dept in departments:
        courses_by_dept[dept.code] = []
        code_list = COURSES_DATA.get(dept.code, [])
        for ccode, cname in code_list:
            course, created = Course.objects.get_or_create(
                course_code=ccode,
                defaults={'course_name': cname, 'department': dept}
            )
            courses_by_dept[dept.code].append(course)
            if created:
                print(f"Created Course: {cname} ({ccode})")

    # 4. User generation parameters
    # Students: ~80%
    # Faculty: ~16%
    # Drivers: ~2%
    # Conductors: ~2%
    num_students = int(count * 0.80)
    num_faculty = int(count * 0.16)
    num_drivers = int(count * 0.02)
    num_conductors = count - (num_students + num_faculty + num_drivers) # Ensure total equals count exactly

    print(f"\nUser Distribution:")
    print(f"  - Students  : {num_students}")
    print(f"  - Faculty   : {num_faculty}")
    print(f"  - Drivers   : {num_drivers}")
    print(f"  - Conductors: {num_conductors}")
    print(f"  - Total     : {count}")

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

    print("\nHashing password...")
    hashed_password = make_password('Password123')
    
    # Helper to calculate start index based on existing usernames in the system
    def get_next_index(prefix):
        usernames = User.objects.filter(username__startswith=prefix).values_list('username', flat=True)
        max_idx = 0
        for username in usernames:
            try:
                # e.g. "stu_00123" -> 123
                idx = int(username.split('_')[-1])
                if idx > max_idx:
                    max_idx = idx
            except (ValueError, IndexError):
                pass
        return max_idx + 1

    start_stu_idx = get_next_index('stu_')
    start_fac_idx = get_next_index('fac_')
    start_drv_idx = get_next_index('drv_')
    start_cnd_idx = get_next_index('cnd_')

    print(f"\nStarting indices for bulk generation:")
    print(f"  - Student start index: {start_stu_idx}")
    print(f"  - Faculty start index: {start_fac_idx}")
    print(f"  - Driver start index : {start_drv_idx}")
    print(f"  - Conductor start index: {start_cnd_idx}")

    # Helpers to ensure unique Aadhaar numbers (12-digit string)
    def make_aadhaar(prefix_digit, num):
        return f"{prefix_digit}{num:011d}"

    # Generate Student lists
    student_users = []
    for idx in range(start_stu_idx, start_stu_idx + num_students):
        fname = random.choice(FIRST_NAMES)
        lname = random.choice(LAST_NAMES)
        username = f"stu_{idx:05d}"
        email = f"student_{idx:05d}@{schema}.edu"
        student_users.append(User(
            username=username,
            email=email,
            password=hashed_password,
            first_name=fname,
            last_name=lname,
            is_active=True
        ))

    # Generate Faculty lists
    faculty_users = []
    for idx in range(start_fac_idx, start_fac_idx + num_faculty):
        fname = random.choice(FIRST_NAMES)
        lname = random.choice(LAST_NAMES)
        username = f"fac_{idx:05d}"
        email = f"faculty_{idx:05d}@{schema}.edu"
        faculty_users.append(User(
            username=username,
            email=email,
            password=hashed_password,
            first_name=fname,
            last_name=lname,
            is_active=True
        ))

    # Generate Driver lists
    driver_users = []
    for idx in range(start_drv_idx, start_drv_idx + num_drivers):
        fname = random.choice(FIRST_NAMES)
        lname = random.choice(LAST_NAMES)
        username = f"drv_{idx:05d}"
        email = f"driver_{idx:05d}@{schema}.edu"
        driver_users.append(User(
            username=username,
            email=email,
            password=hashed_password,
            first_name=fname,
            last_name=lname,
            is_active=True
        ))

    # Generate Conductor lists
    conductor_users = []
    for idx in range(start_cnd_idx, start_cnd_idx + num_conductors):
        fname = random.choice(FIRST_NAMES)
        lname = random.choice(LAST_NAMES)
        username = f"cnd_{idx:05d}"
        email = f"conductor_{idx:05d}@{schema}.edu"
        conductor_users.append(User(
            username=username,
            email=email,
            password=hashed_password,
            first_name=fname,
            last_name=lname,
            is_active=True
        ))

    # 5. Bulk Create Users
    print("\nBulk creating Users in database...")
    all_users_to_create = student_users + faculty_users + driver_users + conductor_users
    
    created_users = []
    batch_size = 2000
    for i in range(0, len(all_users_to_create), batch_size):
        chunk = all_users_to_create[i:i+batch_size]
        res = User.objects.bulk_create(chunk)
        created_users.extend(res)
        print(f"  Created {len(created_users)} / {len(all_users_to_create)} users...")

    # Build maps of created users by username
    user_map = {u.username: u for u in created_users}

    # 6. Bulk Associate Users to Groups (Roles)
    print("\nCreating Group (Role) associations...")
    group_relations = []
    
    student_group = group_map['student']
    faculty_group = group_map['Faculty']
    support_group = group_map['Support Staff']

    for u in created_users:
        if u.username.startswith('stu_'):
            group_relations.append(User.groups.through(user_id=u.id, group_id=student_group.id))
        elif u.username.startswith('fac_'):
            group_relations.append(User.groups.through(user_id=u.id, group_id=faculty_group.id))
        elif u.username.startswith('drv_') or u.username.startswith('cnd_'):
            group_relations.append(User.groups.through(user_id=u.id, group_id=support_group.id))

    for i in range(0, len(group_relations), batch_size):
        User.groups.through.objects.bulk_create(group_relations[i:i+batch_size])
    print(f"  [OK] Linked all {len(group_relations)} users to role groups.")

    # 7. Bulk Create Profiles
    print("\nPreparing Profiles...")

    # Prepare Student Profiles
    student_profiles = []
    for idx, user_obj in enumerate(student_users):
        u = user_map[user_obj.username]
        # Pick random department and random course of that department
        dept = random.choice(departments)
        course = random.choice(courses_by_dept[dept.code])
        
        # Real unique identifiers
        u_num = int(u.username.split('_')[-1])
        s_id = f"STU-{u_num:05d}-{schema.upper()}"
        aadhaar = make_aadhaar(9, u_num)
        biometric = f"BIO-STU-{u_num:05d}"

        student_profiles.append(StudentProfile(
            user=u,
            student_id=s_id,
            department=dept,
            program_enrolled_in=course.course_name,
            batch_academic_year="2025-2029",
            current_semester_year="Semester 3",
            status="active",
            aadhaar_number=aadhaar,
            biometric_id=biometric
        ))

    # Prepare Faculty Profiles
    faculty_profiles = []
    designations = ['Assistant Professor', 'Associate Professor', 'Professor']
    for idx, user_obj in enumerate(faculty_users):
        u = user_map[user_obj.username]
        dept = random.choice(departments)
        
        u_num = int(u.username.split('_')[-1])
        f_id = f"FAC-{u_num:05d}-{schema.upper()}"
        aadhaar = make_aadhaar(8, u_num)
        pan = f"FACPA{u_num:05d}"

        faculty_profiles.append(TeachingStaffProfile(
            user=u,
            employee_id=f_id,
            department=dept,
            designation=random.choice(designations),
            staff_role="lecturer",
            status="active",
            aadhaar_number=aadhaar,
            pan_number=pan
        ))

    # Prepare Driver Profiles
    driver_profiles = []
    for idx, user_obj in enumerate(driver_users):
        u = user_map[user_obj.username]
        
        u_num = int(u.username.split('_')[-1])
        d_id = f"DRV-{u_num:05d}-{schema.upper()}"
        aadhaar = make_aadhaar(7, u_num)
        pan = f"DRVPA{u_num:05d}"

        driver_profiles.append(NonTeachingStaffProfile(
            user=u,
            employee_id=d_id,
            designation="Bus Driver",
            staff_role="driver",
            status="active",
            aadhaar_number=aadhaar,
            pan_number=pan
        ))

    # Prepare Conductor Profiles
    conductor_profiles = []
    for idx, user_obj in enumerate(conductor_users):
        u = user_map[user_obj.username]
        
        u_num = int(u.username.split('_')[-1])
        c_id = f"CND-{u_num:05d}-{schema.upper()}"
        aadhaar = make_aadhaar(6, u_num)
        pan = f"CNDPA{u_num:05d}"

        conductor_profiles.append(NonTeachingStaffProfile(
            user=u,
            employee_id=c_id,
            designation="Bus Conductor",
            staff_role="conductor",
            status="active",
            aadhaar_number=aadhaar,
            pan_number=pan
        ))

    # Save Profiles in bulk
    print("Writing profiles to database...")
    for i in range(0, len(student_profiles), batch_size):
        StudentProfile.objects.bulk_create(student_profiles[i:i+batch_size])
    print(f"  [OK] Created {len(student_profiles)} Student profiles.")

    for i in range(0, len(faculty_profiles), batch_size):
        TeachingStaffProfile.objects.bulk_create(faculty_profiles[i:i+batch_size])
    print(f"  [OK] Created {len(faculty_profiles)} Faculty profiles.")

    all_non_teaching = driver_profiles + conductor_profiles
    for i in range(0, len(all_non_teaching), batch_size):
        NonTeachingStaffProfile.objects.bulk_create(all_non_teaching[i:i+batch_size])
    print(f"  [OK] Created {len(all_non_teaching)} Support Staff profiles (Drivers & Conductors).")

    print("\n" + "="*60)
    print(f"SEEDING OF {count} USERS COMPLETED SUCCESSFULLY!")
    print("="*60)
    print(f"  Total Students created        : {len(student_profiles)}")
    print(f"  Total Faculty created         : {len(faculty_profiles)}")
    print(f"  Total Drivers created         : {len(driver_profiles)}")
    print(f"  Total Conductors created      : {len(conductor_profiles)}")
    print("  Password for all users        : Password123")
    print("="*60)

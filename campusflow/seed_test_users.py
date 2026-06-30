"""
CampusFlow Test User Seeding Tool
=================================
Usage:
  python manage.py shell < seed_test_users.py

Instructions:
  Set the TARGET_SCHEMA variable below to your desired tenant (e.g., 'demo', 'mit').
  This will create test users with password 'Password123' and assign their profiles.
"""
import sys
import uuid
from django.contrib.auth.models import User, Group
from django_tenants.utils import schema_context
from campusflow_app.models.profile import (
    StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile,
    ManagementProfile, AdministratorProfile, DepartmentHeadProfile
)
from campusflow_app.models.department import Department

# Define target schema to seed
TARGET_SCHEMA = 'demo'

print(f"Starting test user seeding for schema context: '{TARGET_SCHEMA}'")

try:
    with schema_context(TARGET_SCHEMA):
        # 1. Ensure Groups/Roles exist
        roles = ['student', 'Faculty', 'Support Staff', 'Management', 'Administrator', 'Department Head']
        groups = {}
        for role_name in roles:
            group, created = Group.objects.get_or_create(name=role_name)
            groups[role_name] = group
            if created:
                print(f"Provisioned Role Group: {role_name}")

        # 2. Get or create a default department
        dept, _ = Department.objects.get_or_create(
            code='GEN',
            defaults={'name': 'General Department', 'status': 'Active'}
        )

        # Helper to safely create a user, clear existing profiles, and map roles
        def create_test_user(username, email, role, profile_class, profile_fields={}):
            # Cleanup existing if any to allow re-runs
            User.objects.filter(username=username).delete()
            
            user = User.objects.create_user(
                username=username,
                email=email,
                password='Password123',
                is_staff=True if role in ['Management', 'Administrator'] else False
            )
            user.groups.add(groups[role])
            
            # Populate profile records
            profile_fields['user'] = user
            profile_class.objects.create(**profile_fields)
            print(f"Created user '{username}' with role '{role}' and profile.")
            return user

        # 3. Create Users
        # Student
        create_test_user(
            username=f"{TARGET_SCHEMA}_student",
            email=f"student@{TARGET_SCHEMA}.edu",
            role='student',
            profile_class=StudentProfile,
            profile_fields={
                'student_id': f"STU-{uuid.uuid4().hex[:5].upper()}",
                'department': dept,
                'status': 'active'
            }
        )

        # Faculty
        create_test_user(
            username=f"{TARGET_SCHEMA}_faculty",
            email=f"faculty@{TARGET_SCHEMA}.edu",
            role='Faculty',
            profile_class=TeachingStaffProfile,
            profile_fields={
                'employee_id': f"FAC-{uuid.uuid4().hex[:5].upper()}",
                'department': dept
            }
        )

        # Department Head (HOD)
        # Note: DepartmentHeadProfile uses OneToOneField to Department, so we don't bind to dept here if already occupied
        create_test_user(
            username=f"{TARGET_SCHEMA}_hod",
            email=f"hod@{TARGET_SCHEMA}.edu",
            role='Department Head',
            profile_class=DepartmentHeadProfile,
            profile_fields={
                'employee_id': f"HOD-{uuid.uuid4().hex[:5].upper()}"
            }
        )

        # Support Staff (Storekeeper / Librarian / Warden)
        create_test_user(
            username=f"{TARGET_SCHEMA}_staff",
            email=f"staff@{TARGET_SCHEMA}.edu",
            role='Support Staff',
            profile_class=NonTeachingStaffProfile,
            profile_fields={
                'employee_id': f"STF-{uuid.uuid4().hex[:5].upper()}",
                'status': 'active'
            }
        )

        # Management (College Owner / SaaS Admin proxy)
        create_test_user(
            username=f"{TARGET_SCHEMA}_management",
            email=f"management@{TARGET_SCHEMA}.edu",
            role='Management',
            profile_class=ManagementProfile,
            profile_fields={
                'employee_id': f"MGT-{uuid.uuid4().hex[:5].upper()}",
                'status': 'active'
            }
        )

        # Administrator
        create_test_user(
            username=f"{TARGET_SCHEMA}_admin",
            email=f"admin@{TARGET_SCHEMA}.edu",
            role='Administrator',
            profile_class=AdministratorProfile,
            profile_fields={
                'employee_id': f"ADM-{uuid.uuid4().hex[:5].upper()}",
                'status': 'active'
            }
        )

        print("--------------------------------------------------")
        print("Test user seeding completed successfully!")
        print("Default Password for all users is: Password123")
        print("--------------------------------------------------")

except Exception as e:
    print(f"Error seeding test users: {str(e)}")

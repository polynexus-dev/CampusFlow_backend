import os
import sys
import random

if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
    import django
    django.setup()

from django_tenants.utils import schema_context
from campusflow_app.serializers import UserRegistrationSerializer
from campusflow_app.models import Department

def test_serializer_create():
    with schema_context('demo'):
        dept = Department.objects.first()
        uname = f"test_reg_{random.randint(1000, 9999)}"
        data = {
            "username": uname,
            "email": f"{uname}@demo.localhost",
            "password": "SecurePassword123!",
            "password2": "SecurePassword123!",
            "first_name": "Test",
            "last_name": "User",
            "role": "student",
            "student_id": f"STU-{random.randint(1000, 9999)}",
            "department_id": dept.id,
            "program_enrolled_in_id": "B.Tech CS",
            "date_of_birth": "2003-01-01",
            "consent_given": True
        }

        serializer = UserRegistrationSerializer(data=data)
        if serializer.is_valid():
            user = serializer.save()
            print(f"SUCCESS! Created user '{user.username}' with is_active = {user.is_active}")
        else:
            print("Serializer errors:", serializer.errors)

if __name__ == "__main__":
    test_serializer_create()

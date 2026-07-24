import os
import sys

if not os.environ.get('DJANGO_SETTINGS_MODULE'):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
    import django
    django.setup()

from django_tenants.utils import schema_context
from campusflow_app.models import Lecture, StudentProfile
from campusflow_app.demo_guard import is_demo_tenant

def test_demo_checks():
    with schema_context('demo'):
        print(f"Is Demo Tenant: {is_demo_tenant()}")
        lectures = Lecture.objects.filter(code__isnull=False).exclude(code='')
        print(f"Total active lectures available for demo students: {lectures.count()}")

if __name__ == "__main__":
    test_demo_checks()

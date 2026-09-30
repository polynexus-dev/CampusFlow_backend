import os, django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'campusflow.settings')
django.setup()

from django.contrib.auth.models import User
from django_tenants.utils import schema_context

for s in ['public', 'demo']:
    print(f"=== SCHEMA: {s} ===")
    with schema_context(s):
        users = User.objects.all()[:15]
        for u in users:
            pw_admin123 = u.check_password('admin123')
            pw_password123 = u.check_password('Password123')
            print(f"  User: {u.username} | Email: {u.email} | admin123={pw_admin123} | Password123={pw_password123}")

import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
django.setup()

from django_tenants.utils import schema_context
from rest_framework_simplejwt.tokens import AccessToken
from django.contrib.auth.models import User

# Exact token from the user log
token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzgzNTMxMDMyLCJpYXQiOjE3ODM1MDIyMzIsImp0aSI6IjdhZDkzNDE3Mzk5NjRlMWI5MDU0MTkyYzUwNWQzNWE2IiwidXNlcl9pZCI6MTAsInRlbmFudF9zY2hlbWEiOiJkZW1vIn0.0iC6RujeyB6Ddrm3ZnoJrSGXSIUKGlZUtiTcE7NwGsA"

try:
    access_token = AccessToken(token)
    user_id = access_token["user_id"]
    print(f"Token decoded user_id: {user_id}")
    
    with schema_context("demo"):
        user = User.objects.get(id=user_id)
        print(f"User retrieved: {user.username} (ID: {user.id})")
except Exception as e:
    print(f"Token auth failed: {e}")

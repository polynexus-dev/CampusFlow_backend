import os
import random
from locust import HttpUser, task, between

# Load usernames: try local file first, then fall back to Django DB
db_usernames = []
if os.path.exists("usernames.txt"):
    print("Loading usernames from 'usernames.txt'...")
    with open("usernames.txt", "r") as f:
        db_usernames = [line.strip() for line in f if line.strip()]
else:
    print("No 'usernames.txt' found. Falling back to Django DB loading...")
    try:
        import django
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
        django.setup()
        from django_tenants.utils import schema_context
        from django.contrib.auth.models import User
        
        SCHEMA = os.getenv("LOCUST_SCHEMA", "demo")
        print(f"Loading usernames from database schema '{SCHEMA}'...")
        with schema_context(SCHEMA):
            db_usernames = list(User.objects.filter(
                is_active=True
            ).exclude(username='admin').values_list('username', flat=True))
            
        from django.db import connections
        connections.close_all()
    except Exception as e:
        print(f"Could not load usernames from Django database: {e}")

print(f"Loaded {len(db_usernames)} active usernames for load testing.")

class CampusFlowUser(HttpUser):
    # Simulate a user performing a login check
    wait_time = between(0.1, 0.5)

    def on_start(self):
        # Assign a random username from the preloaded database list
        if db_usernames:
            self.username = random.choice(db_usernames)
        else:
            self.username = "stu_00001"
        self.password = "Password123"

    @task
    def login(self):
        payload = {
            "username": self.username,
            "password": self.password
        }
        headers = {
            "Content-Type": "application/json"
        }
        with self.client.post("/login/", json=payload, headers=headers, catch_response=True) as response:
            if response.status_code == 200:
                response.success()
            else:
                response.failure(f"Failed to log in: {response.status_code} - {response.text}")

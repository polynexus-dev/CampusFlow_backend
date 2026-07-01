import os
import random
from locust import HttpUser, task, between

import requests

# Load usernames dynamically from target server API
db_usernames = []
TARGET_HOST = os.getenv("LOCUST_HOST", "https://campusnexus.api.polynexus.in")
ADMIN_USER = os.getenv("LOCUST_ADMIN", "demo_admin")
ADMIN_PASS = os.getenv("LOCUST_PASSWORD", "Password123")

print(f"Connecting to {TARGET_HOST} to dynamically fetch usernames list...")
try:
    # 1. Login as admin to get access token
    login_url = f"{TARGET_HOST.rstrip('/')}/login/"
    login_res = requests.post(login_url, json={
        "username": ADMIN_USER,
        "password": ADMIN_PASS
    }, headers={"Content-Type": "application/json"}, timeout=10)
    
    if login_res.status_code == 200:
        token = login_res.json().get("access")
        print("Logged in successfully. Querying user profiles...")
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        
        # 2. Fetch students
        students_url = f"{TARGET_HOST.rstrip('/')}/student/user/"
        students_res = requests.get(students_url, headers=headers, timeout=15)
        if students_res.status_code == 200:
            for item in students_res.json():
                username = item.get("user", {}).get("username")
                if username:
                    db_usernames.append(username)
            print(f"Loaded {len(db_usernames)} student usernames.")
        else:
            print(f"Failed to fetch students: {students_res.status_code}")
            
        # 3. Fetch faculty
        faculty_url = f"{TARGET_HOST.rstrip('/')}/teaching-staff/user/"
        faculty_res = requests.get(faculty_url, headers=headers, timeout=15)
        if faculty_res.status_code == 200:
            fac_count = 0
            for item in faculty_res.json():
                username = item.get("user", {}).get("username")
                if username:
                    db_usernames.append(username)
                    fac_count += 1
            print(f"Loaded {fac_count} faculty usernames.")
        else:
            print(f"Failed to fetch faculty: {faculty_res.status_code}")
    else:
        print(f"Admin login failed: {login_res.status_code} - {login_res.text}")
except Exception as e:
    print(f"Could not load usernames dynamically via HTTP API: {e}")

# Fallback in case of HTTP API errors
if not db_usernames:
    if os.path.exists("usernames.txt"):
        print("Loading usernames from local 'usernames.txt'...")
        with open("usernames.txt", "r") as f:
            db_usernames = [line.strip() for line in f if line.strip()]
    else:
        print("Fallback: Using Django DB loading...")
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
        except Exception as ex:
            print(f"Could not load usernames from Django database: {ex}")

# Final fallback
if not db_usernames:
    print("Static Fallback: Generating generic 'stu_00001' to 'stu_04000' range...")
    db_usernames = [f"stu_{i:05d}" for i in range(1, 4001)]

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

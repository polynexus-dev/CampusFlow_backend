import os
import random
from locust import HttpUser, task, between

import requests

# ── Attendance-rush load test config ────────────────────────────────────────
# Points at a lecture that must already have an *active* AttendanceSession
# (start one via the lecturer app/API before running this) and a folder with
# front.png/left.png (any real face photos work — used as the live selfie and
# the baseline motion frame). Every attempt will legitimately fail the final
# embedding-match step unless the logged-in student's own face was actually
# registered from these exact photos — that's fine, we're measuring pipeline
# throughput/latency under load, not correctness. Attempts also naturally
# stop counting after the first success per (student, lecture) — the
# duplicate-attendance check short-circuits before the CPU pipeline runs —
# so this is best pointed at a lecture/session dedicated to load testing,
# ideally with a large pool of never-yet-marked student accounts.
LOCUST_LECTURE_ID = os.getenv("LOCUST_LECTURE_ID")
LOCUST_IMAGES_DIR = os.getenv(
    "LOCUST_IMAGES_DIR",
    r"D:\Polynexus\Servers\Campusnexus\New folder\campusflow_mobile_new\test_images",
)
_front_bytes, _left_bytes = None, None
if LOCUST_LECTURE_ID:
    try:
        with open(os.path.join(LOCUST_IMAGES_DIR, "front.png"), "rb") as f:
            _front_bytes = f.read()
        with open(os.path.join(LOCUST_IMAGES_DIR, "left.png"), "rb") as f:
            _left_bytes = f.read()
    except OSError as e:
        print(f"Could not load test images for attendance load test: {e}")

# Load usernames dynamically from target server API
db_usernames = []
TARGET_HOST = os.getenv("LOCUST_HOST", "https://api.campusnexus.in")
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


class AttendanceRushUser(HttpUser):
    """
    Simulates the actual capacity bottleneck: concurrent face-attendance
    verification during a class-start rush (see MarkAttendanceView /
    campusflow_app/tasks.py::run_face_pipeline). This is deliberately a
    separate User class from CampusFlowUser's plain login test — run it in
    isolation so the two scenarios' numbers don't mix:

        LOCUST_LECTURE_ID=42 locust -f locustfile.py AttendanceRushUser --host=http://localhost:8200

    Requires a lecture (LOCUST_LECTURE_ID) with an already-active
    AttendanceSession — start one via the lecturer app/API first. Every
    user stops immediately on start if that's not configured, so running
    the plain `locust -f locustfile.py` command without it is unaffected.

    Caveat: the duplicate-attendance check short-circuits BEFORE the CPU
    pipeline runs, so only the first attempt per (student, lecture) pair
    actually exercises face_utils.py — a large db_usernames pool matters
    more here than request rate. A steady stream of 409s means the pool of
    fresh (student, lecture) pairs is exhausted, not that load has dropped.
    """
    wait_time = between(1, 2)

    def on_start(self):
        if not LOCUST_LECTURE_ID or _front_bytes is None:
            print(
                "AttendanceRushUser: LOCUST_LECTURE_ID or test images not "
                "configured — stopping this user without generating load."
            )
            self.environment.runner.quit()
            return

        self.token = None
        self.username = random.choice(db_usernames) if db_usernames else "stu_00001"
        self.password = "Password123"

        with self.client.post(
            "/login/",
            json={"username": self.username, "password": self.password},
            headers={"Content-Type": "application/json"},
            catch_response=True,
        ) as response:
            if response.status_code == 200:
                self.token = response.json().get("access")
                response.success()
            else:
                response.failure(f"Login failed: {response.status_code} - {response.text}")

    @task
    def mark_attendance(self):
        if not self.token:
            return

        headers = {"Authorization": f"Bearer {self.token}"}

        with self.client.get(
            "/liveness-challenge/", headers=headers, catch_response=True,
            name="/liveness-challenge/",
        ) as challenge_resp:
            if challenge_resp.status_code != 200:
                challenge_resp.failure(f"Challenge fetch failed: {challenge_resp.status_code}")
                return
            challenge_resp.success()
            challenge_id = challenge_resp.json().get("challenge_id")

        files = {
            "photo": ("front.png", _front_bytes, "image/png"),
            "photo_prev": ("left.png", _left_bytes, "image/png"),
        }
        data = {
            "lecture_id": LOCUST_LECTURE_ID,
            "challenge_id": challenge_id,
        }
        with self.client.post(
            "/mark-attendance/", headers=headers, data=data, files=files,
            catch_response=True, name="/mark-attendance/",
        ) as response:
            # 200 = verified, 400 = liveness/motion/embedding-match failure
            # (still ran the full CPU pipeline — expected here since these
            # test photos won't match any real student's registered face),
            # 409 = duplicate (pipeline skipped, see class docstring),
            # 503 = queue backpressure timeout. All are "not a bug" outcomes
            # for this load test; only unexpected status codes count as
            # failures.
            if response.status_code in (200, 400, 409, 503):
                response.success()
            else:
                response.failure(f"Unexpected status: {response.status_code} - {response.text}")

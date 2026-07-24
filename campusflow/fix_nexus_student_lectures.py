import requests
import json
import random
import string
import datetime
from datetime import date, timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def fix_lectures_for_student():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"

    # 1. Login as demo_admin
    r = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False, timeout=10)
    token_admin = r.json().get("access")
    headers_admin = {"Authorization": f"Bearer {token_admin}", "Content-Type": "application/json"}

    # 2. Get teaching staff user ID
    faculty_user_id = None
    staff_res = session.get(f"{BASE_URL}/api/teaching-staff/user/", headers=headers_admin, verify=False).json()
    staff_list = staff_res.get("results", []) if isinstance(staff_res, dict) else staff_res
    print(f"Found {len(staff_list)} teaching staff members.")

    for s in staff_list:
        u = s.get("user", {})
        uid = u.get("id") if isinstance(u, dict) else s.get("user_id")
        if uid:
            faculty_user_id = uid
            print(f"Using Faculty User ID: {faculty_user_id} ({u.get('username') if isinstance(u, dict) else 'faculty'})")
            break

    # Get classrooms
    classrooms_res = session.get(f"{BASE_URL}/api/classrooms/", headers=headers_admin, verify=False).json()
    classrooms = classrooms_res if isinstance(classrooms_res, list) else classrooms_res.get("results", [])
    room_id = classrooms[0]["id"] if classrooms else 1

    # 3. Create 50+ lectures with faculty_user_id and active code for next 30 days
    today = date.today()
    lectures_created = 0

    time_slots = [
        ("09:00:00", "10:00:00", "Data Structures & Algorithms"),
        ("10:00:00", "11:00:00", "Database Management Systems"),
        ("11:15:00", "12:15:00", "Web Technologies"),
        ("14:00:00", "15:00:00", "Operating Systems"),
    ]

    for day_offset in range(0, 31):
        curr_date = today + timedelta(days=day_offset)
        if curr_date.weekday() == 6:  # Skip Sundays
            continue

        for s_time, e_time, subj in time_slots:
            start_iso = f"{curr_date.strftime('%Y-%m-%d')}T{s_time}+05:30"
            end_iso = f"{curr_date.strftime('%Y-%m-%d')}T{e_time}+05:30"

            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            code_str = f"L{curr_date.strftime('%d%m')}{suffix}"

            payload = {
                "name": f"{subj} Lecture",
                "subject": subj,
                "classroom": room_id,
                "faculty": faculty_user_id,
                "start_time": start_iso,
                "end_time": end_iso,
                "code": code_str
            }

            r_lec = session.post(f"{BASE_URL}/api/lectures/", json=payload, headers=headers_admin, verify=False)
            if r_lec.status_code in [200, 201]:
                lectures_created += 1

    print(f"[+] Created {lectures_created} Lectures assigned to Faculty #{faculty_user_id} with active codes!")

    # 4. Verify as demo_student
    print("\n==========================================")
    print("VERIFYING COMPLETE STUDENT ACCESS FOR DEMO_STUDENT:")
    print("==========================================")
    r_stu = session.post(login_url, json={"username": "demo_student", "password": "Password123"}, verify=False, timeout=10)
    token_stu = r_stu.json().get("access")
    headers_stu = {"Authorization": f"Bearer {token_stu}"}

    endpoints = [
        "/api/schedules/",
        "/api/lectures/",
        "/api/assignments/",
        "/api/announcements/",
        "/api/books/",
    ]

    for ep in endpoints:
        res = session.get(f"{BASE_URL}{ep}", headers=headers_stu, verify=False)
        items = res.json()
        count = len(items) if isinstance(items, list) else len(items.get("results", [])) if isinstance(items, dict) else "N/A"
        print(f"  [+] GET {ep} -> Status: {res.status_code} | Items Visible to demo_student: {count}")

if __name__ == "__main__":
    fix_lectures_for_student()

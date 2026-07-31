import requests
import json
import random
import string
import datetime
from datetime import date, timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def bind_lectures_to_cs_faculty():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"

    # 1. Login as demo_admin
    r = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False, timeout=10)
    token_admin = r.json().get("access")
    headers_admin = {"Authorization": f"Bearer {token_admin}", "Content-Type": "application/json"}

    # 2. Get teaching staff list
    staff_res = session.get(f"{BASE_URL}/api/teaching-staff/user/", headers=headers_admin, verify=False).json()
    staff_list = staff_res.get("results", []) if isinstance(staff_res, dict) else staff_res

    print(f"Found {len(staff_list)} faculty members.")
    cs_faculty_user_id = None

    for s in staff_list:
        dept = s.get("department")
        u = s.get("user", {})
        uid = u.get("id") if isinstance(u, dict) else s.get("user_id")
        uname = u.get("username") if isinstance(u, dict) else ""
        print(f"  Faculty Username: {uname} | Dept: '{dept}' | UserID: {uid}")

        if dept == "Computer Science" or uname == "demo_faculty":
            cs_faculty_user_id = s.get("user_id") or (u.get("id") if isinstance(u, dict) else None)
            if not cs_faculty_user_id and "id" in s:
                cs_faculty_user_id = s["id"]
            print(f"  --> MATCH CS Faculty User ID: {cs_faculty_user_id}")
            break

    if not cs_faculty_user_id and staff_list:
        # Fallback to first faculty
        first_u = staff_list[0].get("user", {})
        cs_faculty_user_id = first_u.get("id") if isinstance(first_u, dict) else staff_list[0].get("user_id")

    print(f"[+] Final CS Faculty User ID: {cs_faculty_user_id}")

    # 3. Create Classrooms & Lectures from 2026-07-24 to 2026-07-31 (10 AM to 5 PM, Mon-Sat)
    classrooms_res = session.get(f"{BASE_URL}/api/classrooms/", headers=headers_admin, verify=False).json()
    classrooms = classrooms_res if isinstance(classrooms_res, list) else classrooms_res.get("results", [])
    room_id = classrooms[0]["id"] if classrooms else 1

    today = date(2026, 7, 24)
    end_date = date(2026, 7, 31)

    time_slots_spec = [
        ("10:00:00", "11:00:00", "Data Structures & Algorithms"),
        ("11:00:00", "12:00:00", "Database Management Systems"),
        ("12:00:00", "13:00:00", "Operating Systems"),
        ("14:00:00", "15:00:00", "Computer Networks"),
        ("15:00:00", "16:00:00", "Software Engineering"),
        ("16:00:00", "17:00:00", "Web Technologies & Cloud"),
    ]

    lectures_created = 0
    curr_date = today

    while curr_date <= end_date:
        if curr_date.weekday() != 6: # Skip Sundays
            for s_time, e_time, subj in time_slots_spec:
                start_iso = f"{curr_date.strftime('%Y-%m-%d')}T{s_time}+05:30"
                end_iso = f"{curr_date.strftime('%Y-%m-%d')}T{e_time}+05:30"

                suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
                code_str = f"L{curr_date.strftime('%d%m')}{suffix}"

                lec_payload = {
                    "name": f"{subj} Session",
                    "subject": subj,
                    "classroom": room_id,
                    "faculty": cs_faculty_user_id,
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "code": code_str
                }

                r_lec = session.post(f"{BASE_URL}/api/lectures/", json=lec_payload, headers=headers_admin, verify=False)
                if r_lec.status_code in [200, 201]:
                    lectures_created += 1

        curr_date += timedelta(days=1)

    print(f"[+] Created {lectures_created} Lectures for CS Faculty #{cs_faculty_user_id}!")

    # 4. Verify as demo_student
    print("\n==========================================")
    print("VERIFYING FINAL STUDENT ACCESS FOR DEMO_STUDENT:")
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
    bind_lectures_to_cs_faculty()

import requests
import json
import random
import string
import datetime
from datetime import date, timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def final_cs_setup():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"

    # 1. Login as demo_admin
    r = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False, timeout=10)
    token_admin = r.json().get("access")
    headers_admin = {"Authorization": f"Bearer {token_admin}", "Content-Type": "application/json"}

    # Update demo_student to Department #1 (Computer Science)
    stu_res = session.get(f"{BASE_URL}/api/student/user/", headers=headers_admin, verify=False).json()
    students = stu_res.get("results", []) if isinstance(stu_res, dict) else stu_res
    
    demo_stu_id = None
    for s in students:
        u = s.get("user", {})
        uname = u.get("username") if isinstance(u, dict) else u
        if uname == "demo_student":
            demo_stu_id = s.get("id")
            break

    if demo_stu_id:
        session.put(f"{BASE_URL}/api/student/user/", json={"id": demo_stu_id, "department_id": 1}, headers=headers_admin, verify=False)
        print(f"[+] Set demo_student department to #1 (Computer Science).")

    # Update Faculty #5 and Faculty #11 department to Department #1 (Computer Science)
    staff_res = session.get(f"{BASE_URL}/api/teaching-staff/user/", headers=headers_admin, verify=False).json()
    staff_list = staff_res.get("results", []) if isinstance(staff_res, dict) else staff_res
    for s in staff_list[:10]:
        s_id = s.get("id")
        if s_id:
            session.put(f"{BASE_URL}/api/teaching-staff/user/", json={"id": s_id, "department_id": 1}, headers=headers_admin, verify=False)

    print("[+] Updated faculty profiles to Department #1 (Computer Science).")

    # 2. Get Classrooms & CS Courses
    classrooms_res = session.get(f"{BASE_URL}/api/classrooms/", headers=headers_admin, verify=False).json()
    classrooms = classrooms_res if isinstance(classrooms_res, list) else classrooms_res.get("results", [])
    room_id = classrooms[0]["id"] if classrooms else 1

    cs_faculty_ids = [5, 11, 4016, 4017]

    # 3. Create Lectures for 10 AM to 5 PM from July 24, 2026 to July 31, 2026 (Mon-Sat)
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
            for idx, (s_time, e_time, subj) in enumerate(time_slots_spec):
                start_iso = f"{curr_date.strftime('%Y-%m-%d')}T{s_time}+05:30"
                end_iso = f"{curr_date.strftime('%Y-%m-%d')}T{e_time}+05:30"

                suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
                code_str = f"L{curr_date.strftime('%d%m')}{suffix}"

                fac_id = cs_faculty_ids[idx % len(cs_faculty_ids)]

                lec_payload = {
                    "name": f"{subj} Session",
                    "subject": subj,
                    "classroom": room_id,
                    "faculty": fac_id,
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "code": code_str
                }

                r_lec = session.post(f"{BASE_URL}/api/lectures/", json=lec_payload, headers=headers_admin, verify=False)
                if r_lec.status_code in [200, 201]:
                    lectures_created += 1

        curr_date += timedelta(days=1)

    print(f"[+] Created {lectures_created} Daily Lectures from 10 AM to 5 PM (Mon-Sat, July 24 - July 31)!")

    # 4. Verify as demo_student
    print("\n==========================================")
    print("VERIFYING DEMO_STUDENT VISIBILITY:")
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
        print(f"  [+] GET {ep} -> Status: {res.status_code} | Total Items Visible to demo_student: {count}")

if __name__ == "__main__":
    final_cs_setup()

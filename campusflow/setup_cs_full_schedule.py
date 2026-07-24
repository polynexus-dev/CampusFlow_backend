import requests
import json
import random
import string
import datetime
from datetime import date, time, timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def setup_cs():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"

    # 1. Login as demo_admin
    r = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False, timeout=10)
    token_admin = r.json().get("access")
    headers_admin = {"Authorization": f"Bearer {token_admin}", "Content-Type": "application/json"}
    print("[1] Logged in as demo_admin.")

    # 2. Assign demo_student to Department ID 1 (Computer Science) and Program "B.Tech CS"
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
        update_payload = {
            "id": demo_stu_id,
            "department_id": 1,
            "program_enrolled_in": "B.Tech CS"
        }
        u_res = session.put(f"{BASE_URL}/api/student/user/", json=update_payload, headers=headers_admin, verify=False)
        print(f"[+] Assigned demo_student (profile #{demo_stu_id}) to Department #1 (Computer Science) & Program 'B.Tech CS' (Status {u_res.status_code}).")

    # 3. Get Courses for Department #1 (Computer Science) & Classrooms
    courses_res = session.get(f"{BASE_URL}/api/courses/", headers=headers_admin, verify=False).json()
    courses = courses_res if isinstance(courses_res, list) else courses_res.get("results", [])
    cs_courses = [c for c in courses if c.get("department_id") == 1]
    if not cs_courses:
        cs_courses = courses[:3]
    print(f"[+] Found {len(cs_courses)} CS Courses.")

    classrooms_res = session.get(f"{BASE_URL}/api/classrooms/", headers=headers_admin, verify=False).json()
    classrooms = classrooms_res if isinstance(classrooms_res, list) else classrooms_res.get("results", [])
    room_id = classrooms[0]["id"] if classrooms else 1

    # Get Faculty ID (user 5 or similar)
    faculty_id = 5

    # 4. Create Weekly Schedules for 10 AM to 5 PM (Monday to Saturday)
    time_slots_spec = [
        ("10:00:00", "11:00:00", "Data Structures & Algorithms"),
        ("11:00:00", "12:00:00", "Database Management Systems"),
        ("12:00:00", "13:00:00", "Operating Systems"),
        ("14:00:00", "15:00:00", "Computer Networks"),
        ("15:00:00", "16:00:00", "Software Engineering"),
        ("16:00:00", "17:00:00", "Web Technologies & Cloud"),
    ]

    days_of_week = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    schedules_created = 0

    for day in days_of_week:
        for idx, (s_time, e_time, subj) in enumerate(time_slots_spec):
            c_obj = cs_courses[idx % len(cs_courses)]
            sch_payload = {
                "course": c_obj["id"],
                "classroom": room_id,
                "day_of_week": day,
                "start_time": s_time,
                "end_time": e_time,
                "faculty": faculty_id,
                "semester": "Semester 4",
                "academic_year": "2025-2026"
            }
            r_sch = session.post(f"{BASE_URL}/api/schedules/", json=sch_payload, headers=headers_admin, verify=False)
            if r_sch.status_code in [200, 201]:
                schedules_created += 1

    print(f"[+] Created {schedules_created} Timetable Schedule slots for 10 AM to 5 PM across Monday-Saturday!")

    # 5. Create Daily Lectures for everyday from TODAY (2026-07-24) to 2026-07-31 (except Sundays)
    today = date(2026, 7, 24)
    end_date = date(2026, 7, 31)
    
    lectures_created = 0
    curr_date = today

    while curr_date <= end_date:
        # Skip Sundays (weekday == 6)
        if curr_date.weekday() != 6:
            for s_time, e_time, subj in time_slots_spec:
                start_iso = f"{curr_date.strftime('%Y-%m-%d')}T{s_time}+05:30"
                end_iso = f"{curr_date.strftime('%Y-%m-%d')}T{e_time}+05:30"

                suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
                code_str = f"L{curr_date.strftime('%d%m')}{suffix}"

                lec_payload = {
                    "name": f"{subj} Session",
                    "subject": subj,
                    "classroom": room_id,
                    "faculty": faculty_id,
                    "start_time": start_iso,
                    "end_time": end_iso,
                    "code": code_str
                }

                r_lec = session.post(f"{BASE_URL}/api/lectures/", json=lec_payload, headers=headers_admin, verify=False)
                if r_lec.status_code in [200, 201]:
                    lectures_created += 1

        curr_date += timedelta(days=1)

    print(f"[+] Created {lectures_created} Lectures for everyday from {today} to {end_date} (10 AM - 5 PM, Mon-Sat)!")

    # 6. Verify as demo_student
    print("\n==========================================")
    print("VERIFYING ACCESSIBILITY FOR DEMO_STUDENT:")
    print("==========================================")
    r_stu = session.post(login_url, json={"username": "demo_student", "password": "Password123"}, verify=False, timeout=10)
    token_stu = r_stu.json().get("access")
    headers_stu = {"Authorization": f"Bearer {token_stu}"}

    # Verify Profile
    prof = session.get(f"{BASE_URL}/api/user/", headers=headers_stu, verify=False).json()
    print(f"  [+] Student Username: {prof.get('user', {}).get('username')}")
    print(f"  [+] Department: '{prof.get('department')}' (ID: {prof.get('profile', {}).get('department_id')})")
    print(f"  [+] Program Enrolled In: '{prof.get('program_enrolled_in')}'")

    endpoints = [
        "/api/schedules/",
        "/api/lectures/",
        "/api/assignments/",
        "/api/announcements/",
    ]

    for ep in endpoints:
        res = session.get(f"{BASE_URL}{ep}", headers=headers_stu, verify=False)
        items = res.json()
        count = len(items) if isinstance(items, list) else len(items.get("results", [])) if isinstance(items, dict) else "N/A"
        print(f"  [+] GET {ep} -> Status: {res.status_code} | Total Items Seen by demo_student: {count}")

if __name__ == "__main__":
    setup_cs()

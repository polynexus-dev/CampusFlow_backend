import requests
import json
import datetime
from datetime import timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def fix_student_and_seed():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"

    # 1. Login as demo_admin
    r = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False, timeout=10)
    token_admin = r.json().get("access")
    headers_admin = {"Authorization": f"Bearer {token_admin}", "Content-Type": "application/json"}

    print("[1] Logged in as demo_admin.")

    # 2. Update demo_student's department to Department ID 1 (Computer Science)
    # Get student profile ID from GET /api/student/user/
    stu_res = session.get(f"{BASE_URL}/api/student/user/", headers=headers_admin, verify=False).json()
    students = stu_res.get("results", []) if isinstance(stu_res, dict) else stu_res

    print(f"Found {len(students)} students in system.")
    demo_stu_id = None
    for s in students:
        u = s.get("user", {})
        uname = u.get("username") if isinstance(u, dict) else u
        if uname == "demo_student":
            demo_stu_id = s.get("id")
            print(f"Found demo_student profile ID: {demo_stu_id}")
            break

    if demo_stu_id:
        update_payload = {
            "id": demo_stu_id,
            "department_id": 1
        }
        u_res = session.put(f"{BASE_URL}/api/student/user/", json=update_payload, headers=headers_admin, verify=False)
        print(f"Update student profile response status: {u_res.status_code}")
    else:
        print("Could not find demo_student in /api/student/user/ list.")

    # Also, let's create Schedules & Assignments explicitly for Department 4 (General Department) just in case!
    courses_res = session.get(f"{BASE_URL}/api/courses/", headers=headers_admin, verify=False).json()
    courses = courses_res if isinstance(courses_res, list) else courses_res.get("results", [])
    print(f"Found {len(courses)} Courses.")

    # Create a course for Department 4 if needed
    r_c = session.post(f"{BASE_URL}/api/courses/", json={"course_code": "GEN101", "course_name": "General Fundamentals", "department_id": 4}, headers=headers_admin, verify=False)
    gen_course_id = r_c.json().get("id") if r_c.status_code in [200, 201] else (courses[0]["id"] if courses else 1)
    print(f"General Course ID: {gen_course_id}")

    # Create Schedules for Dept 1 & Dept 4
    classrooms_res = session.get(f"{BASE_URL}/api/classrooms/", headers=headers_admin, verify=False).json()
    classrooms = classrooms_res if isinstance(classrooms_res, list) else classrooms_res.get("results", [])
    room_id = classrooms[0]["id"] if classrooms else 1

    days = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
    for c_obj in courses[:5]:
        c_id = c_obj["id"]
        for day in days:
            sch_payload = {
                "course": c_id,
                "classroom": room_id,
                "day_of_week": day,
                "start_time": "09:00:00",
                "end_time": "10:00:00",
                "semester": "Semester 4",
                "academic_year": "2025-2026"
            }
            session.post(f"{BASE_URL}/api/schedules/", json=sch_payload, headers=headers_admin, verify=False)

    # 3. Create Assignments for Dept 1 AND Dept 4
    for d_id in [1, 4]:
        for c_id in [courses[0]["id"] if courses else 1, gen_course_id]:
            ass_data = {
                "title": f"Core Course Assignment (Dept {d_id})",
                "description": "Complete problem set 1-5 and submit online.",
                "course_id": c_id,
                "department_id": d_id,
                "due_date": (datetime.datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
            }
            session.post(f"{BASE_URL}/api/assignments/", data=ass_data, headers={"Authorization": f"Bearer {token_admin}"}, verify=False)

    # 4. Now Verify as demo_student!
    print("\n==========================================")
    print("VERIFYING WHAT DEMO_STUDENT SEES NOW:")
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
        print(f"  [+] GET {ep} -> Status: {res.status_code} | Total Items Seen by demo_student: {count}")

if __name__ == "__main__":
    fix_student_and_seed()

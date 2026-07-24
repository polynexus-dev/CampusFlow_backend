import requests
import json
import random
import string
import datetime
from datetime import date, time, timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def populate_remote():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"
    login_payload = {"username": "demo_admin", "password": "Password123"}

    print(f"Logging in to {BASE_URL}...")
    res = session.post(login_url, json=login_payload, verify=False, timeout=10)
    if res.status_code != 200:
        print(f"Failed to login: {res.status_code} - {res.text}")
        return

    data = res.json()
    token = data.get("access")
    print(f"[+] Logged in successfully! (user_id={data.get('user_id')}, schema={data.get('tenant_schema')})")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    # ── 1. Fetch Classrooms, Courses, Users, Departments ─────────────────
    print("\nFetching infrastructure from remote API...")
    classrooms_res = session.get(f"{BASE_URL}/api/classrooms/", headers=headers, verify=False).json()
    courses_res = session.get(f"{BASE_URL}/api/courses/", headers=headers, verify=False).json()
    schedules_res = session.get(f"{BASE_URL}/api/schedules/", headers=headers, verify=False).json()

    classrooms = classrooms_res if isinstance(classrooms_res, list) else classrooms_res.get("results", [])
    courses = courses_res if isinstance(courses_res, list) else courses_res.get("results", [])
    schedules = schedules_res if isinstance(schedules_res, list) else schedules_res.get("results", [])

    print(f"Found {len(classrooms)} Classrooms, {len(courses)} Courses, {len(schedules)} Timetable Schedules.")

    if not classrooms:
        r = session.post(f"{BASE_URL}/api/classroom/", json={"name": "Room 101"}, headers=headers, verify=False)
        classrooms = [r.json()]
    
    room_id = classrooms[0]["id"]
    course_id = courses[0]["id"] if courses else 1

    # ── 2. Create Future Lectures for the Next 30 Days ──────────────────
    print("\n[1/4] Seeding Lectures for the next 30 days...")
    today = date.today()
    lectures_created = 0

    times_slots = [
        ("09:00:00", "10:00:00", "Data Structures & Algorithms"),
        ("10:00:00", "11:00:00", "Database Management Systems"),
        ("11:15:00", "12:15:00", "Web Technologies"),
        ("14:00:00", "15:00:00", "Operating Systems"),
    ]

    for day_offset in range(0, 31):
        curr_date = today + timedelta(days=day_offset)
        # Skip Sundays
        if curr_date.weekday() == 6:
            continue

        for s_time, e_time, subj in times_slots:
            start_iso = f"{curr_date.strftime('%Y-%m-%d')}T{s_time}+05:30"
            end_iso = f"{curr_date.strftime('%Y-%m-%d')}T{e_time}+05:30"

            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=4))
            code_str = f"L{curr_date.strftime('%d%m')}{suffix}"

            payload = {
                "name": f"{subj} Session",
                "subject": subj,
                "classroom": room_id,
                "start_time": start_iso,
                "end_time": end_iso,
                "code": code_str
            }

            r = session.post(f"{BASE_URL}/api/lectures/", json=payload, headers=headers, verify=False)
            if r.status_code in [200, 201]:
                lectures_created += 1

    print(f"[+] Created {lectures_created} Future Lectures on api.campusnexus.in!")

    # ── 3. Create Announcements ──────────────────────────────────────────
    print("\n[2/4] Seeding Announcements...")
    announcements_data = [
        {
            "title": "Midterm Examination Timetable Released",
            "content": "The midterm examinations for Semester 4 will commence from the 15th of next month. All students must check their portals for individual seating arrangements.",
            "priority": "urgent",
            "is_pinned": True
        },
        {
            "title": "Annual Campus Hackathon 2026",
            "content": "Join us for a 36-hour codefest! Solve real-world challenges in AI, Cloud, and Web. Exciting cash prizes and internship opportunities.",
            "priority": "high",
            "is_pinned": True
        },
        {
            "title": "Guest Lecture: Scalable System Design & Microservices",
            "content": "Industry expert from PolyNexus Systems will deliver a hands-on guest session in Auditorium 1 this Thursday at 2:00 PM.",
            "priority": "high",
            "is_pinned": False
        },
        {
            "title": "Central Library Book Circulation Notice",
            "content": "All borrowed books due before the end of this month must be returned or renewed online to avoid late fines.",
            "priority": "normal",
            "is_pinned": False
        }
    ]

    ann_created = 0
    for ann in announcements_data:
        r = session.post(f"{BASE_URL}/api/announcements/", json=ann, headers=headers, verify=False)
        if r.status_code in [200, 201]:
            ann_created += 1
        else:
            print(f"  Announcement error ({r.status_code}): {r.text[:200]}")
    print(f"[+] Created {ann_created} Announcements!")

    # ── 4. Create Assignments ────────────────────────────────────────────
    print("\n[3/4] Seeding Assignments...")
    dept_id = 1
    if courses:
        dept_id = courses[0].get("department_id") or 1

    assignments_data = [
        {
            "title": "Assignment 1: B-Tree & Red-Black Tree Implementation",
            "description": "Implement balanced search trees in Python or C++. Submit clean code along with complexity analysis.",
            "course": course_id,
            "department": dept_id,
            "due_date": (datetime.datetime.now() + timedelta(days=5)).isoformat()
        },
        {
            "title": "Assignment 2: SQL Query Optimization & Indexing",
            "description": "Analyze execution plans for 10 complex multi-table queries. Optimize using indexes and partitioned schemas.",
            "course": course_id,
            "department": dept_id,
            "due_date": (datetime.datetime.now() + timedelta(days=12)).isoformat()
        },
        {
            "title": "Assignment 3: RESTful API & JWT Authentication App",
            "description": "Build a Node.js/Django backend API with JWT authentication, role-based access control, and Swagger documentation.",
            "course": course_id,
            "department": dept_id,
            "due_date": (datetime.datetime.now() + timedelta(days=18)).isoformat()
        },
        {
            "title": "Assignment 4: Docker & Kubernetes Microservice Deployment",
            "description": "Containerize a multi-service app using Docker Compose and deploy to a local Minikube cluster.",
            "course": course_id,
            "department": dept_id,
            "due_date": (datetime.datetime.now() + timedelta(days=25)).isoformat()
        }
    ]

    ass_created = 0
    for ass in assignments_data:
        r = session.post(f"{BASE_URL}/api/assignments/", json=ass, headers=headers, verify=False)
        if r.status_code in [200, 201]:
            ass_created += 1
        else:
            print(f"  Assignment error ({r.status_code}): {r.text[:200]}")
    print(f"[+] Created {ass_created} Assignments!")

    # ── 5. Create Library Books & Stock ─────────────────────────────────
    print("\n[4/4] Seeding Library Books & Stock...")
    books_data = [
        {"title": "Introduction to Algorithms", "author": "Thomas H. Cormen", "isbn": "978-0262033848", "publisher": "MIT Press", "total_copies": 10, "available_copies": 7},
        {"title": "Clean Code", "author": "Robert C. Martin", "isbn": "978-0132350884", "publisher": "Prentice Hall", "total_copies": 8, "available_copies": 5},
        {"title": "Design Patterns", "author": "Erich Gamma", "isbn": "978-0201633610", "publisher": "Addison-Wesley", "total_copies": 6, "available_copies": 4},
        {"title": "Database System Concepts", "author": "Abraham Silberschatz", "isbn": "978-0073523323", "publisher": "McGraw-Hill", "total_copies": 12, "available_copies": 9},
        {"title": "Operating System Concepts", "author": "Abraham Silberschatz", "isbn": "978-1118063330", "publisher": "Wiley", "total_copies": 10, "available_copies": 8},
        {"title": "Computer Networks", "author": "Andrew S. Tanenbaum", "isbn": "978-0132126953", "publisher": "Pearson", "total_copies": 7, "available_copies": 5},
    ]

    books_created = 0
    for bd in books_data:
        r = session.post(f"{BASE_URL}/api/books/", json=bd, headers=headers, verify=False)
        if r.status_code in [200, 201]:
            books_created += 1
            book_obj = r.json()
            b_id = book_obj.get("id")
            # Create a book copy
            copy_payload = {
                "book": b_id,
                "barcode": f"BC-{bd['isbn'][-6:]}-01",
                "status": "Available"
            }
            session.post(f"{BASE_URL}/api/book-copies/", json=copy_payload, headers=headers, verify=False)
        else:
            print(f"  Book error ({r.status_code}): {r.text[:200]}")
    print(f"[+] Created {books_created} Library Books with stock copies!")

    print("\n[SUCCESS] POPULATION OF API.CAMPUSNEXUS.IN COMPLETE!")

if __name__ == "__main__":
    populate_remote()

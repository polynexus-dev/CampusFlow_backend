import requests
import datetime
from datetime import timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def add_assignments_all_depts():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"

    r = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False, timeout=10)
    token_admin = r.json().get("access")
    headers_auth = {"Authorization": f"Bearer {token_admin}"}

    courses_res = session.get(f"{BASE_URL}/api/courses/", headers=headers_auth, verify=False).json()
    courses = courses_res if isinstance(courses_res, list) else courses_res.get("results", [])
    c_id = courses[0]["id"] if courses else 1

    departments_to_seed = [1, 2, 3, 4]

    for d_id in departments_to_seed:
        assignments_data = [
            {
                "title": f"Assignment 1: Data Structures & Trees (Dept #{d_id})",
                "description": "Implement balanced search trees in Python or C++. Submit clean code along with complexity analysis.",
                "course_id": c_id,
                "department_id": d_id,
                "due_date": (datetime.datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
            },
            {
                "title": f"Assignment 2: Database Query Optimization (Dept #{d_id})",
                "description": "Analyze execution plans for 10 complex multi-table queries. Optimize using indexes and partitioned schemas.",
                "course_id": c_id,
                "department_id": d_id,
                "due_date": (datetime.datetime.now() + timedelta(days=12)).strftime("%Y-%m-%d %H:%M:%S")
            },
            {
                "title": f"Assignment 3: Web REST API & Auth (Dept #{d_id})",
                "description": "Build a Node.js/Django backend API with JWT authentication, role-based access control, and Swagger documentation.",
                "course_id": c_id,
                "department_id": d_id,
                "due_date": (datetime.datetime.now() + timedelta(days=18)).strftime("%Y-%m-%d %H:%M:%S")
            },
            {
                "title": f"Assignment 4: Cloud & Microservices (Dept #{d_id})",
                "description": "Containerize a multi-service app using Docker Compose and deploy to a local Minikube cluster.",
                "course_id": c_id,
                "department_id": d_id,
                "due_date": (datetime.datetime.now() + timedelta(days=25)).strftime("%Y-%m-%d %H:%M:%S")
            }
        ]

        for ass in assignments_data:
            session.post(f"{BASE_URL}/api/assignments/", data=ass, headers=headers_auth, verify=False)

    print("[+] Assignments created for ALL Departments (1, 2, 3, 4)!")

    # Verify as demo_student
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

    print("\n==========================================")
    print("FINAL VERIFICATION AS DEMO_STUDENT:")
    print("==========================================")
    for ep in endpoints:
        res = session.get(f"{BASE_URL}{ep}", headers=headers_stu, verify=False)
        items = res.json()
        count = len(items) if isinstance(items, list) else len(items.get("results", [])) if isinstance(items, dict) else "N/A"
        print(f"  [+] GET {ep} -> Status: {res.status_code} | Total Items Visible to demo_student: {count}")

if __name__ == "__main__":
    add_assignments_all_depts()

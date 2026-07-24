import requests
import datetime
from datetime import timedelta
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def populate_assignments():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"
    res = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False, timeout=10)
    data = res.json()
    token = data.get("access")

    headers_auth_only = {"Authorization": f"Bearer {token}"}

    courses_res = session.get(f"{BASE_URL}/api/courses/", headers=headers_auth_only, verify=False).json()
    courses = courses_res if isinstance(courses_res, list) else courses_res.get("results", [])
    course_id = courses[0]["id"] if courses else 1
    dept_id = courses[0].get("department_id") or 1 if courses else 1

    print(f"Course ID: {course_id}, Dept ID: {dept_id}")

    assignments_data = [
        {
            "title": "Assignment 1: B-Tree & Red-Black Tree Implementation",
            "description": "Implement balanced search trees in Python or C++. Submit clean code along with complexity analysis.",
            "course_id": course_id,
            "department_id": dept_id,
            "due_date": (datetime.datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d %H:%M:%S")
        },
        {
            "title": "Assignment 2: SQL Query Optimization & Indexing",
            "description": "Analyze execution plans for 10 complex multi-table queries. Optimize using indexes and partitioned schemas.",
            "course_id": course_id,
            "department_id": dept_id,
            "due_date": (datetime.datetime.now() + timedelta(days=12)).strftime("%Y-%m-%d %H:%M:%S")
        },
        {
            "title": "Assignment 3: RESTful API & JWT Authentication App",
            "description": "Build a Node.js/Django backend API with JWT authentication, role-based access control, and Swagger documentation.",
            "course_id": course_id,
            "department_id": dept_id,
            "due_date": (datetime.datetime.now() + timedelta(days=18)).strftime("%Y-%m-%d %H:%M:%S")
        },
        {
            "title": "Assignment 4: Docker & Kubernetes Microservice Deployment",
            "description": "Containerize a multi-service app using Docker Compose and deploy to a local Minikube cluster.",
            "course_id": course_id,
            "department_id": dept_id,
            "due_date": (datetime.datetime.now() + timedelta(days=25)).strftime("%Y-%m-%d %H:%M:%S")
        }
    ]

    ass_created = 0
    for ass in assignments_data:
        r = session.post(f"{BASE_URL}/api/assignments/", data=ass, headers=headers_auth_only, verify=False)
        if r.status_code in [200, 201]:
            ass_created += 1
            print(f"  [+] Created assignment: {ass['title']}")
        else:
            print(f"  [-] Assignment error ({r.status_code}): {r.text[:200]}")
    print(f"[+] Total Assignments Created: {ass_created}")

if __name__ == "__main__":
    populate_assignments()

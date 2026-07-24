import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

session = requests.Session()
r_admin = session.post(f"{BASE_URL}/api/login/", json={"username": "demo_admin", "password": "Password123"}, verify=False)
token_admin = r_admin.json().get("access")
headers_admin = {"Authorization": f"Bearer {token_admin}"}

print("Searching for student_johndoe in student user profiles...")
res = session.get(f"{BASE_URL}/api/student/user/?search=johndoe", headers=headers_admin, verify=False).json()
items = res.get("results", []) if isinstance(res, dict) else res
print(f"Results for search=johndoe in student profile: {len(items)}")
for i in items:
    print(i)

# Also check college employees or general users list
print("\nSearching in college employees...")
res_emp = session.get(f"{BASE_URL}/api/college/employees/?search=johndoe", headers=headers_admin, verify=False).json()
items_emp = res_emp.get("results", []) if isinstance(res_emp, dict) else res_emp
print(f"Results for search=johndoe in employees: {len(items_emp)}")
for i in items_emp:
    print(i)

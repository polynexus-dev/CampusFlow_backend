import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

session = requests.Session()
r = session.post(f"{BASE_URL}/api/login/", json={"username": "demo_admin", "password": "Password123"}, verify=False)
token = r.json().get("access")
headers = {"Authorization": f"Bearer {token}"}

# Check /api/college/employees/
res = session.get(f"{BASE_URL}/api/college/employees/", headers=headers, verify=False).json()
items = res.get("results", []) if isinstance(res, dict) else res
print(f"Total employees: {len(items)}")
for emp in items:
    u = emp.get("user", {})
    uname = u.get("username") if isinstance(u, dict) else emp.get("username")
    uid = u.get("id") if isinstance(u, dict) else emp.get("id")
    dept = emp.get("department")
    role = emp.get("role")
    if uname in ["fac_01598", "fac_01599", "demo_faculty", "demo_faculty2"]:
        print(f"  MATCH: username={uname} | UserID={uid} | Dept={dept} | Role={role}")

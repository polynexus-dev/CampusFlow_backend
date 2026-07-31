import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

session = requests.Session()
r = session.post(f"{BASE_URL}/api/login/", json={"username": "demo_admin", "password": "Password123"}, verify=False)
token = r.json().get("access")
headers = {"Authorization": f"Bearer {token}"}

res = session.get(f"{BASE_URL}/api/college/employees/?search=Computer", headers=headers, verify=False).json()
items = res.get("results", []) if isinstance(res, dict) else res
print(f"CS employees count: {len(items)}")
for emp in items[:10]:
    u = emp.get("user", {})
    uname = u.get("username") if isinstance(u, dict) else emp.get("username")
    uid = emp.get("id") or (u.get("id") if isinstance(u, dict) else None)
    dept = emp.get("department")
    role = emp.get("role")
    print(f"  username={uname} | ID={uid} | Dept={dept} | Role={role}")

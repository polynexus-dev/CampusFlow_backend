import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

session = requests.Session()
r = session.post(f"{BASE_URL}/api/login/", json={"username": "demo_admin", "password": "Password123"}, verify=False)
token = r.json().get("access")
headers = {"Authorization": f"Bearer {token}"}

res = session.get(f"{BASE_URL}/api/teaching-staff/user/", headers=headers, verify=False).json()
items = res.get("results", []) if isinstance(res, dict) else res

print(f"Total faculty records: {len(items)}")
for i in items:
    print(i)

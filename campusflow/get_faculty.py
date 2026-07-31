import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

session = requests.Session()
r = session.post(f"{BASE_URL}/api/login/", json={"username": "demo_admin", "password": "Password123"}, verify=False)
token = r.json().get("access")
headers = {"Authorization": f"Bearer {token}"}

staff_res = session.get(f"{BASE_URL}/api/teaching-staff/user/", headers=headers, verify=False).json()
print("Staff list structure sample:")
print(json.dumps(staff_res, indent=2)[:800])

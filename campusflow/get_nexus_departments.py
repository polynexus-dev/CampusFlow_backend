import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

session = requests.Session()
r = session.post(f"{BASE_URL}/api/login/", json={"username": "demo_admin", "password": "Password123"}, verify=False)
token = r.json().get("access")
headers = {"Authorization": f"Bearer {token}"}

res = session.get(f"{BASE_URL}/api/department/", headers=headers, verify=False)
print("DEPARTMENTS ON API.CAMPUSNEXUS.IN:")
try:
    depts = res.json()
    if isinstance(depts, dict) and "results" in depts:
        depts = depts["results"]
    for d in depts:
        print(f"  ID: {d.get('id')} | Name: '{d.get('name')}' | Code: '{d.get('code')}'")
except Exception as e:
    print(res.text[:300])

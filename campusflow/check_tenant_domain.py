import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def check_tenant_info():
    session = requests.Session()
    r = session.post(f"{BASE_URL}/api/login/", json={"username": "demo_admin", "password": "Password123"}, verify=False)
    token = r.json().get("access")
    headers = {"Authorization": f"Bearer {token}"}

    res = session.get(f"{BASE_URL}/api/tenant/settings/", headers=headers, verify=False)
    print("Tenant Settings Output:")
    print(res.text)

if __name__ == "__main__":
    check_tenant_info()

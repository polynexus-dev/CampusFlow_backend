import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def verify_all():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"
    res = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False, timeout=10)
    token = res.json().get("access")
    headers = {"Authorization": f"Bearer {token}"}

    endpoints = [
        "/api/schedules/",
        "/api/lectures/",
        "/api/assignments/",
        "/api/announcements/",
        "/api/books/",
    ]

    print("VERIFYING LIVE ENDPOINTS ON API.CAMPUSNEXUS.IN:")
    for ep in endpoints:
        r = session.get(f"{BASE_URL}{ep}", headers=headers, verify=False)
        data = r.json()
        count = len(data) if isinstance(data, list) else (len(data.get("results")) if isinstance(data, dict) and "results" in data else "N/A")
        print(f"  [+] GET {ep} -> Status: {r.status_code} | Total Items: {count}")

if __name__ == "__main__":
    verify_all()

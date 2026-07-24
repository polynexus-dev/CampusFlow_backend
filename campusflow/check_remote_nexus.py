import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def check_remote_data():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"
    r = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False, timeout=10)
    data = r.json()
    token = data.get("access")
    print(f"Logged in! Token obtained.")

    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    endpoints_to_check = [
        "/api/schedules/",
        "/api/lectures/",
        "/api/courses/",
        "/api/classrooms/",
        "/api/departments/",
        "/api/assignments/",
        "/api/announcements/",
        "/api/library/books/",
        "/api/library/issues/",
    ]

    for ep in endpoints_to_check:
        res = session.get(f"{BASE_URL}{ep}", headers=headers, verify=False, timeout=10)
        print(f"\n--- GET {ep} (Status: {res.status_code}) ---")
        try:
            print(json.dumps(res.json(), indent=2)[:500])
        except Exception:
            print(res.text[:300])

if __name__ == "__main__":
    check_remote_data()

import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def inspect_student():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"
    
    passwords_to_try = ["Password123", "admin123", "student123", "demo123", "password"]
    token = None
    user_info = None

    for pwd in passwords_to_try:
        print(f"Trying login for 'demo_student' with password '{pwd}'...")
        r = session.post(login_url, json={"username": "demo_student", "password": pwd}, verify=False, timeout=5)
        if r.status_code == 200:
            user_info = r.json()
            token = user_info.get("access")
            print(f"[+] Login SUCCESS for demo_student with password '{pwd}'!")
            break
        else:
            print(f"  Status: {r.status_code} - {r.text[:200]}")

    if not token:
        print("[-] Failed to log in as demo_student with tried passwords.")
        return

    headers = {"Authorization": f"Bearer {token}"}

    # 1. Fetch Profile
    print("\n--- 1. DEMO_STUDENT PROFILE ---")
    prof_r = session.get(f"{BASE_URL}/api/user/", headers=headers, verify=False)
    print(f"GET /api/user/ -> Status {prof_r.status_code}")
    try:
        print(json.dumps(prof_r.json(), indent=2))
    except Exception:
        print(prof_r.text)

    # 2. Test Endpoints as demo_student
    endpoints = [
        "/api/schedules/",
        "/api/lectures/",
        "/api/assignments/",
        "/api/announcements/",
        "/api/books/",
    ]

    print("\n--- 2. ENDPOINTS VIEWED BY DEMO_STUDENT ---")
    for ep in endpoints:
        r = session.get(f"{BASE_URL}{ep}", headers=headers, verify=False)
        print(f"\nGET {ep} -> Status: {r.status_code}")
        try:
            res_json = r.json()
            count = len(res_json) if isinstance(res_json, list) else len(res_json.get("results", [])) if isinstance(res_json, dict) else "N/A"
            print(f"  Items Count: {count}")
            print(f"  Sample: {json.dumps(res_json, indent=2)[:500]}")
        except Exception:
            print(r.text[:300])

if __name__ == "__main__":
    inspect_student()

import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def activate_johndoe():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"

    # 1. Login as demo_admin
    r_admin = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False)
    token_admin = r_admin.json().get("access")
    headers_admin = {"Authorization": f"Bearer {token_admin}", "Content-Type": "application/json"}

    # 2. Get student profile ID for student_johndoe
    stu_res = session.get(f"{BASE_URL}/api/student/user/", headers=headers_admin, verify=False).json()
    students = stu_res.get("results", []) if isinstance(stu_res, dict) else stu_res

    target_profile_id = None
    for s in students:
        u = s.get("user", {})
        uname = u.get("username") if isinstance(u, dict) else u
        if uname == "student_johndoe":
            target_profile_id = s.get("id")
            break

    print(f"[+] Found student_johndoe profile ID: {target_profile_id}")

    if target_profile_id:
        update_payload = {
            "id": target_profile_id,
            "status": "active",
            "is_active": True,
            "department_id": 1,
            "program_enrolled_in": "B.Tech CS"
        }
        u_res = session.put(f"{BASE_URL}/api/student/user/", json=update_payload, headers=headers_admin, verify=False)
        print(f"[+] Activation update status: {u_res.status_code} - {u_res.text[:200]}")

    # 3. Test Login for student_johndoe
    print("\n[+] Testing login for student_johndoe...")
    r_login = session.post(login_url, json={"username": "student_johndoe", "password": "SecurePassword123!"}, verify=False)
    print(f"Login Status: {r_login.status_code}")
    if r_login.status_code == 200:
        print("[SUCCESS] student_johndoe is ACTIVATED and logged in successfully!")
        data = r_login.json()
        print(f"User: {data.get('user')} | Role: {data.get('roleName')} | Department: {data.get('profile', {}).get('department_id')}")
    else:
        print(f"Login Failed: {r_login.text}")

if __name__ == "__main__":
    activate_johndoe()

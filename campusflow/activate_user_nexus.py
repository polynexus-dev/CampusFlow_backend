import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def check_and_activate_user():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"

    # 1. Try logging in as student_johndoe first to see error
    print("Testing login for student_johndoe...")
    r_login = session.post(login_url, json={"username": "student_johndoe", "password": "SecurePassword123!"}, verify=False)
    print(f"Login Status: {r_login.status_code}")
    print(f"Login Response: {r_login.text}")

    # 2. Login as demo_admin
    r_admin = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False)
    token_admin = r_admin.json().get("access")
    headers_admin = {"Authorization": f"Bearer {token_admin}", "Content-Type": "application/json"}

    # 3. Find student_johndoe in student profile list or pending approvals list
    # Check pending approvals
    pending_res = session.get(f"{BASE_URL}/api/approvals/pending/", headers=headers_admin, verify=False)
    print(f"\nGET /api/approvals/pending/ Status: {pending_res.status_code}")
    try:
        print("Pending Approvals:")
        print(json.dumps(pending_res.json(), indent=2)[:500])
    except Exception:
        print(pending_res.text[:200])

    # Check student list
    stu_res = session.get(f"{BASE_URL}/api/student/user/", headers=headers_admin, verify=False).json()
    students = stu_res.get("results", []) if isinstance(stu_res, dict) else stu_res

    target_profile_id = None
    target_username = None

    for s in students:
        u = s.get("user", {})
        uname = u.get("username") if isinstance(u, dict) else u
        if uname == "student_johndoe":
            target_profile_id = s.get("id")
            target_username = uname
            print(f"\nFound student_johndoe profile #{target_profile_id} (status: {s.get('status')})")
            break

    # 4. Activate student_johndoe via PUT /api/student/user/ or approve_user endpoint
    if target_profile_id:
        update_payload = {
            "id": target_profile_id,
            "status": "active",
            "is_active": True,
            "department_id": 1
        }
        u_res = session.put(f"{BASE_URL}/api/student/user/", json=update_payload, headers=headers_admin, verify=False)
        print(f"Update response status: {u_res.status_code} - {u_res.text}")

    # 5. Retry login for student_johndoe
    print("\nRetrying login for student_johndoe after activation...")
    r_retry = session.post(login_url, json={"username": "student_johndoe", "password": "SecurePassword123!"}, verify=False)
    print(f"Retry Login Status: {r_retry.status_code}")
    print(f"Retry Login Response: {r_retry.text}")

if __name__ == "__main__":
    check_and_activate_user()

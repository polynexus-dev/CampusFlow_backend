import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def register_and_activate():
    session = requests.Session()

    # 1. Register student_johndoe
    reg_url = f"{BASE_URL}/api/register/student/"
    reg_payload = {
        "username": "student_johndoe",
        "email": "johndoe@demo.localhost",
        "password": "SecurePassword123!",
        "password2": "SecurePassword123!",
        "first_name": "John",
        "last_name": "Doe",
        "role": "student",
        "student_id": "STU-JD999",
        "department_id": 1,
        "program_enrolled_in_id": "B.Tech CS",
        "date_of_birth": "2003-01-01",
        "consent_given": True
    }

    print("Registering student_johndoe...")
    r_reg = session.post(reg_url, json=reg_payload, verify=False)
    print(f"Registration Status: {r_reg.status_code}")
    print(f"Registration Response: {r_reg.text}")

    # 2. Login as demo_admin
    login_url = f"{BASE_URL}/api/login/"
    r_admin = session.post(login_url, json={"username": "demo_admin", "password": "Password123"}, verify=False)
    token_admin = r_admin.json().get("access")
    headers_admin = {"Authorization": f"Bearer {token_admin}", "Content-Type": "application/json"}

    # 3. Find student_johndoe in student profile list and activate
    stu_res = session.get(f"{BASE_URL}/api/student/user/?search=johndoe", headers=headers_admin, verify=False).json()
    students = stu_res.get("results", []) if isinstance(stu_res, dict) else stu_res

    target_profile_id = None
    for s in students:
        u = s.get("user", {})
        uname = u.get("username") if isinstance(u, dict) else u
        if uname == "student_johndoe":
            target_profile_id = s.get("id")
            break

    if not target_profile_id:
        # Check all students
        stu_all = session.get(f"{BASE_URL}/api/student/user/", headers=headers_admin, verify=False).json()
        all_stus = stu_all.get("results", []) if isinstance(stu_all, dict) else stu_all
        for s in all_stus:
            u = s.get("user", {})
            uname = u.get("username") if isinstance(u, dict) else u
            if uname == "student_johndoe":
                target_profile_id = s.get("id")
                break

    print(f"Found student_johndoe profile ID: {target_profile_id}")

    if target_profile_id:
        update_payload = {
            "id": target_profile_id,
            "status": "active",
            "is_active": True,
            "department_id": 1,
            "program_enrolled_in": "B.Tech CS"
        }
        u_res = session.put(f"{BASE_URL}/api/student/user/", json=update_payload, headers=headers_admin, verify=False)
        print(f"Activation update status: {u_res.status_code} - {u_res.text}")

    # 4. Test Login for student_johndoe
    print("\nTesting login for student_johndoe after activation...")
    r_login = session.post(login_url, json={"username": "student_johndoe", "password": "SecurePassword123!"}, verify=False)
    print(f"Login Status: {r_login.status_code}")
    print(f"Login Response: {r_login.text}")

    if r_login.status_code == 200:
        token_stu = r_login.json().get("access")
        headers_stu = {"Authorization": f"Bearer {token_stu}"}
        print("\nVerifying student_johndoe dashboard data visibility:")
        endpoints = ["/api/schedules/", "/api/lectures/", "/api/assignments/", "/api/announcements/"]
        for ep in endpoints:
            res = session.get(f"{BASE_URL}{ep}", headers=headers_stu, verify=False)
            items = res.json()
            count = len(items) if isinstance(items, list) else len(items.get("results", [])) if isinstance(items, dict) else "N/A"
            print(f"  [+] GET {ep} -> Status: {res.status_code} | Items Visible: {count}")

if __name__ == "__main__":
    register_and_activate()

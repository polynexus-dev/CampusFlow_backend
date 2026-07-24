import requests
import random
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def test_auto_activate():
    session = requests.Session()
    uname = f"student_auto_{random.randint(1000, 9999)}"
    email = f"{uname}@demo.localhost"

    payload = {
        "username": uname,
        "email": email,
        "password": "SecurePassword123!",
        "password2": "SecurePassword123!",
        "first_name": "Test",
        "last_name": "User",
        "role": "student",
        "student_id": f"STU-{random.randint(1000, 9999)}",
        "department_id": 1,
        "program_enrolled_in_id": "B.Tech CS",
        "date_of_birth": "2003-01-01",
        "consent_given": True
    }

    print(f"Registering student '{uname}' on api.campusnexus.in...")
    reg_res = session.post(f"{BASE_URL}/api/register/student/", json=payload, verify=False)
    print(f"Registration Status: {reg_res.status_code}")
    print(f"Registration Response: {reg_res.text}")

    if reg_res.status_code in [200, 201]:
        print("\nAttempting IMMEDIATE login without OTP activation...")
        login_res = session.post(f"{BASE_URL}/api/login/", json={"username": uname, "password": "SecurePassword123!"}, verify=False)
        print(f"Login Status: {login_res.status_code}")
        if login_res.status_code == 200:
            print("[+] SUCCESS! Demo account auto-activated and logged in immediately!")
            print(f"Login User Details: {login_res.json().get('user')}")
        else:
            print(f"Login Response: {login_res.text}")

if __name__ == "__main__":
    test_auto_activate()

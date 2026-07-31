import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def test_face_reg():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/login/"

    # Login as student_johndoe
    r = session.post(login_url, json={"username": "student_johndoe", "password": "SecurePassword123!"}, verify=False)
    if r.status_code != 200:
        print(f"Login failed: {r.status_code} - {r.text}")
        return

    token = r.json().get("access")
    headers = {"Authorization": f"Bearer {token}"}

    print("Testing GET /api/register-face/...")
    get_r = session.get(f"{BASE_URL}/api/register-face/", headers=headers, verify=False)
    print(f"GET Status: {get_r.status_code}")

    print("\nTesting POST /api/register-face/ (without consent)...")
    post_r1 = session.post(f"{BASE_URL}/api/register-face/", headers=headers, verify=False)
    print(f"POST Status without consent: {post_r1.status_code}")
    print(f"Response: {post_r1.text[:300]}")

    print("\nTesting POST /api/register-face/ (with consent, missing images)...")
    post_r2 = session.post(f"{BASE_URL}/api/register-face/", data={"biometric_consent_given": "true"}, headers=headers, verify=False)
    print(f"POST Status with consent: {post_r2.status_code}")
    print(f"Response: {post_r2.text[:300]}")

if __name__ == "__main__":
    test_face_reg()

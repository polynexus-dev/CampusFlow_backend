import os
import sys
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="ignore").decode("ascii"))


def test_login(username="demo_admin", password="admin123", host="https://api.campusnexus.in"):
    login_url = f"{host.rstrip('/')}/api/login/"
    headers = {
        "Content-Type": "application/json",
        "Host": "api.campusnexus.in",
    }
    payload = {
        "username": username,
        "password": password,
    }


    _print(f"🔐 Testing login for user '{username}' with password '{password}'...")
    _print(f"URL: {login_url}")

    try:
        res = requests.post(
            login_url, json=payload, headers=headers, verify=False, timeout=10
        )
        _print(f"Status Code: {res.status_code}")
        _print(f"Response Body: {res.text}")
        if res.status_code == 200:
            data = res.json()
            _print(
                f"✅ Login SUCCESS! User ID: {data.get('user_id')}, Tenant: "
                f"{data.get('tenant_schema')}"
            )
        else:
            _print(f"❌ Login FAILED ({res.status_code}): {res.text}")
    except Exception as e:
        _print(f"⚠️ Request exception: {e}")


if __name__ == "__main__":
    uname = sys.argv[1] if len(sys.argv) > 1 else "demo_admin"
    pwd = sys.argv[2] if len(sys.argv) > 2 else "admin123"
    base = sys.argv[3] if len(sys.argv) > 3 else "https://api.campusnexus.in"
    test_login(uname, pwd, base)

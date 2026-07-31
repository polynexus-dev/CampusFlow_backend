import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

candidate_urls = [
    "/api/auth/login/",
    "/api/users/login/",
    "/api/login/",
    "/api/token/",
    "/api/token/obtain/",
    "/api/v1/auth/login/",
    "/api/v1/login/",
    "/api/swagger/",
    "/swagger/",
    "/redoc/",
    "/api/schema/",
]

creds = {"username": "demo_admin", "password": "Password123"}
# Also test email login
creds_email = {"email": "demo_admin@campusnexus.in", "password": "Password123"}

session = requests.Session()

for path in candidate_urls:
    url = f"{BASE_URL}{path}"
    try:
        r = session.post(url, json=creds, verify=False, timeout=5)
        print(f"POST {path} -> Status: {r.status_code}")
        if r.status_code != 404:
            print(f"  Body: {r.text[:300]}")
    except Exception as e:
        print(f"Error {path}: {e}")

    try:
        r_get = session.get(url, verify=False, timeout=5)
        if r_get.status_code == 200:
            print(f"GET {path} -> 200 OK (Swagger/Docs found!)")
    except Exception:
        pass

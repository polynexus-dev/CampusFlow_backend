import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

endpoints = [
    "http://13.235.143.251",
    "http://13.235.143.251:8000",
    "http://13.235.143.251:8200",
    "https://campusflow.polynexus.in",
    "https://api.campusflow.polynexus.in",
    "http://localhost:8000",
    "http://localhost:8200",
]

print("Checking VM and Local Endpoints...")
for base in endpoints:
    url = f"{base}/api/auth/token/"
    try:
        r = requests.post(url, json={"username": "demo_admin", "password": "admin123"}, verify=False, timeout=4)
        print(f"URL: {url} -> Status: {r.status_code}")
        if r.status_code == 200:
            print(f"  SUCCESS ON {base}!")
    except Exception as e:
        print(f"URL: {url} -> Failed ({e})")

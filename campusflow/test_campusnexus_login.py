import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def test_remote():
    session = requests.Session()
    login_url = f"{BASE_URL}/api/token/"
    login_payload = {"username": "demo_admin", "password": "Password123"}

    print(f"Connecting to {login_url}...")
    try:
        res = session.post(login_url, json=login_payload, verify=False, timeout=10)
        print(f"Status: {res.status_code}")
        print(f"Response: {res.text[:500]}")
    except Exception as e:
        print(f"Error: {e}")
        # Try http if https failed
        login_url_http = "http://api.campusnexus.in/api/token/"
        print(f"\nTrying HTTP: {login_url_http}...")
        try:
            res = session.post(login_url_http, json=login_payload, timeout=10)
            print(f"Status: {res.status_code}")
            print(f"Response: {res.text[:500]}")
        except Exception as e2:
            print(f"HTTP Error: {e2}")

if __name__ == "__main__":
    test_remote()

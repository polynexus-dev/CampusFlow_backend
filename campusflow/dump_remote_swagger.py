import requests
import json
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE_URL = "https://api.campusnexus.in"

def dump_swagger():
    res = requests.get(f"{BASE_URL}/swagger/?format=openapi", verify=False)
    if res.status_code == 200:
        data = res.json()
        paths = list(data.get("paths", {}).keys())
        print(f"Found {len(paths)} API paths from OpenAPI schema:")
        for p in sorted(paths):
            print(f"  {p}")
    else:
        print(f"Failed to fetch openapi: {res.status_code}")

if __name__ == "__main__":
    dump_swagger()

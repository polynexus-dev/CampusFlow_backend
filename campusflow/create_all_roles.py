"""
CampusFlow — Create All Roles Script
=====================================
Creates one dummy staff user for every role in the system.
Auto-logs in to get a fresh token — no need to paste tokens manually.

HOW TO USE:
  1. Set ENV = "local" or "production"
  2. Set PRODUCTION_URL to your VM/server domain
  3. Set LOGIN_USERNAME and LOGIN_PASSWORD (Management or SaaS Admin account)
  4. Set EMAIL_DOMAIN to your tenant's permitted email domain
  5. Set DEPARTMENT_ID to an existing department ID
  6. Run:  python create_all_roles.py
"""

import requests
import json

# -----------------------------------------------------------------
#  CONFIGURE HERE
# -----------------------------------------------------------------
                        # "local" or "production"
ENV = "production"
LOCAL_URL      = "http://localhost:8000/api"
PRODUCTION_URL = "https://api.campusnexus.in/api"

BASE_URL = (PRODUCTION_URL if ENV == "production" else LOCAL_URL).rstrip("/")

# Login credentials (Management or SaaS Admin)
LOGIN_USERNAME = "swapnil"           # <- change to your admin username
LOGIN_PASSWORD = "swapnil"            # <- change to your admin password

# Tenant's permitted email domain
EMAIL_DOMAIN = "ghrietn.in"    # <- change to your tenant domain

# Department ID used for Faculty and Department Head roles
DEPARTMENT_ID = 1                      # <- change to a valid department ID

# Default password for all dummy accounts
DEFAULT_PASSWORD = "passward123"

# -----------------------------------------------------------------

REGISTER_STAFF_URL = f"{BASE_URL}/register/staff/"
LOGIN_URL          = f"{BASE_URL}/login/"


    # def get_token():
    #     """Auto-login and return a fresh access token."""
    #     print(f"  Logging in as '{LOGIN_USERNAME}'...")
    #     try:
    #         resp = requests.post(
    #             LOGIN_URL,
    #             json={"username": LOGIN_USERNAME, "password": LOGIN_PASSWORD},
    #             timeout=15
    #         )
    #         if resp.status_code == 200:
    #             data = resp.json()
    #             token = data.get("access") or data.get("access_token")
    #             if token:
    #                 print(f"  Token obtained successfully.\n")
    #                 return token
    #             print(f"  ERROR: No 'access' key in login response: {data}")
    #         else:
    #             print(f"  LOGIN FAILED {resp.status_code}: {resp.text}")
    #     except Exception as e:
    #         print(f"  Login error: {e}")
    #     return None


# Role definitions: (role_name, username_suffix, needs_department)
ROLES = [
    # Teaching / Academic roles
    ("Faculty",               "faculty_dummy",       True),
    ("Department Head",       "hod_dummy",           True),
    ("Principal",             "principal_dummy",     False),

    # Admin roles
    ("Administrator",         "admin_dummy",         False),

    # Non-teaching staff roles
    ("Support Staff",         "support_dummy",       False),
    ("Librarian",             "librarian_dummy",     False),
    ("Hostel Warden",         "warden_dummy",        False),
    ("Store Manager",         "store_dummy",         False),
    ("Placement Officer",     "placement_dummy",     False),
    ("Fee Counter",           "feecounter_dummy",    False),
    ("Transport Coordinator", "transport_dummy",     False),
    ("Payroll Officer",       "payroll_dummy",       False),
    ("Admissions Officer",    "admissions_dummy",    False),
    ("Scholarship Officer",   "scholarship_dummy",   False),
    ("Accounts Officer",      "accounts_dummy",      False),
]


def build_payload(role, username, needs_department):
    payload = {
        "username":        username,
        "email":           f"{username}@{EMAIL_DOMAIN}",
        "password":        DEFAULT_PASSWORD,
        "password2":       DEFAULT_PASSWORD,
        "role":            role,
        "employee_id":     f"EMP-{username.upper()[:12]}",
        "first_name":      role.split()[0],
        "last_name":       "Dummy",
        "consent_given":   True,
        "consent_version": "v1.0",
    }
    if needs_department:
        payload["department_id"] = DEPARTMENT_ID
    return payload


def create_role(role, username, needs_department, headers):
    payload = build_payload(role, username, needs_department)
    try:
        resp = requests.post(REGISTER_STAFF_URL, headers=headers, json=payload, timeout=15)
        if resp.status_code in (200, 201):
            print(f"  OK   {role:<25}  created  ({username}@{EMAIL_DOMAIN})")
        else:
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            print(f"  FAIL {role:<25}  {resp.status_code}  {json.dumps(err)}")
    except requests.exceptions.ConnectionError:
        print(f"  ERR  {role:<25}  Connection error — is server running at {BASE_URL}?")
    except Exception as e:
        print(f"  ERR  {role:<25}  {e}")


def main():
    print("=" * 62)
    print("  CampusFlow — Create All Roles")
    print(f"  ENV         : {ENV.upper()}")
    print(f"  BASE_URL    : {BASE_URL}")
    print(f"  EMAIL_DOMAIN: {EMAIL_DOMAIN}")
    print(f"  DEPT_ID     : {DEPARTMENT_ID}")
    print("=" * 62)

    token = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ0b2tlbl90eXBlIjoiYWNjZXNzIiwiZXhwIjoxNzkyNDQxOTUyLCJpYXQiOjE3OTI0MTMxNTIsImp0aSI6IjI5ZGE1M2Q2NWU4ODRiYWJhZmM5NjdiMGQzNTgxMjc3IiwidXNlcl9pZCI6MSwidGVuYW50X3NjaGVtYSI6ImdocmlldCJ9.JUMmH8KbmSXQSKVnny9qSw65NTu6xWgG2ORIyNhPaZQ"
    if not token:
        print("  ABORTED: Could not obtain a valid token.")
        return

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    for role, username, needs_dept in ROLES:
        create_role(role, username, needs_dept, headers)

    print("=" * 62)
    print(f"  Done.  Default password for all accounts: {DEFAULT_PASSWORD}")
    print("=" * 62)


if __name__ == "__main__":
    main()

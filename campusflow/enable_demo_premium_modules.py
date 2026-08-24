"""
Run on the VM with: python manage.py shell < enable_demo_premium_modules.py

Adds every premium module Administrator's role can see to the demo
tenant's subscribed_modules, EXCEPT "audit-portal" -- that one is the CA
role's dedicated namespace (RESTRICTED_ROLE_MODULES in
campusflow_app/views/module_permissions.py) and must never be subscribed
for a tenant whose only real users are Administrator/Management, or it
would (previously did, before today's fix) leak into their sidebar too.
"""
from django_tenants.utils import schema_context
from tenants.models import Tenant

MODULES_TO_ADD = [
    "Compliance Center",
    "Ledger",
    "Scholarship",
    "AI Valuation",
    "At-Risk Prediction",
    "Admissions",
    "Timetable Generation",
    "Syllabus Tracker",
]

with schema_context("public"):
    tenant = Tenant.objects.get(schema_name="demo")
    current = set(tenant.subscribed_modules or [])
    tenant.subscribed_modules = sorted(current | set(MODULES_TO_ADD))
    tenant.save()
    print("demo.subscribed_modules is now:")
    for m in tenant.subscribed_modules:
        print(f"  - {m}")

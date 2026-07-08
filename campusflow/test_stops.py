import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
django.setup()

from django_tenants.utils import schema_context
from campusflow_app.models import BusRoute

with schema_context("demo"):
    for r in BusRoute.objects.all():
        print(f"Route ID: {r.id}, Name: {r.name}, Stops type: {type(r.stops)}, Stops: {r.stops}")

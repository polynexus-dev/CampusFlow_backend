"""
Celery app for CampusFlow.

Only used today to move the CPU-bound face-recognition pipeline
(liveness + motion checks + ArcFace embedding extraction) out of the
request/response cycle and into a separately-scalable worker pool — see
campusflow_app/tasks.py. The Django view still calls the task synchronously
via `.get(timeout=...)`, so the API contract (an immediate response) is
unchanged; only *where* the CPU work runs has moved.
"""

import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")

app = Celery("campusflow")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

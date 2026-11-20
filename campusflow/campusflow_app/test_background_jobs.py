"""Background jobs API + app-version endpoint."""

import json
from unittest import mock

from django.contrib.auth.models import Group, User
from django.urls import reverse
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models.audit import AuditLog
from .models.background_job import BackgroundJob
from .tasks import run_background_job


class BackgroundJobAPITests(TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ("Administrator", "student"):
                Group.objects.get_or_create(name=role)
            self.admin = User.objects.create_user(username="admin_jobs", password="pw12345!")
            self.admin.groups.add(Group.objects.get(name="Administrator"))
            self.student = User.objects.create_user(username="student_jobs", password="pw12345!")
            self.student.groups.add(Group.objects.get(name="student"))
            AuditLog.objects.create(user=self.admin, action="LOGIN", model_name="User", object_id="1", object_repr="admin_jobs")

    def _auth(self, user):
        token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

    def _start(self, user, kind="audit_log_csv"):
        # Run the Celery task inline instead of queueing it.
        with mock.patch.object(
            run_background_job, "delay",
            side_effect=lambda schema, job_id: run_background_job(schema, job_id),
        ):
            return self.client.post(
                reverse("background-jobs"), json.dumps({"kind": kind, "params": {}}),
                content_type="application/json", **self._auth(user),
            )

    def test_admin_export_runs_and_downloads(self):
        res = self._start(self.admin)
        self.assertEqual(res.status_code, status.HTTP_202_ACCEPTED)
        job_id = res.json()["id"]

        poll = self.client.get(reverse("background-job-detail", args=[job_id]), **self._auth(self.admin))
        self.assertEqual(poll.status_code, 200)
        body = poll.json()
        self.assertEqual(body["status"], "done")
        self.assertEqual(body["progress"], 100)
        self.assertEqual(body["result_url"], f"api/jobs/{job_id}/download/")

        dl = self.client.get(reverse("background-job-download", args=[job_id]), **self._auth(self.admin))
        self.assertEqual(dl.status_code, 200)
        content = b"".join(dl.streaming_content).decode("utf-8-sig")
        self.assertIn("admin_jobs", content)

    def test_student_cannot_start_admin_export(self):
        res = self._start(self.student)
        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)

    def test_unknown_kind_rejected(self):
        res = self._start(self.admin, kind="does_not_exist")
        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)

    def test_users_cannot_see_each_others_jobs(self):
        with schema_context(self.tenant.schema_name):
            job = BackgroundJob.objects.create(kind="audit_log_csv", requested_by=self.admin)
        res = self.client.get(reverse("background-job-detail", args=[job.id]), **self._auth(self.student))
        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_too_many_active_jobs_is_rate_limited(self):
        with schema_context(self.tenant.schema_name):
            for _ in range(3):
                BackgroundJob.objects.create(kind="audit_log_csv", requested_by=self.admin, status="running")
        res = self.client.post(
            reverse("background-jobs"), json.dumps({"kind": "audit_log_csv"}),
            content_type="application/json", **self._auth(self.admin),
        )
        self.assertEqual(res.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(res["Retry-After"], "30")


class AppVersionTests(TenantTestCase):
    def test_public_and_env_driven(self):
        with mock.patch.dict("os.environ", {"MOBILE_LATEST_VERSION": "1.4.0", "MOBILE_MIN_SUPPORTED_VERSION": "1.2.0"}):
            res = self.client.get(reverse("app-version"))
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.json()["latest_version"], "1.4.0")
        self.assertEqual(res.json()["min_supported_version"], "1.2.0")

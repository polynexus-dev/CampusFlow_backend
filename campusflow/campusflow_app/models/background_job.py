from django.conf import settings
from django.db import models


class BackgroundJob(models.Model):
    """
    One long-running task a user asked for (a big export, a report) that
    runs on the Celery "background" queue instead of inside the request.

    The web and mobile apps poll GET /api/jobs/<id>/ for
    {status, progress, message, result_url, error} and let the user keep
    working meanwhile (the "Background processing" UI state). What a job
    actually does is looked up by `kind` in services/background_jobs.py.
    """

    STATUS_PENDING = "pending"
    STATUS_RUNNING = "running"
    STATUS_DONE = "done"
    STATUS_FAILED = "failed"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_RUNNING, "Running"),
        (STATUS_DONE, "Done"),
        (STATUS_FAILED, "Failed"),
    ]

    kind = models.CharField(max_length=64, help_text="Key into services.background_jobs.JOB_HANDLERS.")
    label = models.CharField(max_length=200, blank=True, help_text="Human-readable name shown in the UI.")
    params = models.JSONField(default=dict, blank=True)
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="background_jobs",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    progress = models.PositiveSmallIntegerField(null=True, blank=True, help_text="0-100, when known.")
    message = models.CharField(max_length=255, blank=True, help_text="Current step, e.g. 'Writing rows 2,000 of 9,000'.")
    result_file = models.FileField(upload_to="background_jobs/%Y/%m/", null=True, blank=True)
    result_filename = models.CharField(max_length=255, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "background_jobs"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["requested_by", "-created_at"])]

    def __str__(self):
        return f"{self.kind} #{self.pk} ({self.status})"

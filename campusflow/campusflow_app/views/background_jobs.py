"""
Background job endpoints (the "Background processing" UI state).

  POST /api/jobs/                {kind, params}  -> 202 {id, status, ...}
  GET  /api/jobs/                my recent jobs
  GET  /api/jobs/<id>/           poll: {status, progress, message, result_url, error}
  GET  /api/jobs/<id>/download/  the finished file

Users only ever see their own jobs. What a `kind` does and who may start it
lives in services/background_jobs.py.
"""

from django.db import connection
from django.http import FileResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.background_job import BackgroundJob
from ..services.background_jobs import JOB_HANDLERS

# Stop one user queueing dozens of heavy exports at once.
MAX_ACTIVE_JOBS_PER_USER = 3


def serialize_job(job):
    done = job.status == BackgroundJob.STATUS_DONE and job.result_file
    return {
        "id": job.id,
        "kind": job.kind,
        "label": job.label,
        "status": job.status,
        "progress": job.progress,
        "message": job.message,
        "error": job.error or None,
        "result_url": f"api/jobs/{job.id}/download/" if done else None,
        "result_filename": job.result_filename or None,
        "created_at": job.created_at.isoformat(),
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


class BackgroundJobListCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        jobs = BackgroundJob.objects.filter(requested_by=request.user)[:20]
        return Response([serialize_job(j) for j in jobs])

    def post(self, request):
        kind = request.data.get("kind")
        params = request.data.get("params") or {}
        handler = JOB_HANDLERS.get(kind)
        if handler is None:
            return Response({"error": f"Unknown job type '{kind}'."}, status=status.HTTP_400_BAD_REQUEST)
        if not isinstance(params, dict):
            return Response({"error": "params must be an object."}, status=status.HTTP_400_BAD_REQUEST)
        if not handler["can_start"](request.user, params):
            return Response({"error": "You don't have permission to run this export."}, status=status.HTTP_403_FORBIDDEN)

        active = BackgroundJob.objects.filter(
            requested_by=request.user,
            status__in=[BackgroundJob.STATUS_PENDING, BackgroundJob.STATUS_RUNNING],
        ).count()
        if active >= MAX_ACTIVE_JOBS_PER_USER:
            return Response(
                {"error": f"You already have {active} exports running. Wait for one to finish."},
                status=status.HTTP_429_TOO_MANY_REQUESTS,
                headers={"Retry-After": "30"},
            )

        job = BackgroundJob.objects.create(kind=kind, label=handler["label"], params=params, requested_by=request.user)

        from ..tasks import run_background_job
        try:
            run_background_job.delay(connection.schema_name, job.id)
        except Exception:  # broker down — fail visibly instead of leaving a forever-pending job
            job.status = BackgroundJob.STATUS_FAILED
            job.error = "The background worker is unavailable right now. Please try again in a few minutes."
            job.save(update_fields=["status", "error"])
            return Response(serialize_job(job), status=status.HTTP_503_SERVICE_UNAVAILABLE)

        return Response(serialize_job(job), status=status.HTTP_202_ACCEPTED)


class BackgroundJobDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        job = BackgroundJob.objects.filter(pk=pk, requested_by=request.user).first()
        if job is None:
            return Response({"error": "Job not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(serialize_job(job))


class BackgroundJobDownloadView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        job = BackgroundJob.objects.filter(pk=pk, requested_by=request.user).first()
        if job is None or job.status != BackgroundJob.STATUS_DONE or not job.result_file:
            return Response({"error": "This file isn't ready or no longer exists."}, status=status.HTTP_404_NOT_FOUND)
        try:
            handle = job.result_file.open("rb")
        except FileNotFoundError:
            return Response({"error": "This file has expired. Run the export again."}, status=status.HTTP_410_GONE)
        return FileResponse(handle, as_attachment=True, filename=job.result_filename or "export")

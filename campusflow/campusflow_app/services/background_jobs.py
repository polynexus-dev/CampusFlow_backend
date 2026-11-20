"""
Background jobs — what each BackgroundJob `kind` does.

Add a new long-running export/report by writing a handler and registering it
in JOB_HANDLERS. The generic plumbing (POST /api/jobs/ to start, Celery task
run_background_job, GET /api/jobs/<id>/ to poll, /download/ to fetch the
file) needs no changes.

A handler is a dict:
  label      — shown to the user ("Audit log export")
  can_start  — fn(user, params) -> bool; the permission check for starting it
  run        — fn(job, report) -> (filename, bytes); `report(progress, message)`
               updates the job row so the apps can show real progress.
"""

import csv
import io

from ..permissions import is_college_admin, is_saas_admin


# ── Audit log CSV export ───────────────────────────────────────────────────

def _audit_log_csv(job, report):
    from ..models.audit import AuditLog

    p = job.params or {}
    qs = AuditLog.objects.select_related("user").order_by("-timestamp")
    if p.get("date_from"):
        qs = qs.filter(timestamp__date__gte=p["date_from"])
    if p.get("date_to"):
        qs = qs.filter(timestamp__date__lte=p["date_to"])
    if p.get("action"):
        qs = qs.filter(action=str(p["action"]).upper())
    if p.get("model"):
        qs = qs.filter(model_name__icontains=p["model"])

    total = qs.count()
    report(0, f"Exporting {total:,} entries")
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Timestamp", "User", "Action", "Model", "Object ID", "Object", "IP address", "Endpoint"])

    chunk = 2000
    for i, log in enumerate(qs.iterator(chunk_size=chunk), start=1):
        writer.writerow([
            log.timestamp.isoformat(),
            log.user.username if log.user else "System",
            log.action,
            log.model_name,
            log.object_id,
            log.object_repr,
            log.ip_address or "",
            log.endpoint or "",
        ])
        if i % chunk == 0 and total:
            report(min(99, int(i * 100 / total)), f"Writing row {i:,} of {total:,}")

    return "audit-log.csv", buf.getvalue().encode("utf-8-sig")  # BOM so Excel opens UTF-8 correctly


JOB_HANDLERS = {
    "audit_log_csv": {
        "label": "Audit log export",
        "can_start": lambda user, params: is_saas_admin(user) or is_college_admin(user),
        "run": _audit_log_csv,
    },
}

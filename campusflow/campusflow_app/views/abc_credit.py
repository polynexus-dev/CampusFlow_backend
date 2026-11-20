"""
ABC (Academic Bank of Credits) credit entries: list, APAAR readiness check,
the NAD upload CSV, and recording an upload the college made.

Entries are created by services/abc_credit.record_credit_entry() when exam
results are published, not through this API. Phase A of ABC is a CSV the
college uploads on the NAD / DigiLocker portal itself, so nothing here talks
to a government system (see models/abc_credit.py).
"""
import csv
import datetime
import io

from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.abc_credit import ABCCreditEntry, apaar_problem
from ..permissions import IsSaaSOrCollegeAdmin, RequiresModule
from ..serializers import ABCCreditEntrySerializer

ABC_ADMIN_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("compliance-center")]

# Default NAD upload columns. Universities often hand colleges their own
# template; staff then reorder or rename columns in Excel before uploading.
NAD_CSV_HEADER = [
    "APAAR_ID", "ENROLMENT_NO", "STUDENT_NAME", "DATE_OF_BIRTH", "GENDER",
    "PROGRAMME", "SEMESTER", "COURSE_CODE", "COURSE_NAME", "CREDITS_EARNED",
    "GRADE", "ACADEMIC_YEAR",
]


def _entries(request):
    qs = ABCCreditEntry.objects.select_related(
        "student__user", "student__program", "course", "academic_year", "uploaded_by",
    ).all()
    params = request.query_params
    if params.get("student"):
        qs = qs.filter(student_id=params["student"])
    if params.get("academic_year"):
        qs = qs.filter(academic_year_id=params["academic_year"])
    if params.get("sync_status"):
        qs = qs.filter(sync_status=params["sync_status"])
    return qs


def _student_name(student):
    return student.user.get_full_name() or student.user.username


LIST_LIMIT_DEFAULT = 200
LIST_LIMIT_MAX = 1000


class ABCCreditEntryListView(APIView):
    """
    GET /api/abc-credit-entries/?student=&academic_year=&sync_status=&search=&limit=
    A college has one entry per student per course per year (thousands), so
    the list is capped (`limit`, default 200) and returns the full `count`.
    Totals for the whole set come from the readiness view.
    """
    permission_classes = ABC_ADMIN_PERMS

    def get(self, request):
        qs = _entries(request)
        search = (request.query_params.get("search") or "").strip()
        if search:
            qs = qs.filter(
                Q(student__student_id__icontains=search) | Q(student__user__first_name__icontains=search)
                | Q(student__user__last_name__icontains=search) | Q(student__apaar_id__icontains=search)
                | Q(course__course_code__icontains=search)
            )
        try:
            limit = min(max(int(request.query_params.get("limit", LIST_LIMIT_DEFAULT)), 1), LIST_LIMIT_MAX)
        except ValueError:
            limit = LIST_LIMIT_DEFAULT
        return Response({
            "count": qs.count(),
            "results": [ABCCreditEntrySerializer(e).data for e in qs[:limit]],
        })


class ABCReadinessView(APIView):
    """
    GET /api/abc-credit-entries/readiness/?academic_year=
    Pending entries split into ready (valid APAAR ID) and blocked, with the
    students that block them, so the office can fix APAAR IDs before export.
    """
    permission_classes = ABC_ADMIN_PERMS

    def get(self, request):
        entries = _entries(request)
        pending = entries.filter(sync_status=ABCCreditEntry.SYNC_PENDING)
        ready_ids = []
        blocked = {}
        for e in pending:
            problem = apaar_problem(e.student.apaar_id)
            if problem is None:
                ready_ids.append(e.pk)
                continue
            row = blocked.setdefault(e.student_id, {
                "student": e.student_id,
                "student_id_display": e.student.student_id,
                "student_name": _student_name(e.student),
                "apaar_id": e.student.apaar_id or "",
                "problem": problem,
                "pending_entries": 0,
            })
            row["pending_entries"] += 1
        blocked_rows = sorted(blocked.values(), key=lambda r: r["student_id_display"])
        blocked_count = sum(r["pending_entries"] for r in blocked_rows)
        return Response({
            "pending_entries": len(ready_ids) + blocked_count,
            "ready_entries": len(ready_ids),
            # Exactly the entries the export contains right now; the screen
            # keeps this from the moment of download for "mark as uploaded".
            "ready_ids": ready_ids,
            "blocked_entries": blocked_count,
            "blocked_students": blocked_rows,
            "uploaded_entries": entries.filter(sync_status=ABCCreditEntry.SYNC_UPLOADED).count(),
            "synced_entries": entries.filter(sync_status=ABCCreditEntry.SYNC_SYNCED).count(),
        })


class ABCExportView(APIView):
    """
    GET /api/abc-credit-entries/export/?academic_year=
    CSV of pending entries whose student has a valid APAAR ID, for the
    college to upload on the NAD portal. Entries stay pending until someone
    records the upload (mark-uploaded); downloading changes nothing.
    """
    permission_classes = ABC_ADMIN_PERMS

    def get(self, request):
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(NAD_CSV_HEADER)
        count = 0
        for e in _entries(request).filter(sync_status=ABCCreditEntry.SYNC_PENDING):
            s = e.student
            if apaar_problem(s.apaar_id):  # listed by the readiness check instead
                continue
            programme = (s.program.name if s.program_id else "") or (s.program_enrolled_in or "")
            writer.writerow([
                s.apaar_id.strip(), s.student_id, _student_name(s),
                s.date_of_birth.isoformat() if s.date_of_birth else "", s.gender or "",
                programme, e.course.semester_number or "", e.course.course_code, e.course.course_name,
                e.credits_earned, e.grade, e.academic_year.name,
            ])
            count += 1
        # UTF-8 BOM so Excel shows Indian-language names correctly.
        response = HttpResponse("﻿" + buffer.getvalue(), content_type="text/csv; charset=utf-8")
        stamp = timezone.localdate().isoformat()
        response["Content-Disposition"] = f'attachment; filename="abc_nad_upload_{stamp}.csv"'
        response["X-Entry-Count"] = str(count)
        return response


class ABCMarkUploadedView(APIView):
    """
    POST /api/abc-credit-entries/mark-uploaded/
    {"ids": [...], "batch_reference": "...", "uploaded_on": "YYYY-MM-DD"}
    Records that the college uploaded these entries on the NAD portal. Only
    pending entries with a valid APAAR ID change; the rest are reported back.
    """
    permission_classes = ABC_ADMIN_PERMS

    def post(self, request):
        ids = request.data.get("ids")
        batch_reference = (request.data.get("batch_reference") or "").strip()
        if not isinstance(ids, list) or not ids:
            return Response({"error": "Choose at least one entry."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            ids = list(dict.fromkeys(int(i) for i in ids))
        except (TypeError, ValueError):
            return Response({"error": "Entry ids must be numbers."}, status=status.HTTP_400_BAD_REQUEST)
        if not batch_reference:
            return Response(
                {"error": "Enter the batch reference shown on the NAD portal after the upload."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if len(batch_reference) > 100:
            return Response({"error": "Batch reference is too long (100 characters max)."},
                            status=status.HTTP_400_BAD_REQUEST)

        today = timezone.localdate()
        raw_date = request.data.get("uploaded_on")
        if raw_date:
            try:
                uploaded_on = datetime.date.fromisoformat(str(raw_date))
            except ValueError:
                return Response({"error": "Upload date must be YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)
            if uploaded_on > today:
                return Response({"error": "Upload date can't be in the future."}, status=status.HTTP_400_BAD_REQUEST)
        else:
            uploaded_on = today

        marked, skipped = [], []
        with transaction.atomic():
            entries = ABCCreditEntry.objects.select_for_update().select_related("student").filter(pk__in=ids)
            found = set()
            for e in entries:
                found.add(e.pk)
                if e.sync_status != ABCCreditEntry.SYNC_PENDING:
                    skipped.append({"id": e.pk, "reason": f"already {e.get_sync_status_display().lower()}"})
                elif apaar_problem(e.student.apaar_id):
                    skipped.append({"id": e.pk, "reason": f"APAAR ID {apaar_problem(e.student.apaar_id)}"})
                else:
                    e.mark_uploaded(batch_reference, uploaded_on, request.user)
                    marked.append(e.pk)
            skipped += [{"id": i, "reason": "not found"} for i in ids if i not in found]

        return Response({"marked": len(marked), "marked_ids": marked, "skipped": skipped})

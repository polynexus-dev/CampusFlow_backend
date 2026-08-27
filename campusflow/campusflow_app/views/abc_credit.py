"""
ABC credit entries — read/list plus the sync stub. See models/abc_credit.py
for the internal-modeling-only boundary: entries themselves are created by
services/abc_credit.record_credit_entry() at result-publish time, not
through this API — these views are for viewing what's on file and (once a
real integration exists) triggering the sync.
"""
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.abc_credit import ABCCreditEntry
from ..permissions import IsSaaSOrCollegeAdmin, RequiresModule
from ..serializers import ABCCreditEntrySerializer

ABC_ADMIN_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("compliance-center")]


class ABCCreditEntryListView(APIView):
    """GET /api/abc-credit-entries/?student=&academic_year=&sync_status="""
    permission_classes = ABC_ADMIN_PERMS

    def get(self, request):
        qs = ABCCreditEntry.objects.select_related("student__user", "course", "academic_year").all()
        student = request.query_params.get("student")
        academic_year = request.query_params.get("academic_year")
        sync_status_filter = request.query_params.get("sync_status")
        if student:
            qs = qs.filter(student_id=student)
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        if sync_status_filter:
            qs = qs.filter(sync_status=sync_status_filter)
        return Response({"results": [ABCCreditEntrySerializer(e).data for e in qs]})


class SyncABCCreditEntryView(APIView):
    """
    POST /api/abc-credit-entries/<id>/sync/
    Stub — see ABCCreditEntry.sync()'s docstring. Exists so the workflow
    (and its permission boundary) is already wired for when a real ABC
    portal integration replaces the stub body.
    """
    permission_classes = ABC_ADMIN_PERMS

    def post(self, request, pk):
        entry = ABCCreditEntry.objects.filter(pk=pk).first()
        if not entry:
            return Response({"error": "ABC credit entry not found."}, status=status.HTTP_404_NOT_FOUND)
        entry.sync()
        return Response(ABCCreditEntrySerializer(entry).data)

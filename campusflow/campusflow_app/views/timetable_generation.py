"""
campusflow_app/views/timetable_generation.py

Trigger/poll/apply/discard for CP-SAT timetable generation (see
services/timetable_generation.py, models/timetable_generation.py, and the
run_generate_timetable Celery task). Same human-in-the-loop shape as the
other AI/algorithmic features this session: a generation run produces
draft Schedule rows, never live ones, until explicitly applied.
"""

from django.db import connection
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.academics import Term
from ..models.department import Department
from ..models.schedule import Schedule
from ..models.timetable_generation import TimetableGenerationRun
from ..permissions import IsSaaSOrCollegeAdmin
from ..serializers import TimetableGenerationRunSerializer
from ..tasks import run_generate_timetable


class GenerateTimetableView(APIView):
    """POST /timetable/generate/ {"term_id": ..., "department_id": ...?}"""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]

    def post(self, request):
        term_id = request.data.get("term_id")
        if not term_id:
            return Response({"error": "term_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            term = Term.objects.get(pk=term_id)
        except Term.DoesNotExist:
            return Response({"error": "Term not found."}, status=status.HTTP_404_NOT_FOUND)

        department = None
        department_id = request.data.get("department_id")
        if department_id:
            try:
                department = Department.objects.get(pk=department_id)
            except Department.DoesNotExist:
                return Response({"error": "Department not found."}, status=status.HTTP_404_NOT_FOUND)

        run = TimetableGenerationRun.objects.create(term=term, department=department, requested_by=request.user)
        run_generate_timetable.delay(connection.schema_name, run.id)

        return Response(TimetableGenerationRunSerializer(run).data, status=status.HTTP_202_ACCEPTED)


class TimetableGenerationRunViewSet(viewsets.ReadOnlyModelViewSet):
    """List/retrieve generation runs — for polling a pending one and browsing history."""
    queryset = TimetableGenerationRun.objects.select_related("term", "department", "requested_by", "applied_by").all()
    serializer_class = TimetableGenerationRunSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get_queryset(self):
        qs = super().get_queryset()
        term_id = self.request.query_params.get("term")
        if term_id:
            qs = qs.filter(term_id=term_id)
        return qs


class ApplyTimetableGenerationRunView(APIView):
    """POST /timetable-generation-runs/<int:pk>/apply/ — flips the run's draft Schedule rows live."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]

    def post(self, request, pk):
        try:
            run = TimetableGenerationRun.objects.get(pk=pk)
        except TimetableGenerationRun.DoesNotExist:
            return Response({"error": "Generation run not found."}, status=status.HTTP_404_NOT_FOUND)

        if run.status != TimetableGenerationRun.STATUS_COMPLETED:
            return Response(
                {"error": f"Only a completed run can be applied (current status: '{run.status}')."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        Schedule.objects.filter(generation_run=run, is_draft=True).update(is_draft=False)
        run.status = TimetableGenerationRun.STATUS_APPLIED
        run.applied_at = timezone.now()
        run.applied_by = request.user
        run.save(update_fields=["status", "applied_at", "applied_by"])

        return Response(TimetableGenerationRunSerializer(run).data)


class DiscardTimetableGenerationRunView(APIView):
    """POST /timetable-generation-runs/<int:pk>/discard/ — deletes the run's draft Schedule rows."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]

    def post(self, request, pk):
        try:
            run = TimetableGenerationRun.objects.get(pk=pk)
        except TimetableGenerationRun.DoesNotExist:
            return Response({"error": "Generation run not found."}, status=status.HTTP_404_NOT_FOUND)

        if run.status not in (TimetableGenerationRun.STATUS_COMPLETED, TimetableGenerationRun.STATUS_INFEASIBLE, TimetableGenerationRun.STATUS_FAILED):
            return Response(
                {"error": f"Cannot discard a run already '{run.status}'."}, status=status.HTTP_400_BAD_REQUEST,
            )

        Schedule.objects.filter(generation_run=run, is_draft=True).delete()
        run.status = TimetableGenerationRun.STATUS_DISCARDED
        run.save(update_fields=["status"])

        return Response(TimetableGenerationRunSerializer(run).data)

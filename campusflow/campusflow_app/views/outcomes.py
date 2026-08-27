"""
Outcome-Based Education Views
==============================
CRUD for Program Outcomes, Course Outcomes, and the CO-PO articulation matrix.

Auth rules match the rest of the academic spine: GET open to any authenticated
user, writes need Faculty or above (the same bar as the question bank these
outcomes tag into).
"""

import csv
import io

from django.db import IntegrityError
from django.db.models import ProtectedError
from django.http import HttpResponse
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.academics import Program
from ..models.course import Course
from ..models.outcomes import CourseOutcome, POCOMapping, ProgramOutcome
from ..permissions import IsFacultyOrAbove, IsHMOrAbove
from ..services.outcome_attainment import (
    compute_course_outcome_class_attainment, compute_program_outcome_attainment,
)


def _to_int(value, default=None):
    """
    IntegerField assignment does not coerce a string in Python memory — only
    the DB round-trip does, via .save() + a refetch — so an unconverted
    request value silently stays a string on the in-memory instance and on
    anything serialized straight back from it. Coerce explicitly instead of
    relying on that round-trip.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _serialize_program_outcome(po):
    return {
        "id": po.id,
        "program_id": po.program_id,
        "kind": po.kind,
        "code": po.code,
        "statement": po.statement,
        "order": po.order,
    }


def _serialize_course_outcome(co, include_mappings=False):
    data = {
        "id": co.id,
        "course_id": co.course_id,
        "code": co.code,
        "statement": co.statement,
        "bloom_level": co.bloom_level,
        "target_attainment_percent": float(co.target_attainment_percent),
        "target_student_percent": float(co.target_student_percent),
        "order": co.order,
    }
    if include_mappings:
        data["po_mappings"] = [
            {
                "id": m.id,
                "program_outcome_id": m.program_outcome_id,
                "program_outcome_code": m.program_outcome.code,
                "strength": m.strength,
            }
            for m in co.po_mappings.select_related("program_outcome")
        ]
    return data


class _AdminWriteMixin:
    """GET open to authenticated users; every other verb needs Faculty+."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsFacultyOrAbove()]


class ProgramOutcomeListCreateView(_AdminWriteMixin, APIView):
    """
    GET  /api/academics/programs/<program_id>/outcomes/[?kind=]
    POST /api/academics/programs/<program_id>/outcomes/  — {kind?, code, statement, order?}
    """

    def get(self, request, program_id):
        outcomes = ProgramOutcome.objects.filter(program_id=program_id)
        kind = request.query_params.get("kind")
        if kind:
            outcomes = outcomes.filter(kind=kind)
        return Response(
            {"results": [_serialize_program_outcome(po) for po in outcomes]}, status=status.HTTP_200_OK
        )

    def post(self, request, program_id):
        program = Program.objects.filter(pk=program_id).first()
        if not program:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)

        code = (request.data.get("code") or "").strip()
        statement = (request.data.get("statement") or "").strip()
        if not code or not statement:
            return Response({"error": "code and statement are required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            outcome = ProgramOutcome.objects.create(
                program=program,
                kind=request.data.get("kind", ProgramOutcome.KIND_PO),
                code=code, statement=statement,
                order=_to_int(request.data.get("order"), 0),
            )
        except IntegrityError:
            return Response(
                {"error": f"Outcome '{code}' already exists for this program."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_serialize_program_outcome(outcome), status=status.HTTP_201_CREATED)


class ProgramOutcomeDetailView(_AdminWriteMixin, APIView):
    """PUT / DELETE /api/academics/program-outcomes/<pk>/"""

    def _get(self, pk):
        return ProgramOutcome.objects.filter(pk=pk).first()

    def put(self, request, pk):
        outcome = self._get(pk)
        if not outcome:
            return Response({"error": "Program outcome not found."}, status=status.HTTP_404_NOT_FOUND)

        for field in ("code", "statement", "kind"):
            if field in request.data:
                value = request.data.get(field)
                setattr(outcome, field, value.strip() if isinstance(value, str) else value)
        if "order" in request.data:
            outcome.order = _to_int(request.data.get("order"), outcome.order)

        try:
            outcome.save()
        except IntegrityError:
            return Response({"error": "An outcome with that code already exists for this program."},
                            status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize_program_outcome(outcome), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        outcome = self._get(pk)
        if not outcome:
            return Response({"error": "Program outcome not found."}, status=status.HTTP_404_NOT_FOUND)
        outcome.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CourseOutcomeListCreateView(_AdminWriteMixin, APIView):
    """
    GET  /api/courses/<course_id>/outcomes/
    POST /api/courses/<course_id>/outcomes/  — {code, statement, bloom_level?, target_attainment_percent?, target_student_percent?, order?}
    """

    def get(self, request, course_id):
        outcomes = CourseOutcome.objects.filter(course_id=course_id).prefetch_related(
            "po_mappings__program_outcome"
        )
        return Response(
            {"results": [_serialize_course_outcome(co, include_mappings=True) for co in outcomes]},
            status=status.HTTP_200_OK,
        )

    def post(self, request, course_id):
        course = Course.objects.filter(pk=course_id).first()
        if not course:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        code = (request.data.get("code") or "").strip()
        statement = (request.data.get("statement") or "").strip()
        if not code or not statement:
            return Response({"error": "code and statement are required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            outcome = CourseOutcome.objects.create(
                course=course, code=code, statement=statement,
                bloom_level=request.data.get("bloom_level", ""),
                target_attainment_percent=request.data.get("target_attainment_percent", 60),
                target_student_percent=request.data.get("target_student_percent", 60),
                order=_to_int(request.data.get("order"), 0),
            )
        except IntegrityError:
            return Response(
                {"error": f"Outcome '{code}' already exists for this course."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_serialize_course_outcome(outcome), status=status.HTTP_201_CREATED)


class CourseOutcomeDetailView(_AdminWriteMixin, APIView):
    """PUT / DELETE /api/course-outcomes/<pk>/"""

    def _get(self, pk):
        return CourseOutcome.objects.prefetch_related("po_mappings__program_outcome").filter(pk=pk).first()

    def put(self, request, pk):
        outcome = self._get(pk)
        if not outcome:
            return Response({"error": "Course outcome not found."}, status=status.HTTP_404_NOT_FOUND)

        for field in ("code", "statement", "bloom_level"):
            if field in request.data:
                value = request.data.get(field)
                setattr(outcome, field, value.strip() if isinstance(value, str) else value)
        for field in ("target_attainment_percent", "target_student_percent"):
            if field in request.data:
                setattr(outcome, field, request.data.get(field))
        if "order" in request.data:
            outcome.order = _to_int(request.data.get("order"), outcome.order)

        try:
            outcome.save()
        except IntegrityError:
            return Response({"error": "An outcome with that code already exists for this course."},
                            status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({"error": "Invalid numeric value."}, status=status.HTTP_400_BAD_REQUEST)
        return Response(_serialize_course_outcome(outcome, include_mappings=True), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        outcome = self._get(pk)
        if not outcome:
            return Response({"error": "Course outcome not found."}, status=status.HTTP_404_NOT_FOUND)
        outcome.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class POCOMappingListCreateView(_AdminWriteMixin, APIView):
    """
    GET  /api/course-outcomes/<course_outcome_id>/po-mappings/
    POST /api/course-outcomes/<course_outcome_id>/po-mappings/  — {program_outcome_id, strength?}
    """

    def get(self, request, course_outcome_id):
        mappings = POCOMapping.objects.filter(course_outcome_id=course_outcome_id).select_related(
            "program_outcome"
        )
        return Response(
            {
                "results": [
                    {
                        "id": m.id,
                        "program_outcome_id": m.program_outcome_id,
                        "program_outcome_code": m.program_outcome.code,
                        "strength": m.strength,
                    }
                    for m in mappings
                ]
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, course_outcome_id):
        course_outcome = CourseOutcome.objects.filter(pk=course_outcome_id).first()
        if not course_outcome:
            return Response({"error": "Course outcome not found."}, status=status.HTTP_404_NOT_FOUND)

        program_outcome = ProgramOutcome.objects.filter(pk=request.data.get("program_outcome_id")).first()
        if not program_outcome:
            return Response({"error": "A valid program_outcome_id is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        # A CO can only articulate to its own program's POs — mapping across
        # programs would produce an NBA matrix that means nothing. A legacy
        # course with no regulation has no program to check against, so the
        # mapping is allowed through unvalidated rather than blocked outright.
        if course_outcome.course.regulation_id:
            course_program_id = course_outcome.course.regulation.program_id
            if program_outcome.program_id != course_program_id:
                return Response(
                    {"error": "This program outcome belongs to a different program than the course's own."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        strength = _to_int(request.data.get("strength"), 1)
        if strength not in (1, 2, 3):
            return Response({"error": "strength must be 1, 2 or 3."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            mapping = POCOMapping.objects.create(
                course_outcome=course_outcome, program_outcome=program_outcome,
                strength=strength,
            )
        except IntegrityError:
            return Response(
                {"error": "This CO is already mapped to that PO — update the existing mapping instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(
            {
                "id": mapping.id,
                "course_outcome_id": mapping.course_outcome_id,
                "program_outcome_id": mapping.program_outcome_id,
                "program_outcome_code": program_outcome.code,
                "strength": mapping.strength,
            },
            status=status.HTTP_201_CREATED,
        )


class POCOMappingDetailView(_AdminWriteMixin, APIView):
    """PUT / DELETE /api/po-mappings/<pk>/"""

    def put(self, request, pk):
        mapping = POCOMapping.objects.filter(pk=pk).first()
        if not mapping:
            return Response({"error": "Mapping not found."}, status=status.HTTP_404_NOT_FOUND)
        if "strength" in request.data:
            # Django does not enforce `choices` at .save() time — only
            # full_clean()/ModelForm validation does — so an out-of-range
            # value would otherwise be stored silently instead of rejected.
            strength = _to_int(request.data.get("strength"))
            if strength not in (1, 2, 3):
                return Response({"error": "strength must be 1, 2 or 3."}, status=status.HTTP_400_BAD_REQUEST)
            mapping.strength = strength
        mapping.save()
        return Response(
            {"id": mapping.id, "strength": mapping.strength}, status=status.HTTP_200_OK,
        )

    def delete(self, request, pk):
        mapping = POCOMapping.objects.filter(pk=pk).first()
        if not mapping:
            return Response({"error": "Mapping not found."}, status=status.HTTP_404_NOT_FOUND)
        mapping.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CourseOutcomeAttainmentView(APIView):
    """
    GET /api/courses/<course_id>/outcome-attainment/
    Class-level CO attainment for one course — every student who sat an exam
    for this course, rolled up per CourseOutcome. Restricted to Faculty+ (this
    is aggregate class performance data, not an individual student's own
    record — a different sensitivity bar than StudentTopicPerformanceView).
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request, course_id):
        course = Course.objects.filter(pk=course_id).first()
        if not course:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        results = compute_course_outcome_class_attainment(course_id)
        return Response({
            "course_id": course.id,
            "course_code": course.course_code,
            "course_name": course.course_name,
            "course_outcomes": results,
        })


class ProgramOutcomeAttainmentView(APIView):
    """
    GET /api/academics/programs/<program_id>/outcome-attainment/[?format=csv]
    The core NBA SAR output: every ProgramOutcome's attainment %, rolled up
    from class-level CO attainment via the CO-PO correlation matrix. Gated at
    HM-or-above — this is IQAC/HOD-facing accreditation data, the same bar as
    other cross-student aggregate reports in this codebase.
    """
    permission_classes = [IsAuthenticated, IsHMOrAbove]

    def get(self, request, program_id):
        program = Program.objects.filter(pk=program_id).first()
        if not program:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)

        academic_year_id = _to_int(request.query_params.get("academic_year"))
        results = compute_program_outcome_attainment(program_id, academic_year_id=academic_year_id)

        if (request.query_params.get("export") or "").lower() == "csv":
            buffer = io.StringIO()
            writer = csv.writer(buffer)
            writer.writerow([
                "PO/PSO/PEO Code", "Kind", "Statement",
                "Direct Attainment %", "Indirect Attainment %", "Overall Attainment %",
                "Contributing Course Outcomes",
            ])
            for po in results:
                contributing = "; ".join(
                    f"{c['course_code']} {c['course_outcome_code']} (strength {c['correlation_strength']}, {c['attainment_value']}%)"
                    for c in po["contributing_course_outcomes"]
                )
                writer.writerow([
                    po["code"], po["kind"], po["statement"],
                    po["direct_attainment_percent"], po["indirect_attainment_percent"], po["attainment_percent"],
                    contributing,
                ])
            response = HttpResponse(buffer.getvalue(), content_type="text/csv")
            response["Content-Disposition"] = f'attachment; filename="sar_po_attainment_{program.code}.csv"'
            return response

        return Response({
            "program_id": program.id,
            "program_code": program.code,
            "program_name": program.name,
            "program_outcomes": results,
        })

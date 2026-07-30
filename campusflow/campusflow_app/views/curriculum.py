"""
Curriculum Views
================
CRUD for the curriculum structure: Program, Regulation, Batch, Section, and the
grading schemes a Regulation grades against.

Auth rules match the rest of the academic spine:
  - GET:   any authenticated user (a student may see their own programme/batch)
  - write: SaaS Admin or College Admin (Management/Administrator)

Nothing here mutates StudentProfile. The nullable program/batch/section FKs added
in this change are written by the backfill and by student create/update later —
these endpoints only manage the structures those FKs point at.
"""

from django.db import IntegrityError
from django.db.models import ProtectedError
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.academics import Batch, Program, Regulation, Section
from ..models.course import Course
from ..models.department import Department
from ..models.grading import GradeBand, GradingScheme
from ..permissions import IsSaaSOrCollegeAdmin
from ..services.academics import get_default_grading_scheme


# ── serialization helpers ─────────────────────────────────────────────

def _serialize_program(p):
    return {
        "id": p.id,
        "name": p.name,
        "code": p.code,
        "short_name": p.short_name,
        "level": p.level,
        "department_id": p.department_id,
        "department_name": p.department.name if p.department_id else None,
        "duration_years": float(p.duration_years),
        "total_terms": p.total_terms,
        "total_credits_required": (
            float(p.total_credits_required) if p.total_credits_required is not None else None
        ),
        "nep_multiple_entry_exit": p.nep_multiple_entry_exit,
        "aicte_program_code": p.aicte_program_code,
        "is_active": p.is_active,
        "regulation_count": p.regulations.count(),
    }


def _serialize_regulation(r):
    return {
        "id": r.id,
        "program_id": r.program_id,
        "program_code": r.program.code if r.program_id else None,
        "code": r.code,
        "name": r.name,
        "effective_from_year": r.effective_from_year,
        "effective_to_year": r.effective_to_year,
        "grading_scheme_id": r.grading_scheme_id,
        "grading_scheme_name": r.grading_scheme.name if r.grading_scheme_id else None,
        "min_credits_to_graduate": (
            float(r.min_credits_to_graduate) if r.min_credits_to_graduate is not None else None
        ),
        "max_backlogs_to_promote": r.max_backlogs_to_promote,
        "is_locked": r.is_locked,
        "status": r.status,
        "course_count": r.courses.count(),
    }


def _serialize_batch(b):
    return {
        "id": b.id,
        "program_id": b.program_id,
        "program_code": b.program.code if b.program_id else None,
        "regulation_id": b.regulation_id,
        "regulation_code": b.regulation.code if b.regulation_id else None,
        "admission_year": b.admission_year,
        "name": b.name,
        "expected_graduation_year": b.expected_graduation_year,
        "current_semester_number": b.current_semester_number,
        "is_active": b.is_active,
    }


def _serialize_section(s):
    return {
        "id": s.id,
        "batch_id": s.batch_id,
        "batch_name": s.batch.name if s.batch_id else None,
        "name": s.name,
        "semester_number": s.semester_number,
        "capacity": s.capacity,
        "mentor_id": s.mentor_id,
        "mentor_name": s.mentor.get_full_name() or s.mentor.username if s.mentor_id else None,
    }


def _serialize_scheme(s, include_bands=True):
    data = {
        "id": s.id,
        "name": s.name,
        "max_points": float(s.max_points),
        "passing_grade_points": float(s.passing_grade_points),
        "rounding_decimals": s.rounding_decimals,
        "is_absolute": s.is_absolute,
        "is_default": s.is_default,
    }
    if include_bands:
        data["bands"] = [
            {
                "id": b.id,
                "letter": b.letter,
                "min_percentage": float(b.min_percentage),
                "max_percentage": float(b.max_percentage),
                "grade_points": float(b.grade_points),
                "is_pass": b.is_pass,
                "counts_in_gpa": b.counts_in_gpa,
                "order": b.order,
            }
            for b in s.bands.all()
        ]
    return data


def _to_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class _AdminWriteMixin:
    """GET open to authenticated users; every other verb needs an admin."""

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsSaaSOrCollegeAdmin()]


# ── Program ───────────────────────────────────────────────────────────

class ProgramListCreateView(_AdminWriteMixin, APIView):
    """
    GET  /api/academics/programs/[?department_id=&is_active=true]
    POST /api/academics/programs/  — {name, code, department_id, level?, short_name?, ...}
    """

    def get(self, request):
        programs = Program.objects.select_related("department").prefetch_related("regulations")
        dept_id = request.query_params.get("department_id")
        if dept_id:
            programs = programs.filter(department_id=dept_id)
        if request.query_params.get("is_active") == "true":
            programs = programs.filter(is_active=True)
        return Response(
            {"results": [_serialize_program(p) for p in programs]}, status=status.HTTP_200_OK
        )

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        code = (request.data.get("code") or "").strip().upper()
        if not name or not code:
            return Response({"error": "name and code are required."},
                            status=status.HTTP_400_BAD_REQUEST)

        department = Department.objects.filter(pk=request.data.get("department_id")).first()
        if not department:
            return Response({"error": "A valid department_id is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            program = Program.objects.create(
                name=name,
                code=code,
                short_name=(request.data.get("short_name") or "").strip()[:50],
                level=request.data.get("level", "ug"),
                department=department,
                duration_years=request.data.get("duration_years") or 4,
                total_terms=_to_int(request.data.get("total_terms"), 8),
                total_credits_required=request.data.get("total_credits_required") or None,
                nep_multiple_entry_exit=bool(request.data.get("nep_multiple_entry_exit")),
                aicte_program_code=(request.data.get("aicte_program_code") or "").strip(),
            )
        except IntegrityError:
            return Response({"error": f"A program with code '{code}' already exists."},
                            status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({"error": "Invalid numeric value in duration_years or credits."},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_program(program), status=status.HTTP_201_CREATED)


class ProgramDetailView(_AdminWriteMixin, APIView):
    """GET / PUT / DELETE /api/academics/programs/<pk>/"""

    SIMPLE_FIELDS = (
        "name", "short_name", "level", "aicte_program_code",
        "total_credits_required", "duration_years",
    )

    def _get(self, pk):
        return Program.objects.select_related("department").filter(pk=pk).first()

    def get(self, request, pk):
        program = self._get(pk)
        if not program:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_program(program), status=status.HTTP_200_OK)

    def put(self, request, pk):
        program = self._get(pk)
        if not program:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)

        for field in self.SIMPLE_FIELDS:
            if field in request.data:
                setattr(program, field, request.data.get(field))
        if "code" in request.data:
            program.code = (request.data.get("code") or "").strip().upper()
        if "total_terms" in request.data:
            program.total_terms = _to_int(request.data.get("total_terms"), program.total_terms)
        if "department_id" in request.data:
            department = Department.objects.filter(pk=request.data.get("department_id")).first()
            if not department:
                return Response({"error": "Invalid department_id."},
                                status=status.HTTP_400_BAD_REQUEST)
            program.department = department
        for flag in ("is_active", "nep_multiple_entry_exit"):
            if flag in request.data:
                setattr(program, flag, bool(request.data.get(flag)))

        try:
            program.save()
        except IntegrityError:
            return Response({"error": "A program with that code already exists."},
                            status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({"error": "Invalid numeric value."},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_program(program), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        program = self._get(pk)
        if not program:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            program.delete()
        except ProtectedError:
            return Response(
                {"error": "This program has batches or other records attached. "
                          "Deactivate it instead of deleting."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Regulation ────────────────────────────────────────────────────────

class RegulationListCreateView(_AdminWriteMixin, APIView):
    """
    GET  /api/academics/regulations/[?program_id=&status=]
    POST /api/academics/regulations/  — {program_id, code, effective_from_year, ...}
    """

    def get(self, request):
        regulations = Regulation.objects.select_related("program", "grading_scheme")
        program_id = request.query_params.get("program_id")
        if program_id:
            regulations = regulations.filter(program_id=program_id)
        state = request.query_params.get("status")
        if state:
            regulations = regulations.filter(status=state)
        return Response(
            {"results": [_serialize_regulation(r) for r in regulations]}, status=status.HTTP_200_OK
        )

    def post(self, request):
        program = Program.objects.filter(pk=request.data.get("program_id")).first()
        if not program:
            return Response({"error": "A valid program_id is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        code = (request.data.get("code") or "").strip()
        if not code:
            return Response({"error": "code is required, e.g. R2023."},
                            status=status.HTTP_400_BAD_REQUEST)

        from_year = _to_int(request.data.get("effective_from_year"))
        if not from_year:
            return Response({"error": "effective_from_year is required and must be a year."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Default to the tenant's grading scheme so a regulation is never
        # ungradeable, while still allowing an explicit choice.
        scheme_id = request.data.get("grading_scheme_id")
        if scheme_id:
            scheme = GradingScheme.objects.filter(pk=scheme_id).first()
            if not scheme:
                return Response({"error": "Invalid grading_scheme_id."},
                                status=status.HTTP_400_BAD_REQUEST)
        else:
            scheme = get_default_grading_scheme()

        try:
            regulation = Regulation.objects.create(
                program=program,
                code=code,
                name=(request.data.get("name") or "").strip(),
                effective_from_year=from_year,
                effective_to_year=_to_int(request.data.get("effective_to_year")),
                grading_scheme=scheme,
                min_credits_to_graduate=request.data.get("min_credits_to_graduate") or None,
                max_backlogs_to_promote=_to_int(request.data.get("max_backlogs_to_promote")),
                status=request.data.get("status", "draft"),
            )
        except IntegrityError:
            return Response(
                {"error": f"Regulation '{code}' already exists for {program.code}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except (ValueError, TypeError):
            return Response({"error": "Invalid numeric value."},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_regulation(regulation), status=status.HTTP_201_CREATED)


class RegulationDetailView(_AdminWriteMixin, APIView):
    """GET / PUT / DELETE /api/academics/regulations/<pk>/"""

    def _get(self, pk):
        return Regulation.objects.select_related("program", "grading_scheme").filter(pk=pk).first()

    def get(self, request, pk):
        regulation = self._get(pk)
        if not regulation:
            return Response({"error": "Regulation not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_regulation(regulation), status=status.HTTP_200_OK)

    def put(self, request, pk):
        regulation = self._get(pk)
        if not regulation:
            return Response({"error": "Regulation not found."}, status=status.HTTP_404_NOT_FOUND)

        for field in ("code", "name", "status", "min_credits_to_graduate"):
            if field in request.data:
                value = request.data.get(field)
                setattr(regulation, field, value.strip() if isinstance(value, str) else value)
        for field in ("effective_from_year", "effective_to_year", "max_backlogs_to_promote"):
            if field in request.data:
                setattr(regulation, field, _to_int(request.data.get(field)))
        if "grading_scheme_id" in request.data:
            scheme = GradingScheme.objects.filter(pk=request.data.get("grading_scheme_id")).first()
            if not scheme:
                return Response({"error": "Invalid grading_scheme_id."},
                                status=status.HTTP_400_BAD_REQUEST)
            regulation.grading_scheme = scheme
        if "is_locked" in request.data:
            regulation.is_locked = bool(request.data.get("is_locked"))

        if not regulation.effective_from_year:
            return Response({"error": "effective_from_year is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            regulation.save()
        except IntegrityError:
            return Response({"error": "A regulation with that code already exists for this program."},
                            status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({"error": "Invalid numeric value."},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_regulation(regulation), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        regulation = self._get(pk)
        if not regulation:
            return Response({"error": "Regulation not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            regulation.delete()
        except ProtectedError:
            return Response(
                {"error": "This regulation has courses or batches attached. "
                          "Archive it instead of deleting."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Batch ─────────────────────────────────────────────────────────────

class BatchListCreateView(_AdminWriteMixin, APIView):
    """
    GET  /api/academics/batches/[?program_id=&is_active=true]
    POST /api/academics/batches/  — {program_id, regulation_id, admission_year, name?}
    """

    def get(self, request):
        batches = Batch.objects.select_related("program", "regulation")
        program_id = request.query_params.get("program_id")
        if program_id:
            batches = batches.filter(program_id=program_id)
        if request.query_params.get("is_active") == "true":
            batches = batches.filter(is_active=True)
        return Response(
            {"results": [_serialize_batch(b) for b in batches]}, status=status.HTTP_200_OK
        )

    def post(self, request):
        program = Program.objects.filter(pk=request.data.get("program_id")).first()
        if not program:
            return Response({"error": "A valid program_id is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        regulation = Regulation.objects.filter(pk=request.data.get("regulation_id")).first()
        if not regulation:
            return Response({"error": "A valid regulation_id is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        # A batch inherits its regulation, so a mismatch here would silently
        # grade a cohort against another programme's scheme.
        if regulation.program_id != program.id:
            return Response(
                {"error": f"Regulation '{regulation.code}' belongs to a different program."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        admission_year = _to_int(request.data.get("admission_year"))
        if not admission_year:
            return Response({"error": "admission_year is required and must be a year."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Derive the conventional "2025-2029" label when none is given.
        name = (request.data.get("name") or "").strip()
        if not name:
            span = int(program.duration_years) or 4
            name = f"{admission_year}-{admission_year + span}"

        try:
            batch = Batch.objects.create(
                program=program,
                regulation=regulation,
                admission_year=admission_year,
                name=name,
                expected_graduation_year=_to_int(request.data.get("expected_graduation_year")),
                current_semester_number=_to_int(request.data.get("current_semester_number"), 1),
            )
        except IntegrityError:
            return Response(
                {"error": f"A {admission_year} batch already exists for {program.code}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(_serialize_batch(batch), status=status.HTTP_201_CREATED)


class BatchDetailView(_AdminWriteMixin, APIView):
    """GET / PUT / DELETE /api/academics/batches/<pk>/"""

    def _get(self, pk):
        return Batch.objects.select_related("program", "regulation").filter(pk=pk).first()

    def get(self, request, pk):
        batch = self._get(pk)
        if not batch:
            return Response({"error": "Batch not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_batch(batch), status=status.HTTP_200_OK)

    def put(self, request, pk):
        batch = self._get(pk)
        if not batch:
            return Response({"error": "Batch not found."}, status=status.HTTP_404_NOT_FOUND)

        if "name" in request.data:
            batch.name = (request.data.get("name") or "").strip()
        for field in ("admission_year", "expected_graduation_year", "current_semester_number"):
            if field in request.data:
                setattr(batch, field, _to_int(request.data.get(field)))
        if "regulation_id" in request.data:
            regulation = Regulation.objects.filter(pk=request.data.get("regulation_id")).first()
            if not regulation:
                return Response({"error": "Invalid regulation_id."},
                                status=status.HTTP_400_BAD_REQUEST)
            if regulation.program_id != batch.program_id:
                return Response(
                    {"error": "That regulation belongs to a different program."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            batch.regulation = regulation
        if "is_active" in request.data:
            batch.is_active = bool(request.data.get("is_active"))

        try:
            batch.save()
        except IntegrityError:
            return Response({"error": "A batch for that program and admission year already exists."},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_batch(batch), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        batch = self._get(pk)
        if not batch:
            return Response({"error": "Batch not found."}, status=status.HTTP_404_NOT_FOUND)
        try:
            batch.delete()
        except ProtectedError:
            return Response(
                {"error": "This batch has records attached. Deactivate it instead of deleting."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Section ───────────────────────────────────────────────────────────

class SectionListCreateView(_AdminWriteMixin, APIView):
    """
    GET  /api/academics/sections/[?batch_id=&semester_number=]
    POST /api/academics/sections/  — {batch_id, name, semester_number, capacity?, mentor_id?}
    """

    def get(self, request):
        sections = Section.objects.select_related("batch", "mentor")
        batch_id = request.query_params.get("batch_id")
        if batch_id:
            sections = sections.filter(batch_id=batch_id)
        semester = request.query_params.get("semester_number")
        if semester:
            sections = sections.filter(semester_number=semester)
        return Response(
            {"results": [_serialize_section(s) for s in sections]}, status=status.HTTP_200_OK
        )

    def post(self, request):
        batch = Batch.objects.filter(pk=request.data.get("batch_id")).first()
        if not batch:
            return Response({"error": "A valid batch_id is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "name is required, e.g. A."},
                            status=status.HTTP_400_BAD_REQUEST)

        semester = _to_int(request.data.get("semester_number"))
        if not semester:
            return Response(
                {"error": "semester_number is required. Sections are scoped per semester so a "
                          "batch can be re-cut when electives begin."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            section = Section.objects.create(
                batch=batch,
                name=name,
                semester_number=semester,
                capacity=_to_int(request.data.get("capacity")),
                mentor_id=request.data.get("mentor_id") or None,
            )
        except IntegrityError:
            return Response(
                {"error": f"Section '{name}' already exists for semester {semester} of this batch."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(_serialize_section(section), status=status.HTTP_201_CREATED)


class SectionDetailView(_AdminWriteMixin, APIView):
    """GET / PUT / DELETE /api/academics/sections/<pk>/"""

    def _get(self, pk):
        return Section.objects.select_related("batch", "mentor").filter(pk=pk).first()

    def get(self, request, pk):
        section = self._get(pk)
        if not section:
            return Response({"error": "Section not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_section(section), status=status.HTTP_200_OK)

    def put(self, request, pk):
        section = self._get(pk)
        if not section:
            return Response({"error": "Section not found."}, status=status.HTTP_404_NOT_FOUND)

        if "name" in request.data:
            section.name = (request.data.get("name") or "").strip()
        for field in ("semester_number", "capacity"):
            if field in request.data:
                setattr(section, field, _to_int(request.data.get(field)))
        if "mentor_id" in request.data:
            section.mentor_id = request.data.get("mentor_id") or None

        try:
            section.save()
        except IntegrityError:
            return Response({"error": "A section with that name already exists for this batch and semester."},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_section(section), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        section = self._get(pk)
        if not section:
            return Response({"error": "Section not found."}, status=status.HTTP_404_NOT_FOUND)
        section.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ── Grading schemes ───────────────────────────────────────────────────

class GradingSchemeListView(APIView):
    """
    GET /api/academics/grading-schemes/

    Provisions the tenant's default 10-point scheme on first read, so a
    Regulation can always be pointed at something gradeable.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        get_default_grading_scheme()
        schemes = GradingScheme.objects.prefetch_related("bands").all()
        return Response(
            {"results": [_serialize_scheme(s) for s in schemes]}, status=status.HTTP_200_OK
        )


class GradingSchemeDetailView(_AdminWriteMixin, APIView):
    """
    GET /api/academics/grading-schemes/<pk>/
    PUT /api/academics/grading-schemes/<pk>/  — {name?, bands?: [...]}

    Supplying `bands` replaces the whole set. That is intentional: bands must
    tile the 0-100 range without gaps, so editing them one at a time invites an
    inconsistent intermediate state.
    """

    def _get(self, pk):
        return GradingScheme.objects.prefetch_related("bands").filter(pk=pk).first()

    def get(self, request, pk):
        scheme = self._get(pk)
        if not scheme:
            return Response({"error": "Grading scheme not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_scheme(scheme), status=status.HTTP_200_OK)

    def put(self, request, pk):
        scheme = self._get(pk)
        if not scheme:
            return Response({"error": "Grading scheme not found."}, status=status.HTTP_404_NOT_FOUND)

        if "name" in request.data:
            name = (request.data.get("name") or "").strip()
            if not name:
                return Response({"error": "name cannot be blank."},
                                status=status.HTTP_400_BAD_REQUEST)
            scheme.name = name
        for field in ("max_points", "passing_grade_points"):
            if field in request.data:
                setattr(scheme, field, request.data.get(field))
        if "rounding_decimals" in request.data:
            scheme.rounding_decimals = _to_int(
                request.data.get("rounding_decimals"), scheme.rounding_decimals
            )
        if "is_absolute" in request.data:
            scheme.is_absolute = bool(request.data.get("is_absolute"))

        try:
            scheme.save()
        except IntegrityError:
            return Response({"error": "A grading scheme with that name already exists."},
                            status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({"error": "Invalid numeric value."},
                            status=status.HTTP_400_BAD_REQUEST)

        bands = request.data.get("bands")
        if isinstance(bands, list):
            if not bands:
                return Response({"error": "bands cannot be an empty list."},
                                status=status.HTTP_400_BAD_REQUEST)
            for band in bands:
                if not (band.get("letter") or "").strip():
                    return Response({"error": "Every band needs a letter."},
                                    status=status.HTTP_400_BAD_REQUEST)
                try:
                    low = float(band.get("min_percentage"))
                    high = float(band.get("max_percentage"))
                    float(band.get("grade_points"))
                except (TypeError, ValueError):
                    return Response(
                        {"error": "min_percentage, max_percentage and grade_points must be numbers."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if high < low:
                    return Response(
                        {"error": f"Band '{band.get('letter')}' has max_percentage below min_percentage."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            scheme.bands.all().delete()
            GradeBand.objects.bulk_create([
                GradeBand(
                    scheme=scheme,
                    letter=str(band["letter"]).strip(),
                    min_percentage=band["min_percentage"],
                    max_percentage=band["max_percentage"],
                    grade_points=band["grade_points"],
                    is_pass=bool(band.get("is_pass", True)),
                    counts_in_gpa=bool(band.get("counts_in_gpa", True)),
                    order=_to_int(band.get("order"), index),
                )
                for index, band in enumerate(bands)
            ])
            scheme = self._get(pk)

        return Response(_serialize_scheme(scheme), status=status.HTTP_200_OK)


class RegulationCourseListView(APIView):
    """
    GET /api/academics/regulations/<pk>/courses/

    The curriculum of a regulation — the credit-bearing course list that credit
    totals and SGPA will be computed from.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        if not Regulation.objects.filter(pk=pk).exists():
            return Response({"error": "Regulation not found."}, status=status.HTTP_404_NOT_FOUND)

        courses = Course.objects.filter(regulation_id=pk).select_related("department")
        semester = request.query_params.get("semester_number")
        if semester:
            courses = courses.filter(semester_number=semester)

        total_credits = sum(
            float(c.credits) for c in courses if c.credits and c.is_credit_bearing
        )
        return Response(
            {
                "results": [
                    {
                        "id": c.id,
                        "course_code": c.course_code,
                        "course_name": c.course_name,
                        "canonical_code": c.canonical_code,
                        "department_id": c.department_id,
                        "semester_number": c.semester_number,
                        "course_type": c.course_type,
                        "credits": float(c.credits) if c.credits is not None else None,
                        "lecture_hours": c.lecture_hours,
                        "tutorial_hours": c.tutorial_hours,
                        "practical_hours": c.practical_hours,
                        "is_credit_bearing": c.is_credit_bearing,
                        "counts_toward_cgpa": c.counts_toward_cgpa,
                        "is_active": c.is_active,
                    }
                    for c in courses
                ],
                "total_credits": total_credits,
            },
            status=status.HTTP_200_OK,
        )

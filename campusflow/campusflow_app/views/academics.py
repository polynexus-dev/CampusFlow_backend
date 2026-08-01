"""
Academic Calendar Views
=======================
CRUD for AcademicYear and Term, plus the current-term resolver every other
module will read instead of hardcoding a semester string.

Auth rules:
  - GET:  any authenticated user (students see which term they are in)
  - write: SaaS Admin or College Admin (Management/Administrator)
"""

from datetime import date

from django.db import IntegrityError, transaction
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.academics import AcademicYear, Term
from ..permissions import IsSaaSOrCollegeAdmin
from ..services.academics import (
    derive_academic_year,
    get_current_term,
    get_or_create_terms,
    set_current_term,
)


def _serialize_year(y, include_terms=False):
    data = {
        "id": y.id,
        "name": y.name,
        "start_date": y.start_date.isoformat(),
        "end_date": y.end_date.isoformat(),
        "is_current": y.is_current,
        "is_closed": y.is_closed,
        "term_count": y.terms.count(),
    }
    if include_terms:
        data["terms"] = [_serialize_term(t) for t in y.terms.order_by("sequence")]
    return data


def _serialize_term(t):
    return {
        "id": t.id,
        "academic_year_id": t.academic_year_id,
        "academic_year_name": t.academic_year.name,
        "name": t.name,
        "kind": t.kind,
        "sequence": t.sequence,
        "start_date": t.start_date.isoformat(),
        "end_date": t.end_date.isoformat(),
        "is_current": t.is_current,
        "result_entry_open": t.result_entry_open,
    }


def _parse_date(value, field_name):
    """Returns (date, error_message). Accepts ISO YYYY-MM-DD."""
    if not value:
        return None, f"{field_name} is required."
    try:
        return date.fromisoformat(str(value)[:10]), None
    except ValueError:
        return None, f"{field_name} must be a valid date in YYYY-MM-DD format."


class AcademicYearListCreateView(APIView):
    """
    GET  /api/academics/years/    — list all, newest first
    POST /api/academics/years/    — {name, start_date, end_date}
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsSaaSOrCollegeAdmin()]
        return [IsAuthenticated()]

    def get(self, request):
        years = AcademicYear.objects.prefetch_related("terms").all()
        include_terms = request.query_params.get("include_terms") == "true"
        return Response(
            {"results": [_serialize_year(y, include_terms) for y in years]},
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "name is required, e.g. 2025-2026."},
                            status=status.HTTP_400_BAD_REQUEST)

        # Let the caller omit dates and fall back to the July-June convention.
        if request.data.get("start_date") or request.data.get("end_date"):
            start, err = _parse_date(request.data.get("start_date"), "start_date")
            if err:
                return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)
            end, err = _parse_date(request.data.get("end_date"), "end_date")
            if err:
                return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)
        else:
            try:
                start_year = int(name.split("-")[0])
            except (ValueError, IndexError):
                return Response(
                    {"error": "Provide start_date and end_date, or name in the form 2025-2026."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            _, start, end = derive_academic_year(date(start_year, 7, 1))

        if end <= start:
            return Response({"error": "end_date must be after start_date."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            with transaction.atomic():
                year = AcademicYear.objects.create(name=name, start_date=start, end_date=end)
                if request.data.get("create_terms", True):
                    get_or_create_terms(year)
        except IntegrityError:
            return Response({"error": f"Academic year '{name}' already exists."},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_year(year, include_terms=True), status=status.HTTP_201_CREATED)


class AcademicYearDetailView(APIView):
    """
    GET    /api/academics/years/<pk>/
    PUT    /api/academics/years/<pk>/  — {name?, start_date?, end_date?, is_closed?}
    DELETE /api/academics/years/<pk>/
    """

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsSaaSOrCollegeAdmin()]

    def _get(self, pk):
        return AcademicYear.objects.prefetch_related("terms").filter(pk=pk).first()

    def get(self, request, pk):
        year = self._get(pk)
        if not year:
            return Response({"error": "Academic year not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_year(year, include_terms=True), status=status.HTTP_200_OK)

    def put(self, request, pk):
        year = self._get(pk)
        if not year:
            return Response({"error": "Academic year not found."}, status=status.HTTP_404_NOT_FOUND)

        if "name" in request.data:
            name = (request.data.get("name") or "").strip()
            if not name:
                return Response({"error": "name cannot be blank."}, status=status.HTTP_400_BAD_REQUEST)
            year.name = name

        for field in ("start_date", "end_date"):
            if field in request.data:
                parsed, err = _parse_date(request.data.get(field), field)
                if err:
                    return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)
                setattr(year, field, parsed)

        if year.end_date <= year.start_date:
            return Response({"error": "end_date must be after start_date."},
                            status=status.HTTP_400_BAD_REQUEST)

        if "is_closed" in request.data:
            year.is_closed = bool(request.data.get("is_closed"))

        try:
            year.save()
        except IntegrityError:
            return Response({"error": "An academic year with that name already exists."},
                            status=status.HTTP_400_BAD_REQUEST)

        return Response(_serialize_year(year, include_terms=True), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        year = self._get(pk)
        if not year:
            return Response({"error": "Academic year not found."}, status=status.HTTP_404_NOT_FOUND)
        if year.terms.filter(is_current=True).exists():
            return Response(
                {"error": "Cannot delete the academic year containing the current term. "
                          "Make another term current first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        year.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class TermListCreateView(APIView):
    """
    GET  /api/academics/terms/                       — all terms, newest year first
    GET  /api/academics/terms/?academic_year_id=<id>  — filtered
    POST /api/academics/terms/                       — {academic_year_id, name, sequence, start_date, end_date, kind?}
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsSaaSOrCollegeAdmin()]
        return [IsAuthenticated()]

    def get(self, request):
        terms = Term.objects.select_related("academic_year").all()
        year_id = request.query_params.get("academic_year_id")
        if year_id:
            terms = terms.filter(academic_year_id=year_id)
        return Response({"results": [_serialize_term(t) for t in terms]}, status=status.HTTP_200_OK)

    def post(self, request):
        year = AcademicYear.objects.filter(pk=request.data.get("academic_year_id")).first()
        if not year:
            return Response({"error": "A valid academic_year_id is required."},
                            status=status.HTTP_400_BAD_REQUEST)
        if year.is_closed:
            return Response({"error": f"Academic year '{year.name}' is closed."},
                            status=status.HTTP_400_BAD_REQUEST)

        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "name is required."}, status=status.HTTP_400_BAD_REQUEST)

        start, err = _parse_date(request.data.get("start_date"), "start_date")
        if err:
            return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)
        end, err = _parse_date(request.data.get("end_date"), "end_date")
        if err:
            return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)
        if end <= start:
            return Response({"error": "end_date must be after start_date."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            term = Term.objects.create(
                academic_year=year,
                name=name,
                kind=request.data.get("kind", Term.KIND_ODD),
                sequence=int(request.data.get("sequence") or 1),
                start_date=start,
                end_date=end,
            )
        except (IntegrityError, ValueError):
            return Response(
                {"error": "A term with that name or sequence already exists for this academic year."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(_serialize_term(term), status=status.HTTP_201_CREATED)


class TermDetailView(APIView):
    """
    GET    /api/academics/terms/<pk>/
    PUT    /api/academics/terms/<pk>/  — {name?, kind?, sequence?, start_date?, end_date?, result_entry_open?}
    DELETE /api/academics/terms/<pk>/
    """

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsSaaSOrCollegeAdmin()]

    def _get(self, pk):
        return Term.objects.select_related("academic_year").filter(pk=pk).first()

    def get(self, request, pk):
        term = self._get(pk)
        if not term:
            return Response({"error": "Term not found."}, status=status.HTTP_404_NOT_FOUND)
        return Response(_serialize_term(term), status=status.HTTP_200_OK)

    def put(self, request, pk):
        term = self._get(pk)
        if not term:
            return Response({"error": "Term not found."}, status=status.HTTP_404_NOT_FOUND)

        if "name" in request.data:
            name = (request.data.get("name") or "").strip()
            if not name:
                return Response({"error": "name cannot be blank."}, status=status.HTTP_400_BAD_REQUEST)
            term.name = name
        if "kind" in request.data:
            term.kind = request.data.get("kind")
        if "sequence" in request.data:
            try:
                term.sequence = int(request.data.get("sequence"))
            except (TypeError, ValueError):
                return Response({"error": "sequence must be a whole number."},
                                status=status.HTTP_400_BAD_REQUEST)

        for field in ("start_date", "end_date"):
            if field in request.data:
                parsed, err = _parse_date(request.data.get(field), field)
                if err:
                    return Response({"error": err}, status=status.HTTP_400_BAD_REQUEST)
                setattr(term, field, parsed)

        if term.end_date <= term.start_date:
            return Response({"error": "end_date must be after start_date."},
                            status=status.HTTP_400_BAD_REQUEST)

        if "result_entry_open" in request.data:
            term.result_entry_open = bool(request.data.get("result_entry_open"))

        try:
            term.save()
        except IntegrityError:
            return Response(
                {"error": "A term with that name or sequence already exists for this academic year."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(_serialize_term(term), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        term = self._get(pk)
        if not term:
            return Response({"error": "Term not found."}, status=status.HTTP_404_NOT_FOUND)
        if term.is_current:
            return Response(
                {"error": "Cannot delete the current term. Make another term current first."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        term.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class CurrentTermView(APIView):
    """
    GET /api/academics/current-term/

    The endpoint that replaces hardcoded semester strings across the frontend.
    Provisions the calendar on first call in a tenant schema, so it never 404s.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        term = get_current_term()
        if not term:
            return Response({"error": "Unable to resolve a current term."},
                            status=status.HTTP_404_NOT_FOUND)
        return Response(
            {
                "term": _serialize_term(term),
                "academic_year": _serialize_year(term.academic_year),
                # Flat aliases so callers can drop these straight into the
                # existing free-text `semester` / `academic_year` fields on Exam
                # and Schedule during the transition.
                "semester": term.name,
                "academic_year_name": term.academic_year.name,
            },
            status=status.HTTP_200_OK,
        )


class SetCurrentTermView(APIView):
    """
    POST /api/academics/current-term/set/  — {term_id}

    An explicit choice here overrides date-based resolution permanently, which
    is what a college needs when a session runs late.
    """

    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def post(self, request):
        term = Term.objects.select_related("academic_year").filter(
            pk=request.data.get("term_id")
        ).first()
        if not term:
            return Response({"error": "A valid term_id is required."},
                            status=status.HTTP_400_BAD_REQUEST)

        term = set_current_term(term)
        return Response(
            {"term": _serialize_term(term), "academic_year": _serialize_year(term.academic_year)},
            status=status.HTTP_200_OK,
        )

"""
NBA Indirect Attainment — collection endpoints for the four survey channels
(course-exit, programme-exit, employer, alumni) NBA's SAR expects alongside
direct (exam-derived) attainment. Auth follows outcomes.py's existing bar
for the same reason: GET open to any authenticated user, writes need
Faculty or above — this is accreditation data of the same sensitivity as
CO/PO/CO-PO-mapping management, not individual student records.
"""
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.academics import AcademicYear, Program
from ..models.course import Course
from ..models.indirect_attainment import OutcomeIndirectSurvey, OutcomeIndirectSurveyResponse
from ..models.outcomes import ProgramOutcome
from .outcomes import _AdminWriteMixin, _to_int


def _serialize_survey(survey):
    return {
        "id": survey.id,
        "program_id": survey.program_id,
        "course_id": survey.course_id,
        "course_code": survey.course.course_code if survey.course_id else None,
        "academic_year_id": survey.academic_year_id,
        "academic_year_name": survey.academic_year.name,
        "survey_type": survey.survey_type,
        "survey_type_display": survey.get_survey_type_display(),
        "is_open": survey.is_open,
        "response_count": survey.responses.count(),
    }


def _serialize_response(resp):
    return {
        "id": resp.id,
        "survey_id": resp.survey_id,
        "program_outcome_id": resp.program_outcome_id,
        "program_outcome_code": resp.program_outcome.code,
        "respondent_label": resp.respondent_label,
        "rating": resp.rating,
        "submitted_at": resp.submitted_at.isoformat(),
    }


class OutcomeIndirectSurveyListCreateView(_AdminWriteMixin, APIView):
    """
    GET  /api/academics/programs/<program_id>/indirect-surveys/[?survey_type=]
    POST /api/academics/programs/<program_id>/indirect-surveys/
         — {survey_type, academic_year_id, course_id? (required iff survey_type='course_exit'), is_open?}
    """

    def get(self, request, program_id):
        surveys = OutcomeIndirectSurvey.objects.filter(program_id=program_id).select_related(
            "course", "academic_year",
        )
        survey_type = request.query_params.get("survey_type")
        if survey_type:
            surveys = surveys.filter(survey_type=survey_type)
        return Response({"results": [_serialize_survey(s) for s in surveys]}, status=status.HTTP_200_OK)

    def post(self, request, program_id):
        program = Program.objects.filter(pk=program_id).first()
        if not program:
            return Response({"error": "Program not found."}, status=status.HTTP_404_NOT_FOUND)

        survey_type = request.data.get("survey_type")
        if survey_type not in dict(OutcomeIndirectSurvey.TYPE_CHOICES):
            return Response(
                {"error": f"survey_type must be one of {list(dict(OutcomeIndirectSurvey.TYPE_CHOICES))}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        academic_year = AcademicYear.objects.filter(pk=request.data.get("academic_year_id")).first()
        if not academic_year:
            return Response({"error": "A valid academic_year_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        course = None
        course_id = request.data.get("course_id")
        if course_id:
            course = Course.objects.filter(pk=course_id).first()
            if not course:
                return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        survey = OutcomeIndirectSurvey(
            program=program, course=course, academic_year=academic_year,
            survey_type=survey_type, is_open=request.data.get("is_open", True),
        )
        try:
            survey.full_clean()
            survey.save()
        except ValidationError as exc:
            return Response({"error": "; ".join(exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        except IntegrityError:
            return Response(
                {"error": "A survey of this type already exists for this program/course/academic year."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(_serialize_survey(survey), status=status.HTTP_201_CREATED)


class OutcomeIndirectSurveyDetailView(_AdminWriteMixin, APIView):
    """PATCH / DELETE /api/indirect-surveys/<pk>/ — only is_open is meant to change post-creation."""

    def patch(self, request, pk):
        survey = OutcomeIndirectSurvey.objects.filter(pk=pk).first()
        if not survey:
            return Response({"error": "Survey not found."}, status=status.HTTP_404_NOT_FOUND)
        if "is_open" in request.data:
            survey.is_open = bool(request.data.get("is_open"))
            survey.save(update_fields=["is_open"])
        return Response(_serialize_survey(survey), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        survey = OutcomeIndirectSurvey.objects.filter(pk=pk).first()
        if not survey:
            return Response({"error": "Survey not found."}, status=status.HTTP_404_NOT_FOUND)
        survey.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class OutcomeIndirectSurveyResponseListCreateView(_AdminWriteMixin, APIView):
    """
    GET  /api/indirect-surveys/<survey_id>/responses/
    POST /api/indirect-surveys/<survey_id>/responses/
         — {respondent_label?, ratings: {"PO1": 4, "PSO2": 5, ...}}
    One respondent's ratings arrive as a single PO-code -> 1-5 map (the
    natural shape of "one filled-in survey form") and are exploded here into
    one OutcomeIndirectSurveyResponse row per PO, matching every other
    respondent's rows and letting compute_program_outcome_indirect_attainment
    aggregate with a plain ORM query.
    """

    def get(self, request, survey_id):
        survey = OutcomeIndirectSurvey.objects.filter(pk=survey_id).first()
        if not survey:
            return Response({"error": "Survey not found."}, status=status.HTTP_404_NOT_FOUND)
        responses = survey.responses.select_related("program_outcome").all()
        return Response({"results": [_serialize_response(r) for r in responses]}, status=status.HTTP_200_OK)

    def post(self, request, survey_id):
        survey = OutcomeIndirectSurvey.objects.filter(pk=survey_id).first()
        if not survey:
            return Response({"error": "Survey not found."}, status=status.HTTP_404_NOT_FOUND)
        if not survey.is_open:
            return Response({"error": "This survey is closed to new responses."}, status=status.HTTP_400_BAD_REQUEST)

        ratings = request.data.get("ratings")
        if not isinstance(ratings, dict) or not ratings:
            return Response(
                {"error": "ratings must be a non-empty object of {program_outcome_code: 1-5 rating}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        po_by_code = {
            po.code: po for po in ProgramOutcome.objects.filter(program_id=survey.program_id, code__in=ratings.keys())
        }
        unknown_codes = set(ratings.keys()) - set(po_by_code.keys())
        if unknown_codes:
            return Response(
                {"error": f"Unknown program outcome code(s) for this program: {', '.join(sorted(unknown_codes))}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        parsed = {}
        for code, raw_rating in ratings.items():
            rating = _to_int(raw_rating)
            if rating not in (1, 2, 3, 4, 5):
                return Response(
                    {"error": f"Rating for {code} must be an integer 1-5."}, status=status.HTTP_400_BAD_REQUEST,
                )
            parsed[code] = rating

        respondent_label = (request.data.get("respondent_label") or "").strip()
        created = [
            OutcomeIndirectSurveyResponse.objects.create(
                survey=survey, program_outcome=po_by_code[code],
                respondent_label=respondent_label, rating=rating,
            )
            for code, rating in parsed.items()
        ]
        return Response(
            {"created": len(created), "results": [_serialize_response(r) for r in created]},
            status=status.HTTP_201_CREATED,
        )

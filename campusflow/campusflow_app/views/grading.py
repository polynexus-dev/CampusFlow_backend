"""
Results Publishing & Transcript
================================
Publishes credit-weighted course grades for a term (services/grading.py) and
exposes them back as a transcript: per-term SGPA sheets, per-course grade
awards, and running CGPA.

Auth rules:
  - publish: HOD or above (IsHMOrAbove) — a grading action, not a routine
    write, so it sits above the IsSaaSOrCollegeAdmin bar used elsewhere in the
    academic spine.
  - transcript: a student may read their own; staff need IsFacultyOrAbove.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.academics import Term
from ..models.grading import CourseGradeAward, StudentAcademicSummary, TermGradeSheet
from ..models.profile import StudentProfile
from ..permissions import IsHMOrAbove, is_faculty_or_above
from ..services.grading import publish_term_results


def _serialize_award(a):
    return {
        "id": a.id,
        "course_code": a.registration.offering.course.course_code,
        "course_name": a.registration.offering.course.course_name,
        "credits": float(a.credits),
        "internal_marks": float(a.internal_marks) if a.internal_marks is not None else None,
        "external_marks": float(a.external_marks) if a.external_marks is not None else None,
        "total_marks": float(a.total_marks) if a.total_marks is not None else None,
        "max_marks": float(a.max_marks) if a.max_marks is not None else None,
        "percentage": float(a.percentage) if a.percentage is not None else None,
        "grade_letter": a.grade_letter,
        "grade_points": float(a.grade_points),
        "credit_points": float(a.credit_points),
        "is_pass": a.is_pass,
        "counts_in_gpa": a.counts_in_gpa,
        "attempt_number": a.attempt_number,
    }


def _serialize_gradesheet(sheet, awards):
    return {
        "id": sheet.id,
        "term_id": sheet.term_id,
        "term_name": sheet.term.name,
        "academic_year_name": sheet.term.academic_year.name,
        "semester_number": sheet.semester_number,
        "credits_registered": float(sheet.credits_registered),
        "credits_earned": float(sheet.credits_earned),
        "credit_points_earned": float(sheet.credit_points_earned),
        "sgpa": float(sheet.sgpa) if sheet.sgpa is not None else None,
        "backlog_count": sheet.backlog_count,
        "result_status": sheet.result_status,
        "is_published": sheet.is_published,
        "courses": [_serialize_award(a) for a in awards],
    }


class PublishTermResultsView(APIView):
    """
    POST /api/academics/terms/<pk>/publish-results/

    Computes and publishes CourseGradeAward for every registration in this
    term that does not already have one and has published exam results to
    compute one from, then (re)computes each affected student's TermGradeSheet
    and CGPA. Safe to call repeatedly: an already-published award is never
    touched here (see recompute_academic_records for an explicit correction).
    """

    permission_classes = [IsAuthenticated, IsHMOrAbove]

    def post(self, request, pk):
        term = Term.objects.filter(pk=pk).first()
        if not term:
            return Response({"error": "Term not found."}, status=status.HTTP_404_NOT_FOUND)

        result = publish_term_results(term)
        return Response(
            {
                "message": (
                    f"Published {result['awards_created']} course grade(s) for "
                    f"{result['students_affected']} student(s) in {term.name}."
                ),
                **result,
            },
            status=status.HTTP_200_OK,
        )


class StudentTranscriptView(APIView):
    """
    GET /api/academics/students/<pk>/transcript/
    GET /api/academics/my-transcript/     (student's own — no pk in the URL)

    Returns every published TermGradeSheet with its course-level awards, plus
    the running CGPA from StudentAcademicSummary.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk=None):
        if pk is None:
            student = StudentProfile.objects.filter(user=request.user).first()
            if not student:
                return Response({"error": "No student profile for this account."},
                                status=status.HTTP_404_NOT_FOUND)
        else:
            if not is_faculty_or_above(request.user):
                return Response({"error": "Not permitted to view another student's transcript."},
                                status=status.HTTP_403_FORBIDDEN)
            student = StudentProfile.objects.filter(pk=pk).first()
            if not student:
                return Response({"error": "Student not found."}, status=status.HTTP_404_NOT_FOUND)

        sheets = (
            TermGradeSheet.objects.filter(student=student, is_published=True)
            .select_related("term", "term__academic_year")
            .order_by("term__academic_year__start_date", "term__sequence")
        )
        awards = (
            CourseGradeAward.objects.filter(student=student, is_published=True)
            .select_related("registration__offering__course")
        )
        awards_by_term = {}
        for award in awards:
            awards_by_term.setdefault(award.term_id, []).append(award)

        summary = StudentAcademicSummary.objects.filter(student=student).first()

        return Response(
            {
                "student_id": student.student_id,
                "cgpa": float(summary.cgpa) if summary and summary.cgpa is not None else None,
                "credits_earned": float(summary.credits_earned) if summary else 0,
                "active_backlog_count": summary.active_backlog_count if summary else 0,
                "highest_semester_cleared": summary.highest_semester_cleared if summary else 0,
                "terms": [
                    _serialize_gradesheet(sheet, awards_by_term.get(sheet.term_id, []))
                    for sheet in sheets
                ],
            },
            status=status.HTTP_200_OK,
        )

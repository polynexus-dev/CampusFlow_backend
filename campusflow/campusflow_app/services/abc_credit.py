"""
The ABC credit-upload pipeline trigger point — see models/abc_credit.py's
module docstring for the internal-modeling-only boundary this operates
inside.
"""
from ..models.abc_credit import ABCCreditEntry


def record_credit_entry(result):
    """
    Create (or refresh) the ABCCreditEntry for one published StudentExamResult.
    Idempotent per (student, course, academic_year) — re-publishing/re-calling
    for the same exam updates credits_earned/grade in place rather than
    duplicating, since a course's credits are a per-academic-year fact, not
    a per-exam one (a student might have multiple exams for the same course
    in a year).
    """
    exam = result.exam
    if not exam.term_id:
        return None
    course = exam.course
    if not course.credits:
        return None

    entry, _ = ABCCreditEntry.objects.update_or_create(
        student=result.student, course=course, academic_year=exam.term.academic_year,
        defaults={"credits_earned": course.credits, "grade": result.grade or ""},
    )
    return entry

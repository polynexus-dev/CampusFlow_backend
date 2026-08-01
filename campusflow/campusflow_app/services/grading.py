"""
Credit-Weighted Result Computation
===================================
Turns a student's exam marks into a course grade, a term SGPA, and a running
CGPA — the layer CourseOffering/StudentCourseRegistration (models/offerings.py)
and GradingScheme/GradeBand (models/grading.py) exist to support.

Every function that writes uses bulk_create/bulk_update or targeted
update_or_create, never a per-row .save() loop: publishing a term for 2000
students would otherwise be ~4000 extra SQL statements and 2000 near-identical
AuditLog rows from the global audit signals (signals.py) for one
administrative action. The caller gets one meaningful summary instead.

Nothing here recomputes an award that is already published — see
publish_term_results and management/commands/recompute_academic_records.py
for the explicit, audited override path. This mirrors the invariant
Regulation.is_locked already establishes on Course: credits and grades that a
transcript was printed from must not silently move under a later, unrelated
change.
"""

from collections import defaultdict
from decimal import Decimal

from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from ..models.grading import CourseGradeAward, TermGradeSheet, StudentAcademicSummary
from ..models.offerings import StudentCourseRegistration
from ..models.profile import StudentProfile
from .academics import get_default_grading_scheme

ZERO = Decimal("0")

# Exam type codes read as "the end-semester component" for the internal/
# external split below. Anything else is treated as internal/continuous.
_END_SEMESTER_CODES = {"END", "FINAL", "SEM", "ESE"}


def _split_internal_external(results):
    """
    Best-effort split of a course's exam results into internal (continuous
    assessment) vs external (end-semester) marks — only attempted when
    exactly two distinct ExamType codes are present and exactly one of them
    unambiguously reads as the end-semester component. Otherwise (one exam,
    three+ components, two components with an ambiguous code) returns
    (None, None) rather than guessing which bucket a mark belongs in; the
    combined total_marks/percentage are computed regardless.
    """
    by_code = defaultdict(list)
    for result in results:
        code = (result.exam.exam_type.code or "").upper()
        by_code[code].append(result)

    if len(by_code) != 2:
        return None, None

    end_codes = [code for code in by_code if code in _END_SEMESTER_CODES]
    if len(end_codes) != 1:
        return None, None

    external_code = end_codes[0]
    internal_marks = sum(
        (r.marks_obtained for code, rs in by_code.items() if code != external_code for r in rs),
        ZERO,
    )
    external_marks = sum((r.marks_obtained for r in by_code[external_code]), ZERO)
    return internal_marks, external_marks


def compute_course_award(registration):
    """
    Computes (does NOT save) a CourseGradeAward for one registration, from
    every PUBLISHED exam result the student has for the offering's course
    within the offering's term. Returns None if there are no published
    results yet, or if the resulting percentage does not fall into any grade
    band (a misconfigured scheme) — an award requires real marks and a real
    band, never a guess at either.
    """
    from ..models.result import StudentExamResult

    offering = registration.offering
    course = offering.course

    results = list(
        StudentExamResult.objects.filter(
            student=registration.student,
            exam__course=course,
            exam__term=registration.term,
            exam__results_published=True,
        ).select_related("exam", "exam__exam_type")
    )
    if not results:
        return None

    total_marks = sum((r.marks_obtained for r in results), ZERO)
    max_marks = sum((Decimal(r.exam.total_marks) for r in results), ZERO)
    if not max_marks:
        return None
    percentage = round((total_marks / max_marks) * 100, 2)

    scheme = None
    effective_regulation = registration.student.effective_regulation
    if effective_regulation is not None:
        scheme = effective_regulation.effective_grading_scheme
    if scheme is None:
        scheme = get_default_grading_scheme()

    band = scheme.band_for_percentage(percentage)
    if band is None:
        return None

    internal_marks, external_marks = _split_internal_external(results)

    credits = offering.effective_credits or ZERO
    counts_in_gpa = bool(band.counts_in_gpa) and bool(course.is_credit_bearing)
    credit_points = credits * band.grade_points

    return CourseGradeAward(
        registration=registration,
        student=registration.student,
        term=registration.term,
        credits=credits,
        internal_marks=internal_marks,
        external_marks=external_marks,
        total_marks=total_marks,
        max_marks=max_marks,
        percentage=percentage,
        grade_letter=band.letter,
        grade_points=band.grade_points,
        credit_points=credit_points,
        is_pass=band.is_pass,
        counts_in_gpa=counts_in_gpa,
        grading_scheme=scheme,
        attempt_number=registration.attempt_number,
        source=CourseGradeAward.SOURCE_COMPUTED,
    )


@transaction.atomic
def compute_term_gradesheet(student, term, *, publish=False):
    """
    (Re)computes and returns a TermGradeSheet for one student+term from that
    term's existing CourseGradeAward rows.

    A registration whose award has not been computed yet (marks not entered
    for that course) is simply absent from `awards` and so does not
    contribute to credits_registered — this function is meant to run once a
    term's results are complete, not mid-term. semester_number is read off
    the student's own current_semester_number; it will be 0 if that has not
    been backfilled yet (see backfill_student_academics), which is a display
    placeholder, not something this function tries to infer.
    """
    awards = list(CourseGradeAward.objects.filter(student=student, term=term))

    credits_registered = sum((a.credits for a in awards), ZERO)
    credits_earned = sum((a.credits for a in awards if a.is_pass), ZERO)

    gpa_awards = [a for a in awards if a.counts_in_gpa]
    gpa_credits = sum((a.credits for a in gpa_awards), ZERO)
    credit_points_earned = sum((a.credit_points for a in gpa_awards), ZERO)
    sgpa = round(credit_points_earned / gpa_credits, 2) if gpa_credits else None

    backlog_count = sum(1 for a in awards if not a.is_pass)
    if not awards:
        result_status = "incomplete"
    elif backlog_count:
        result_status = "fail"
    else:
        result_status = "pass"

    sheet, _ = TermGradeSheet.objects.update_or_create(
        student=student, term=term,
        defaults=dict(
            semester_number=student.current_semester_number or 0,
            credits_registered=credits_registered,
            credits_earned=credits_earned,
            credit_points_earned=credit_points_earned,
            sgpa=sgpa,
            backlog_count=backlog_count,
            result_status=result_status,
        ),
    )
    if publish:
        sheet.is_published = True
        sheet.published_at = timezone.now()
        sheet.save(update_fields=["is_published", "published_at"])
    return sheet


@transaction.atomic
def compute_cgpa(student):
    """
    Recomputes StudentAcademicSummary from ALL of a student's published
    CourseGradeAward rows, across every term.

    Policy choice, stated explicitly rather than silently assumed: when a
    course has more than one award (a supplementary or improvement
    re-attempt), the LATEST attempt (highest attempt_number) is the one used
    for the CGPA math. This is the common convention; some institutions
    instead take the best grade across attempts — swap the `max(key=...)`
    below for that policy if a tenant needs it.

    credits_earned counts a course once it has EVER been passed in any
    attempt: an improvement re-attempt does not require re-earning credit
    already banked, even if that later attempt happens to be the one used for
    grade-point math above.
    """
    awards = list(
        CourseGradeAward.objects.filter(student=student, is_published=True)
        .select_related("registration__offering")
    )

    by_course = defaultdict(list)
    for award in awards:
        by_course[award.registration.offering.course_id].append(award)

    credit_points_earned = ZERO
    credits_used = ZERO
    credits_earned = ZERO
    active_backlog_count = 0

    for course_id, course_awards in by_course.items():
        latest = max(course_awards, key=lambda a: a.attempt_number)
        if latest.counts_in_gpa:
            credit_points_earned += latest.credit_points
            credits_used += latest.credits
        if not latest.is_pass:
            active_backlog_count += 1
        if any(a.is_pass for a in course_awards):
            credits_earned += latest.credits

    cgpa = round(credit_points_earned / credits_used, 2) if credits_used else None

    highest_semester_cleared = (
        TermGradeSheet.objects.filter(student=student, result_status="pass")
        .aggregate(m=Max("semester_number"))["m"] or 0
    )

    summary, _ = StudentAcademicSummary.objects.update_or_create(
        student=student,
        defaults=dict(
            credits_earned=credits_earned,
            credit_points_earned=credit_points_earned,
            cgpa=cgpa,
            active_backlog_count=active_backlog_count,
            highest_semester_cleared=highest_semester_cleared,
        ),
    )
    return summary


@transaction.atomic
def publish_term_results(term):
    """
    Computes and publishes a CourseGradeAward for every registration in
    `term` that (a) does not already have one and (b) has published exam
    results to compute one from, then (re)computes and publishes each
    affected student's TermGradeSheet and CGPA.

    Never touches a registration that already has an award — publishing twice
    is a safe no-op for anyone already published, matching the "frozen once
    published" invariant. An actual correction goes through
    recompute_academic_records --include-published, an explicit, separately
    audited action, not a side effect of calling this again.
    """
    registrations = (
        StudentCourseRegistration.objects.filter(
            term=term, status=StudentCourseRegistration.STATUS_REGISTERED,
            grade_award__isnull=True,
        )
        .select_related("student", "offering", "offering__course")
    )

    now = timezone.now()
    new_awards = []
    for registration in registrations:
        award = compute_course_award(registration)
        if award is None:
            continue
        award.is_published = True
        award.published_at = now
        new_awards.append(award)

    CourseGradeAward.objects.bulk_create(new_awards)

    affected_student_ids = {a.student_id for a in new_awards}
    for student in StudentProfile.objects.filter(pk__in=affected_student_ids):
        compute_term_gradesheet(student, term, publish=True)
        compute_cgpa(student)

    return {
        # len(), not .count(): the queryset's result cache was already
        # populated by the for-loop above, so this reuses it instead of
        # issuing a second COUNT query.
        "registrations_considered": len(registrations),
        "awards_created": len(new_awards),
        "students_affected": len(affected_student_ids),
    }

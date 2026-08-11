"""
campusflow_app/services/risk_scoring.py

Rule-based (deliberately NOT machine-learned) dropout/at-risk scoring.

Why rule-based: there is no historical labeled dropout outcome data in this
system (no record of which past students actually dropped out) to train a
classifier against. A model trained on nothing would be fabricating
precision it doesn't have. Instead this combines four observable signals —
attendance, fee-payment delay, exam-performance trend, and assignment
engagement — into a transparent weighted score an evaluator can see the
reasoning behind (see `notes` in compute_risk_score's return value).

SIGNAL_WEIGHTS and RISK_TIER_THRESHOLDS below are starting heuristics
(attendance and fee delay weighted highest, per published findings that
those two signals carry the largest predictive gain) and should be
recalibrated once real cohort outcomes are observed — this is not tuned
against CampusFlow's own data yet, because none exists.

Mirrors the module-level pure-function style of
campusflow_app/services/outcome_attainment.py: functions take an id/model
instance, return plain dicts/tuples, no side effects, no request coupling.
"""

from datetime import timedelta

from django.utils import timezone

from ..models.assignment import Assignment
from ..models.attendance import Attendance
from ..models.fees import StudentFeeInvoice
from ..models.grading import TermGradeSheet
from ..models.lecture import Lecture
from ..models.profile import StudentProfile
from ..models.result import StudentExamResult
from ..models.risk_score import StudentRiskScore
from ..models.submission import AssignmentSubmission

SIGNAL_WEIGHTS = {
    "attendance": 0.35,
    "fees": 0.25,
    "exam_trend": 0.25,
    "assignments": 0.15,
}

RISK_TIER_HIGH_THRESHOLD = 65
RISK_TIER_MEDIUM_THRESHOLD = 35

ATTENDANCE_WINDOW_DAYS = 60
ASSIGNMENT_WINDOW_DAYS = 60
FEE_OVERDUE_TIER_DAYS = (30, 60)  # <30d -> 40 concern, 30-60d -> 70, >60d -> 100
# A 3-point SGPA drop (the common 10-point Indian regulation scale per
# GradingScheme's docstring) is treated as maximum concern. Scoped to the
# common case rather than reading each student's actual GradingScheme.max_points
# — not cleanly reachable from TermGradeSheet without an extra join, and this
# is a starting heuristic anyway (see module docstring).
SGPA_DROP_MAX_CONCERN = 3.0
EXAM_PERCENTAGE_DROP_MAX_CONCERN = 50.0


def _attendance_signal(student_profile):
    """
    Returns (concern_0_100, attendance_rate_0_100) or None if there weren't
    any lectures scheduled for this student's department in the window yet.

    "Scheduled for this student" matches exactly the filter
    LectureListCreateView already uses to decide which lectures a student
    sees (faculty in the student's department) — Lecture has no direct
    Course FK and Attendance is written with `lecture=`, never `schedule=`,
    in every real write path (views/attendance.py, face_attendance.py,
    lecturer_attendance.py), so a course-registration-based join isn't
    available; department-scoped is what the rest of the system already
    uses as "lectures relevant to this student".
    """
    if not student_profile.department_id:
        return None

    now = timezone.now()
    window_start = now - timedelta(days=ATTENDANCE_WINDOW_DAYS)

    expected_lectures = Lecture.objects.filter(
        faculty__teaching_staff_profile__department_id=student_profile.department_id,
        start_time__gte=window_start,
        start_time__lte=now,
    ).exclude(code__isnull=True).exclude(code="")
    expected_count = expected_lectures.count()
    if expected_count == 0:
        return None

    attended_credit = 0.0
    for is_half_day in Attendance.objects.filter(
        user_id=student_profile.user_id, lecture__in=expected_lectures,
    ).values_list("is_half_day", flat=True):
        attended_credit += 0.5 if is_half_day else 1.0

    attendance_rate = min(100.0, (attended_credit / expected_count) * 100)
    concern = max(0.0, 100.0 - attendance_rate)
    return concern, attendance_rate


def _fee_signal(student_profile):
    """
    Returns (concern_0_100, overdue_amount, overdue_invoice_count) — always
    has a value (no data means zero overdue, a legitimate "no risk" answer,
    unlike the other signals where no data means "can't say").
    """
    today = timezone.now().date()
    overdue_invoices = list(
        StudentFeeInvoice.objects.filter(
            student_id=student_profile.user_id, due_date__lt=today,
        ).exclude(status=StudentFeeInvoice.STATUS_PAID)
    )
    if not overdue_invoices:
        return 0.0, 0, 0

    overdue_amount = sum((inv.remaining_balance for inv in overdue_invoices), start=0)
    oldest_days_overdue = max((today - inv.due_date).days for inv in overdue_invoices)

    if len(overdue_invoices) >= 2 or oldest_days_overdue > FEE_OVERDUE_TIER_DAYS[1]:
        concern = 100.0
    elif oldest_days_overdue > FEE_OVERDUE_TIER_DAYS[0]:
        concern = 70.0
    else:
        concern = 40.0
    return concern, overdue_amount, len(overdue_invoices)


def _exam_trend_signal(student_profile):
    """
    Returns (concern_0_100, display_score) or None if there isn't enough
    history to say anything. Prefers TermGradeSheet.sgpa (the stored,
    queryable layer per grading.py's own docstring) across the last
    published terms; falls back to live StudentExamResult percentages
    within the current term when no gradesheet has been published yet.
    """
    sheets = list(
        TermGradeSheet.objects.filter(student=student_profile, is_published=True, sgpa__isnull=False)
        .order_by("-term__academic_year__start_date", "-term__sequence")[:3]
    )
    if len(sheets) >= 2:
        sheets.reverse()  # oldest -> newest
        latest, previous = sheets[-1], sheets[-2]
        drop = float(previous.sgpa) - float(latest.sgpa)
        if drop <= 0:
            return 0.0, float(latest.sgpa)
        concern = min(100.0, (drop / SGPA_DROP_MAX_CONCERN) * 100)
        return concern, float(latest.sgpa)

    # Fall back to in-progress-term raw exam results, same raw material
    # StudentProgressView already sorts chronologically.
    results = list(
        StudentExamResult.objects.filter(student=student_profile).select_related("exam").order_by("exam__date")
    )
    percentages = [r.percentage for r in results if r.percentage is not None]
    if len(percentages) < 2:
        return None

    half = max(1, len(percentages) // 2)
    earlier_avg = sum(percentages[:half]) / half
    recent_avg = sum(percentages[half:]) / (len(percentages) - half)
    drop = earlier_avg - recent_avg
    if drop <= 0:
        return 0.0, recent_avg
    concern = min(100.0, (drop / EXAM_PERCENTAGE_DROP_MAX_CONCERN) * 100)
    return concern, recent_avg


def _assignment_signal(student_profile):
    """Returns (concern_0_100, submission_rate_0_100) or None if nothing was due yet."""
    if not student_profile.department_id:
        return None

    now = timezone.now()
    window_start = now - timedelta(days=ASSIGNMENT_WINDOW_DAYS)

    assignments = Assignment.objects.filter(
        department_id=student_profile.department_id, due_date__gte=window_start, due_date__lte=now,
    )
    assigned_count = assignments.count()
    if assigned_count == 0:
        return None

    submitted_count = AssignmentSubmission.objects.filter(
        student_id=student_profile.user_id, assignment__in=assignments,
    ).count()
    submission_rate = min(100.0, (submitted_count / assigned_count) * 100)
    concern = max(0.0, 100.0 - submission_rate)
    return concern, submission_rate


def _tier_for_score(score):
    if score >= RISK_TIER_HIGH_THRESHOLD:
        return StudentRiskScore.TIER_HIGH
    if score >= RISK_TIER_MEDIUM_THRESHOLD:
        return StudentRiskScore.TIER_MEDIUM
    return StudentRiskScore.TIER_LOW


def compute_risk_score(student_profile: StudentProfile) -> dict:
    """
    Scores one student. Signals that returned None (insufficient data) are
    excluded from the weighted sum and SIGNAL_WEIGHTS is re-normalized over
    only the signals that fired — a student with no fee/attendance concerns
    but no exam history yet is scored on what's actually known, not
    silently treated as risk-free on the missing dimension.
    """
    attendance = _attendance_signal(student_profile)
    fees = _fee_signal(student_profile)
    exam_trend = _exam_trend_signal(student_profile)
    assignments = _assignment_signal(student_profile)

    concerns = {}
    display = {
        "attendance_rate": None,
        "fee_overdue_amount": fees[1],
        "exam_trend_score": None,
        "assignment_submission_rate": None,
    }
    if attendance is not None:
        concerns["attendance"] = attendance[0]
        display["attendance_rate"] = attendance[1]
    concerns["fees"] = fees[0]
    if exam_trend is not None:
        concerns["exam_trend"] = exam_trend[0]
        display["exam_trend_score"] = exam_trend[1]
    if assignments is not None:
        concerns["assignments"] = assignments[0]
        display["assignment_submission_rate"] = assignments[1]

    total_weight = sum(SIGNAL_WEIGHTS[key] for key in concerns)
    risk_score = (
        sum(SIGNAL_WEIGHTS[key] * value for key, value in concerns.items()) / total_weight
        if total_weight > 0 else 0.0
    )

    notes_parts = []
    if display["attendance_rate"] is not None:
        notes_parts.append(f"Attendance {display['attendance_rate']:.0f}% over last {ATTENDANCE_WINDOW_DAYS} days.")
    if display["fee_overdue_amount"]:
        notes_parts.append(f"₹{display['fee_overdue_amount']:.0f} overdue across {fees[2]} invoice(s).")
    if display["exam_trend_score"] is not None and concerns.get("exam_trend", 0) > 0:
        notes_parts.append("Declining exam performance trend.")
    if display["assignment_submission_rate"] is not None and display["assignment_submission_rate"] < 100:
        notes_parts.append(f"Assignment submission rate {display['assignment_submission_rate']:.0f}%.")
    if not notes_parts:
        notes_parts.append("No risk signals detected in available data.")

    return {
        "risk_score": round(risk_score, 1),
        "risk_tier": _tier_for_score(risk_score),
        "attendance_rate": display["attendance_rate"],
        "fee_overdue_amount": display["fee_overdue_amount"],
        "exam_trend_score": display["exam_trend_score"],
        "assignment_submission_rate": display["assignment_submission_rate"],
        "notes": " ".join(notes_parts),
    }


def compute_at_risk_students(department_id=None):
    """
    Batch entry point for the recompute_risk_scores management command.
    Returns a list of (student_profile, score_dict) tuples for every active
    student (excludes dropped/graduated/transferred/on_break students —
    scoring them is meaningless).
    """
    queryset = StudentProfile.objects.filter(academic_status="active")
    if department_id is not None:
        queryset = queryset.filter(department_id=department_id)

    return [(student, compute_risk_score(student)) for student in queryset.select_related("department")]

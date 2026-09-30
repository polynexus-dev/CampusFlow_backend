"""
Detention-list eligibility check — the minimum-attendance-percentage half of
the exam list's eligibility flags, alongside is_student_cleared
(services/clearance.py). Reuses the exact department-scoped Lecture/
Attendance join services/risk_scoring.py's _attendance_signal already
established, windowed to the exam's own Term instead of a rolling lookback,
since a detention decision is "did you attend enough of *this* exam's term",
not "how have you been doing recently".
"""
from ..models.attendance import Attendance
from ..models.exam_administration import AttendanceDetentionSettings
from ..models.lecture import Lecture


def get_detention_settings():
    """Fetch (or lazily create) the tenant's detention rule — same
    get_or_create singleton idiom as get_clearance_settings."""
    settings_row, _ = AttendanceDetentionSettings.objects.get_or_create(pk=1)
    return settings_row


def compute_attendance_rate(student_profile, start_date, end_date):
    """
    Returns (attendance_rate, attended_credit, expected_count) for a student's
    department lectures in [start_date, end_date], or (None, 0, 0) when there
    were no lectures to measure against. A half-day counts as 0.5.
    Shared by is_student_detained and the student attendance-summary API so
    both agree on what "attendance %" means.
    """
    expected_lectures = Lecture.objects.filter(
        faculty__teaching_staff_profile__department_id=student_profile.department_id,
        start_time__date__gte=start_date,
        start_time__date__lte=end_date,
    ).exclude(code__isnull=True).exclude(code="")
    expected_count = expected_lectures.count()
    if expected_count == 0:
        return None, 0, 0

    attended_credit = 0.0
    for is_half_day in Attendance.objects.filter(
        user_id=student_profile.user_id, lecture__in=expected_lectures,
    ).values_list("is_half_day", flat=True):
        attended_credit += 0.5 if is_half_day else 1.0

    return min(100.0, (attended_credit / expected_count) * 100), attended_credit, expected_count


def is_student_detained(student_profile, exam):
    """
    Returns (is_detained, attendance_rate_or_none).

    Nothing blocks (False, None) when: detention isn't enabled, the student
    has no department, the exam has no Term to scope the window to (see
    Exam.term's docstring — not yet backfilled for every exam), or there
    were no lectures in that window to measure against. Silence here means
    "can't say", not "cleared" — but unlike is_student_cleared, an
    unmeasurable attendance window has no reasonable default other than not
    blocking, since there's nothing to hold the student to.
    """
    settings_row = get_detention_settings()
    if not settings_row.is_enabled:
        return False, None
    if not student_profile.department_id or not exam.term_id:
        return False, None

    term = exam.term
    attendance_rate, _, _ = compute_attendance_rate(student_profile, term.start_date, term.end_date)
    if attendance_rate is None:
        return False, None

    is_detained = attendance_rate < float(settings_row.minimum_attendance_percent)
    return is_detained, attendance_rate

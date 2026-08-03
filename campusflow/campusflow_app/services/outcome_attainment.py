"""
NBA Outcome-Based Education — class-level CO attainment and its roll-up to
Program Outcome attainment (Docs/compliance_and_audit_portal_plan.md §4 Phase
C: "Attainment % calculated from existing exam marks data, rolled up from CO
to PO"). This is the one piece the plan flagged as genuinely new work; the
per-student version of the same extraction loop already existed in
views/progress.py (StudentTopicPerformanceView) — this module generalises it
from one student to every student who sat an exam for the course, which is
what a class-level CO attainment (and therefore an NBA SAR) actually needs.
"""
from collections import defaultdict

from ..models.exam import Exam
from ..models.outcomes import CourseOutcome, ProgramOutcome
from ..models.valuation import ScannedPaper


def _extract_score_and_max(raw, spec):
    """Same per-question extraction rule as StudentTopicPerformanceView:
    question_scores entries are either a plain number or a
    {'score','max_marks','note'} dict; question_structure entries are either
    a plain max-marks number or a {'topic','course_outcome','marks'} dict."""
    obtained = raw.get('score') if isinstance(raw, dict) else raw
    try:
        obtained = float(obtained)
    except (TypeError, ValueError):
        return None, None, None

    if isinstance(spec, dict):
        co_code = spec.get('course_outcome')
        max_marks = spec.get('marks')
    else:
        co_code = None
        max_marks = spec

    if isinstance(raw, dict) and raw.get('max_marks') is not None:
        max_marks = raw.get('max_marks')

    try:
        max_marks = float(max_marks)
    except (TypeError, ValueError):
        return None, None, None

    return obtained, max_marks, co_code


def compute_course_outcome_class_attainment(course_id):
    """
    For every CourseOutcome defined on this course, aggregates every
    evaluated student's marks on questions tagged with that CO, then reports
    what fraction of students cleared the CO's own per-student threshold
    (`target_attainment_percent`) — the class-level attainment NBA's SAR asks
    for, compared against `target_student_percent` to say whether the course
    "attained" that outcome this term.
    """
    papers = (
        ScannedPaper.objects
        .filter(session__exam__course_id=course_id, status='Evaluated')
        .select_related('session__exam')
    )

    # student_id -> co_code -> {obtained, max_marks}
    student_co_scores = defaultdict(lambda: defaultdict(lambda: {"obtained": 0.0, "max_marks": 0.0}))

    for paper in papers:
        structure = paper.session.exam.question_structure or {}
        scores = paper.question_scores or {}
        if not structure or not scores:
            continue

        for q_key, raw in scores.items():
            spec = structure.get(q_key)
            if spec is None:
                continue
            obtained, max_marks, co_code = _extract_score_and_max(raw, spec)
            if obtained is None or max_marks is None or not co_code:
                continue
            entry = student_co_scores[paper.student_id][co_code]
            entry["obtained"] += obtained
            entry["max_marks"] += max_marks

    co_codes_seen = {code for co_map in student_co_scores.values() for code in co_map.keys()}
    course_outcomes = CourseOutcome.objects.filter(course_id=course_id, code__in=co_codes_seen)

    results = []
    for co in course_outcomes:
        student_percentages = []
        for co_map in student_co_scores.values():
            entry = co_map.get(co.code)
            if entry and entry["max_marks"]:
                student_percentages.append((entry["obtained"] / entry["max_marks"]) * 100)

        if not student_percentages:
            continue

        target_attainment = float(co.target_attainment_percent)
        target_student = float(co.target_student_percent)
        students_meeting_target = sum(1 for p in student_percentages if p >= target_attainment)
        class_percent_meeting_target = round((students_meeting_target / len(student_percentages)) * 100, 2)

        results.append({
            "course_outcome_id": co.id,
            "code": co.code,
            "statement": co.statement,
            "target_attainment_percent": target_attainment,
            "target_student_percent": target_student,
            "students_considered": len(student_percentages),
            "students_meeting_target": students_meeting_target,
            "class_percent_meeting_target": class_percent_meeting_target,
            "attained": class_percent_meeting_target >= target_student,
            # The CO's own contribution to a PO roll-up — the class-level
            # percentage-meeting-target, not the raw class average, since
            # that's what target_student_percent is actually measuring.
            "attainment_value": class_percent_meeting_target,
        })

    results.sort(key=lambda r: r["code"])
    return results


def compute_program_outcome_attainment(program_id):
    """
    Rolls CO attainment up to each ProgramOutcome via the CO-PO correlation
    matrix (POCOMapping), using the standard weighted-by-correlation-strength
    method: PO attainment = sum(CO attainment x strength) / sum(strength),
    over every CO mapped to that PO with a computed attainment value.
    """
    program_outcomes = (
        ProgramOutcome.objects
        .filter(program_id=program_id)
        .prefetch_related('co_mappings__course_outcome__course')
    )

    co_attainment_cache = {}  # course_id -> {co_code: attainment_value}

    def get_co_attainment(course_id, co_code):
        if course_id not in co_attainment_cache:
            co_attainment_cache[course_id] = {
                r["code"]: r["attainment_value"]
                for r in compute_course_outcome_class_attainment(course_id)
            }
        return co_attainment_cache[course_id].get(co_code)

    results = []
    for po in program_outcomes:
        weighted_sum = 0.0
        total_weight = 0
        contributing = []

        for mapping in po.co_mappings.all():
            co = mapping.course_outcome
            attainment_value = get_co_attainment(co.course_id, co.code)
            if attainment_value is None:
                continue
            weighted_sum += attainment_value * mapping.strength
            total_weight += mapping.strength
            contributing.append({
                "course_code": co.course.course_code,
                "course_outcome_code": co.code,
                "correlation_strength": mapping.strength,
                "attainment_value": attainment_value,
            })

        po_attainment = round(weighted_sum / total_weight, 2) if total_weight else None

        results.append({
            "program_outcome_id": po.id,
            "code": po.code,
            "kind": po.kind,
            "statement": po.statement,
            "attainment_percent": po_attainment,
            "contributing_course_outcomes": contributing,
        })

    return results

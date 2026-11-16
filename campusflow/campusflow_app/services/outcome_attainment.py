"""
NBA Outcome-Based Education — class-level CO attainment and its roll-up to
Program Outcome attainment (Docs/compliance_and_audit_portal_plan.md §4 Phase
C: "Attainment % calculated from existing exam marks data, rolled up from CO
to PO"). This is the one piece the plan flagged as genuinely new work; the
per-student version of the same extraction loop already existed in
views/progress.py (StudentTopicPerformanceView) — this module generalises it
from one student to every student who sat an exam for the course, which is
what a class-level CO attainment (and therefore an NBA SAR) actually needs.

`compute_program_outcome_attainment`'s result blends in indirect (survey)
attainment from models/indirect_attainment.py using NBA's standard 80:20
direct:indirect split at the PO level — the same ratio nearly every NBA SAR
template in circulation uses, distinct from (and not to be confused with)
how the four indirect *channels themselves* are combined, which NBA does not
mandate a fixed split for (handled by equal-weight-per-channel below).
"""
from collections import defaultdict

from ..models.indirect_attainment import OutcomeIndirectSurveyResponse
from ..models.outcomes import CourseOutcome, ProgramOutcome
from .co_evidence import collect_course_evidence

DIRECT_ATTAINMENT_WEIGHT = 0.8
INDIRECT_ATTAINMENT_WEIGHT = 0.2


def _student_percent(by_source, weights):
    """One student's percentage on one CO.

    weights=None pools raw marks across every source (sum obtained / sum max),
    which is exactly the pre-multi-source behaviour when only exams exist.
    With weights, each source's own percentage is averaged by its weight
    (e.g. {"exam": 0.6, "assignment": 0.2, "rubric": 0.2}), over the sources
    this student actually has evidence in."""
    if weights is None:
        obtained = sum(e["obtained"] for e in by_source.values())
        max_marks = sum(e["max_marks"] for e in by_source.values())
        return (obtained / max_marks) * 100 if max_marks else None

    weighted_sum = 0.0
    total_weight = 0.0
    for source, entry in by_source.items():
        weight = float(weights.get(source, 0))
        if weight <= 0 or not entry["max_marks"]:
            continue
        weighted_sum += (entry["obtained"] / entry["max_marks"]) * 100 * weight
        total_weight += weight
    return weighted_sum / total_weight if total_weight else None


def compute_course_outcome_class_attainment(course_id, weights=None, sources=None):
    """
    For every CourseOutcome defined on this course, aggregates every
    student's CO-tagged marks from every evidence source (end-sem/internal
    answer scripts, assignments, rubric assessments; see
    services/co_evidence.py), then reports what fraction of students cleared
    the CO's own per-student threshold (`target_attainment_percent`) — the
    class-level attainment NBA's SAR asks for, compared against
    `target_student_percent` to say whether the course "attained" that
    outcome this term.

    `weights` optionally weights sources against each other (see
    _student_percent); `sources` optionally restricts which are used.
    Each result carries a `source_breakdown` so the SAR can show direct
    attainment split by exam / assignment / rubric.
    """
    # student_id -> co_code -> source -> {obtained, max_marks}
    student_co_scores = defaultdict(
        lambda: defaultdict(lambda: defaultdict(lambda: {"obtained": 0.0, "max_marks": 0.0}))
    )
    for evidence in collect_course_evidence(course_id, sources=sources):
        entry = student_co_scores[evidence.student_id][evidence.co_code][evidence.source]
        entry["obtained"] += evidence.obtained
        entry["max_marks"] += evidence.max_marks

    co_codes_seen = {code for co_map in student_co_scores.values() for code in co_map.keys()}
    course_outcomes = CourseOutcome.objects.filter(course_id=course_id, code__in=co_codes_seen)

    results = []
    for co in course_outcomes:
        student_percentages = []
        # source -> [per-student percentage within that source]
        per_source = defaultdict(list)
        for co_map in student_co_scores.values():
            by_source = co_map.get(co.code)
            if not by_source:
                continue
            percent = _student_percent(by_source, weights)
            if percent is not None:
                student_percentages.append(percent)
            for source, entry in by_source.items():
                if entry["max_marks"]:
                    per_source[source].append((entry["obtained"] / entry["max_marks"]) * 100)

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
            "source_breakdown": {
                source: {
                    "students": len(values),
                    "average_percent": round(sum(values) / len(values), 2),
                }
                for source, values in sorted(per_source.items())
            },
        })

    results.sort(key=lambda r: r["code"])
    return results


def compute_program_outcome_indirect_attainment(program_id, academic_year_id=None):
    """
    Converts each Program Outcome's 1-5 Likert survey ratings into a
    percentage (average / 5 x 100), per indirect channel (course-exit,
    programme-exit, employer, alumni), then blends the channels with equal
    weight across whichever ones actually have responses — NBA's SAR
    template does not mandate a fixed split between the four channels
    themselves, only the direct:indirect split this feeds into (see
    DIRECT_ATTAINMENT_WEIGHT / INDIRECT_ATTAINMENT_WEIGHT above). Equal
    weighting also means a channel nobody has surveyed yet (e.g. no alumni
    responses collected this year) simply doesn't participate, rather than
    silently dragging the average toward zero.

    Returns {program_outcome_id: {"indirect_attainment_percent": float|None,
    "channel_breakdown": {survey_type: {...}}}}.
    """
    responses = OutcomeIndirectSurveyResponse.objects.filter(survey__program_id=program_id)
    if academic_year_id is not None:
        responses = responses.filter(survey__academic_year_id=academic_year_id)

    # program_outcome_id -> survey_type -> [ratings]
    ratings_by_po_and_channel = defaultdict(lambda: defaultdict(list))
    for row in responses.values("program_outcome_id", "survey__survey_type", "rating"):
        ratings_by_po_and_channel[row["program_outcome_id"]][row["survey__survey_type"]].append(row["rating"])

    results = {}
    for po_id, by_channel in ratings_by_po_and_channel.items():
        channel_percentages = []
        breakdown = {}
        for survey_type, values in by_channel.items():
            average_rating = sum(values) / len(values)
            channel_percent = round((average_rating / 5) * 100, 2)
            channel_percentages.append(channel_percent)
            breakdown[survey_type] = {
                "average_rating": round(average_rating, 2),
                "response_count": len(values),
                "attainment_percent": channel_percent,
            }
        results[po_id] = {
            "indirect_attainment_percent": (
                round(sum(channel_percentages) / len(channel_percentages), 2) if channel_percentages else None
            ),
            "channel_breakdown": breakdown,
        }
    return results


def compute_program_outcome_attainment(program_id, academic_year_id=None):
    """
    Rolls CO attainment up to each ProgramOutcome via the CO-PO correlation
    matrix (POCOMapping), using the standard weighted-by-correlation-strength
    method: direct PO attainment = sum(CO attainment x strength) / sum(strength),
    over every CO mapped to that PO with a computed attainment value. Then
    blends in indirect (survey) attainment at NBA's standard 80:20 ratio.

    When a PO has direct attainment but no indirect survey data yet (the
    common case before a survey cycle closes), `attainment_percent` falls
    back to the direct figure alone rather than fabricating an indirect
    component — the same "don't blend with a number that doesn't exist yet"
    rule the rest of this codebase's reports follow.
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

    indirect_by_po = compute_program_outcome_indirect_attainment(program_id, academic_year_id=academic_year_id)

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

        direct_attainment = round(weighted_sum / total_weight, 2) if total_weight else None

        indirect_entry = indirect_by_po.get(po.id, {})
        indirect_attainment = indirect_entry.get("indirect_attainment_percent")

        if direct_attainment is not None and indirect_attainment is not None:
            overall_attainment = round(
                DIRECT_ATTAINMENT_WEIGHT * direct_attainment + INDIRECT_ATTAINMENT_WEIGHT * indirect_attainment, 2,
            )
        else:
            overall_attainment = direct_attainment

        results.append({
            "program_outcome_id": po.id,
            "code": po.code,
            "kind": po.kind,
            "statement": po.statement,
            "direct_attainment_percent": direct_attainment,
            "indirect_attainment_percent": indirect_attainment,
            "indirect_channel_breakdown": indirect_entry.get("channel_breakdown", {}),
            "attainment_percent": overall_attainment,
            "contributing_course_outcomes": contributing,
        })

    return results

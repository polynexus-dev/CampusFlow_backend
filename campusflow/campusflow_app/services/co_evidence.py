"""
Course Outcome evidence: every assessment source that can produce
CO-tagged marks, behind one interface. Docs/college_gap_closure_plan.md §1.0.

Each source yields CoEvidence(student_id, co_code, obtained, max_marks, source),
where student_id is a StudentProfile pk. services/outcome_attainment.py sums
these per student per CO to compute class-level attainment, so adding a new
assessment type (online tests in Phase 2, events in Phase 3) only means
adding a function here and registering it in EVIDENCE_SOURCES.
"""
from collections import namedtuple

from ..models.profile import StudentProfile
from ..models.rubrics import RubricScore
from ..models.submission import AssignmentSubmission
from ..models.valuation import ScannedPaper

CoEvidence = namedtuple("CoEvidence", "student_id co_code obtained max_marks source")

SOURCE_EXAM = "exam"
SOURCE_ASSIGNMENT = "assignment"
SOURCE_RUBRIC = "rubric"


def _to_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract_score_and_max(raw, spec):
    """Same per-question extraction rule as StudentTopicPerformanceView:
    question_scores entries are either a plain number or a
    {'score','max_marks','note'} dict; question_structure entries are either
    a plain max-marks number or a {'topic','course_outcome','marks'} dict."""
    obtained = _to_float(raw.get('score') if isinstance(raw, dict) else raw)
    if obtained is None:
        return None, None, None

    if isinstance(spec, dict):
        co_code = spec.get('course_outcome')
        max_marks = spec.get('marks')
    else:
        co_code = None
        max_marks = spec

    if isinstance(raw, dict) and raw.get('max_marks') is not None:
        max_marks = raw.get('max_marks')

    max_marks = _to_float(max_marks)
    if max_marks is None:
        return None, None, None
    return obtained, max_marks, co_code


def scanned_paper_evidence(course_id):
    """Evaluated answer scripts, per question, against Exam.question_structure."""
    papers = (
        ScannedPaper.objects
        .filter(session__exam__course_id=course_id, status='Evaluated')
        .select_related('session__exam')
    )
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
            yield CoEvidence(paper.student_id, co_code, obtained, max_marks, SOURCE_EXAM)


def assignment_evidence(course_id):
    """Graded submissions on CO-tagged assignments that have numeric max_marks."""
    submissions = (
        AssignmentSubmission.objects
        .filter(
            assignment__course_id=course_id,
            assignment__course_outcome__isnull=False,
            assignment__max_marks__gt=0,
            marks_obtained__isnull=False,
        )
        .select_related('assignment__course_outcome')
    )
    rows = list(submissions)
    if not rows:
        return
    # AssignmentSubmission.student is a User; attainment is keyed by StudentProfile.
    profile_ids = dict(
        StudentProfile.objects
        .filter(user_id__in={s.student_id for s in rows})
        .values_list('user_id', 'id')
    )
    for submission in rows:
        student_id = profile_ids.get(submission.student_id)
        if student_id is None:
            continue
        yield CoEvidence(
            student_id,
            submission.assignment.course_outcome.code,
            float(submission.marks_obtained),
            float(submission.assignment.max_marks),
            SOURCE_ASSIGNMENT,
        )


def rubric_evidence(course_id):
    """Each criterion score on a CO-tagged criterion of a rubric for this course.

    A criterion's max is its best level's score; both sides are multiplied by
    the criterion weight so heavier criteria count for more."""
    scores = (
        RubricScore.objects
        .filter(
            criterion__rubric__course_id=course_id,
            criterion__course_outcome__isnull=False,
        )
        .select_related('assessment', 'criterion__course_outcome', 'level')
        .prefetch_related('criterion__levels')
    )
    best_by_criterion = {}
    for score in scores:
        criterion = score.criterion
        if criterion.id not in best_by_criterion:
            best_by_criterion[criterion.id] = max(
                (float(level.score) for level in criterion.levels.all()), default=0.0,
            )
        best = best_by_criterion[criterion.id]
        if best <= 0:
            continue
        weight = float(criterion.weight)
        yield CoEvidence(
            score.assessment.student_id,
            criterion.course_outcome.code,
            float(score.level.score) * weight,
            best * weight,
            SOURCE_RUBRIC,
        )


EVIDENCE_SOURCES = {
    SOURCE_EXAM: scanned_paper_evidence,
    SOURCE_ASSIGNMENT: assignment_evidence,
    SOURCE_RUBRIC: rubric_evidence,
}


def collect_course_evidence(course_id, sources=None):
    """All CO evidence for a course, from every registered source (or a subset)."""
    for name, source in EVIDENCE_SOURCES.items():
        if sources is not None and name not in sources:
            continue
        yield from source(course_id)

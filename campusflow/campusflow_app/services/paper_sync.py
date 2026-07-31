"""
Bridges the new paper-setting module (ExamQuestion rows) into the
already-working Exam.question_structure convention that
views/exam.py's validate_question_structure and
views/progress.py's StudentTopicPerformanceView already read — so that
existing analytics/valuation code keeps working unmodified.

Also snapshots the resolved course outcome the same way it already snapshots
the topic name: at compose time, from the real objects this function already
has in hand, rather than making StudentTopicPerformanceView re-resolve a
topic string back to a CourseOutcome on every read.
"""


def _resolve_course_outcome_code(eq):
    """ExamQuestion.course_outcome -> Question.course_outcome ->
    SyllabusTopic.course_outcome -> None. Same override order the model
    docstrings in models/outcomes.py describe."""
    if eq.course_outcome_id:
        return eq.course_outcome.code
    if eq.question_id and eq.question.course_outcome_id:
        return eq.question.course_outcome.code
    if eq.topic_id and eq.topic.course_outcome_id:
        return eq.topic.course_outcome.code
    return None


def sync_question_structure(exam):
    """Rebuild exam.question_structure from its current ExamQuestion rows
    and save. Call after any generate/add/replace/update/remove."""
    structure = {}
    for eq in exam.exam_questions.select_related(
        "topic__course_outcome", "question__course_outcome", "course_outcome",
    ).order_by("order"):
        structure[eq.question_label] = {
            "marks": float(eq.marks),
            "topic": eq.topic.name if eq.topic_id else None,
            "course_outcome": _resolve_course_outcome_code(eq),
        }
    exam.question_structure = structure
    exam.save(update_fields=["question_structure"])

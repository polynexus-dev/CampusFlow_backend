"""
Bridges the new paper-setting module (ExamQuestion rows) into the
already-working Exam.question_structure convention that
views/exam.py's validate_question_structure and
views/progress.py's StudentTopicPerformanceView already read — so that
existing analytics/valuation code keeps working unmodified.
"""


def sync_question_structure(exam):
    """Rebuild exam.question_structure from its current ExamQuestion rows
    and save. Call after any generate/add/replace/update/remove."""
    structure = {}
    for eq in exam.exam_questions.select_related("topic").order_by("order"):
        structure[eq.question_label] = {
            "marks": float(eq.marks),
            "topic": eq.topic.name if eq.topic_id else None,
        }
    exam.question_structure = structure
    exam.save(update_fields=["question_structure"])

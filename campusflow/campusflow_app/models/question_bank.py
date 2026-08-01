from django.db import models
from django.contrib.auth.models import User
from .course import Course
from .exam import Exam


class SyllabusTopic(models.Model):
    """One topic/unit within a course's syllabus — the thing a paper
    blueprint allocates marks against and a question bank entry is tagged
    with."""
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="syllabus_topics")
    name = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    description = models.TextField(blank=True)
    # The ~95% case: a syllabus unit maps to one outcome. Question/ExamQuestion
    # carry their own override for the remainder — see models/outcomes.py.
    course_outcome = models.ForeignKey(
        "campusflow_app.CourseOutcome", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="syllabus_topics",
    )

    class Meta:
        db_table = "syllabus_topics"
        verbose_name = "Syllabus Topic"
        verbose_name_plural = "Syllabus Topics"
        constraints = [
            models.UniqueConstraint(fields=["course", "name"], name="unique_course_topic_name"),
        ]
        ordering = ["order", "name"]

    def __str__(self):
        return f"{self.course.course_code} · {self.name}"


class Question(models.Model):
    """A reusable question-bank entry, tagged by topic and difficulty."""
    DIFFICULTY_EASY = "easy"
    DIFFICULTY_MEDIUM = "medium"
    DIFFICULTY_HARD = "hard"
    DIFFICULTY_CHOICES = [
        (DIFFICULTY_EASY, "Easy"),
        (DIFFICULTY_MEDIUM, "Medium"),
        (DIFFICULTY_HARD, "Hard"),
    ]

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="question_bank")
    topic = models.ForeignKey(
        SyllabusTopic, on_delete=models.SET_NULL, null=True, blank=True, related_name="questions",
    )
    text = models.TextField()
    marks = models.DecimalField(max_digits=5, decimal_places=2)
    difficulty = models.CharField(max_length=10, choices=DIFFICULTY_CHOICES, default=DIFFICULTY_MEDIUM)
    # Direct override of topic.course_outcome — for a question that spans two
    # units but assesses one specific outcome.
    course_outcome = models.ForeignKey(
        "campusflow_app.CourseOutcome", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="questions",
    )
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="questions_created")
    is_active = models.BooleanField(
        default=True,
        help_text="Soft-disable instead of delete — past papers keep their snapshot regardless.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "question_bank"
        verbose_name = "Question"
        verbose_name_plural = "Question Bank"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.course.course_code} · {self.text[:60]} ({self.marks} marks)"


class PaperBlueprintTopic(models.Model):
    """One row of an exam's paper blueprint: how many marks worth of
    questions should be drawn from a given topic."""
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="blueprint_topics")
    topic = models.ForeignKey(SyllabusTopic, on_delete=models.CASCADE, related_name="blueprint_entries")
    target_marks = models.DecimalField(max_digits=5, decimal_places=2)

    class Meta:
        db_table = "paper_blueprint_topics"
        verbose_name = "Paper Blueprint Topic"
        verbose_name_plural = "Paper Blueprint Topics"
        constraints = [
            models.UniqueConstraint(fields=["exam", "topic"], name="unique_exam_blueprint_topic"),
        ]

    def __str__(self):
        return f"{self.exam.name} · {self.topic.name} · {self.target_marks} marks"


class ExamQuestion(models.Model):
    """
    One question composed into an exam's paper. Snapshots the bank
    question's text/marks/topic at the time it's added/replaced so an
    already-composed paper doesn't silently change if the bank entry is
    later edited or archived.
    """
    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name="exam_questions")
    question = models.ForeignKey(
        Question, on_delete=models.SET_NULL, null=True, blank=True, related_name="exam_usages",
    )
    question_label = models.CharField(max_length=10, help_text="e.g. Q1 — matches Exam.question_structure's key convention.")
    question_text_snapshot = models.TextField()
    marks = models.DecimalField(max_digits=5, decimal_places=2)
    topic = models.ForeignKey(SyllabusTopic, on_delete=models.SET_NULL, null=True, blank=True, related_name="exam_questions")
    # Direct override, same reasoning as Question.course_outcome. Resolution
    # order at sync time (services/paper_sync.py) is this -> question's ->
    # topic's -> untagged.
    course_outcome = models.ForeignKey(
        "campusflow_app.CourseOutcome", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="exam_questions",
    )
    order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "exam_questions"
        verbose_name = "Exam Question"
        verbose_name_plural = "Exam Questions"
        constraints = [
            models.UniqueConstraint(fields=["exam", "question_label"], name="unique_exam_question_label"),
        ]
        ordering = ["order"]

    def __str__(self):
        return f"{self.exam.name} · {self.question_label} ({self.marks} marks)"

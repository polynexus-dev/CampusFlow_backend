"""
Rubric-based assessment for labs, projects, internships, seminars and vivas.
Docs/college_gap_closure_plan.md §1.2.

Each criterion can be tagged with a CourseOutcome, so every RubricScore
becomes CO evidence (services/co_evidence.py rubric_evidence) and moves the
course's CO attainment and the NBA SAR export.
"""
from django.contrib.auth.models import User
from django.db import models

from .course import Course
from .profile import StudentProfile


class Rubric(models.Model):
    APPLIES_LAB = "lab"
    APPLIES_PROJECT = "project"
    APPLIES_INTERNSHIP = "internship"
    APPLIES_ASSIGNMENT = "assignment"
    APPLIES_SEMINAR = "seminar"
    APPLIES_VIVA = "viva"
    APPLIES_OTHER = "other"
    APPLIES_CHOICES = [
        (APPLIES_LAB, "Lab"),
        (APPLIES_PROJECT, "Project"),
        (APPLIES_INTERNSHIP, "Internship"),
        (APPLIES_ASSIGNMENT, "Assignment"),
        (APPLIES_SEMINAR, "Seminar"),
        (APPLIES_VIVA, "Viva"),
        (APPLIES_OTHER, "Other"),
    ]

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, null=True, blank=True, related_name="rubrics",
        help_text="Leave empty for a rubric shared across courses (criteria then carry no CO tag).",
    )
    applies_to = models.CharField(max_length=20, choices=APPLIES_CHOICES, default=APPLIES_OTHER)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="rubrics_created")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    @property
    def max_score(self):
        """Sum over criteria of (best level score x weight)."""
        total = 0.0
        for criterion in self.criteria.all():
            best = max((float(level.score) for level in criterion.levels.all()), default=0.0)
            total += best * float(criterion.weight)
        return total


class RubricCriterion(models.Model):
    rubric = models.ForeignKey(Rubric, on_delete=models.CASCADE, related_name="criteria")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    course_outcome = models.ForeignKey(
        "campusflow_app.CourseOutcome", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="rubric_criteria",
    )
    weight = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["rubric", "order", "id"]

    def __str__(self):
        return f"{self.rubric.name}: {self.title}"


class RubricLevel(models.Model):
    criterion = models.ForeignKey(RubricCriterion, on_delete=models.CASCADE, related_name="levels")
    label = models.CharField(max_length=100, help_text='e.g. "Excellent", "Satisfactory".')
    score = models.DecimalField(max_digits=6, decimal_places=2)
    descriptor = models.TextField(blank=True, help_text="What performance at this level looks like.")

    class Meta:
        ordering = ["criterion", "-score"]
        constraints = [
            models.UniqueConstraint(fields=["criterion", "label"], name="uniq_rubric_level_label"),
        ]

    def __str__(self):
        return f"{self.criterion.title}: {self.label} ({self.score})"


class RubricAssessment(models.Model):
    """One evaluator's rubric assessment of one student on one piece of work."""
    rubric = models.ForeignKey(Rubric, on_delete=models.PROTECT, related_name="assessments")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="rubric_assessments")
    evaluator = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="rubric_assessments_given")
    assignment = models.ForeignKey(
        "campusflow_app.Assignment", on_delete=models.CASCADE, null=True, blank=True, related_name="rubric_assessments",
    )
    exam = models.ForeignKey(
        "campusflow_app.Exam", on_delete=models.CASCADE, null=True, blank=True, related_name="rubric_assessments",
    )
    context_label = models.CharField(
        max_length=255, blank=True, help_text='For work with no Assignment/Exam row, e.g. "Lab 4: Op-amp circuits".',
    )
    overall_comment = models.TextField(blank=True)
    total_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    max_score = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    assessed_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-assessed_at"]

    def __str__(self):
        return f"{self.rubric.name} for {self.student.student_id}"


class RubricScore(models.Model):
    assessment = models.ForeignKey(RubricAssessment, on_delete=models.CASCADE, related_name="scores")
    criterion = models.ForeignKey(RubricCriterion, on_delete=models.CASCADE, related_name="scores")
    level = models.ForeignKey(RubricLevel, on_delete=models.PROTECT, related_name="scores")
    comment = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["assessment", "criterion"], name="uniq_rubric_score_per_criterion"),
        ]

    def __str__(self):
        return f"{self.criterion.title}: {self.level.label}"

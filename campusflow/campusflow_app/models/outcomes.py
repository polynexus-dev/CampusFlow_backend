"""
Outcome-Based Education: Program Outcomes, Course Outcomes, and the CO-PO
articulation matrix NBA's SAR asks for.

The seam this attaches to already exists and is precise: `SyllabusTopic`
(models/question_bank.py) is a syllabus unit ("Unit III"); `CourseOutcome` is
a peer of it at the Course level, not a kind of it — topics and outcomes are
genuinely different axes (syllabus structure vs assessed capability), mapped
loosely in practice but distinct in what they represent. `SyllabusTopic` gets
a nullable `course_outcome` FK for the ~95% case where a topic maps to one
outcome; `Question` and `ExamQuestion` each get their own nullable
`course_outcome` FK as a direct override for the remainder — a question
spanning two units but assessing one specific outcome.

Because `Course` is regulation-scoped (models/course.py), `CourseOutcome`
(course) is automatically per-regulation — a curriculum revision gets its own
outcome set for free, the same way it gets its own credits.

`StudentTopicPerformanceView` (views/progress.py) already computes per-topic
attainment by joining ScannedPaper.question_scores against
Exam.question_structure; services/paper_sync.py already snapshots each
ExamQuestion's resolved topic name into that structure when a paper is
composed. Both are extended, not replaced, to also snapshot and group by the
resolved course outcome — see the CHANGELOG-style comments at each site.
"""

from django.db import models

from .course import Course


class ProgramOutcome(models.Model):
    """A PO, PSO or PEO statement for a Program — the row a CourseOutcome maps to."""

    KIND_PO = "po"
    KIND_CHOICES = [
        (KIND_PO, "Programme Outcome"),
        ("pso", "Programme Specific Outcome"),
        ("peo", "Programme Educational Objective"),
    ]

    program = models.ForeignKey(
        "campusflow_app.Program", on_delete=models.CASCADE, related_name="outcomes",
    )
    kind = models.CharField(max_length=4, choices=KIND_CHOICES, default=KIND_PO)
    code = models.CharField(max_length=10, help_text='e.g. "PO1", "PSO2".')
    statement = models.TextField()
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Program Outcome"
        verbose_name_plural = "Program Outcomes"
        ordering = ["kind", "order", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "kind", "code"], name="uniq_program_outcome_code",
            ),
        ]

    def __str__(self):
        return f"{self.program.code} {self.code}"


class CourseOutcome(models.Model):
    """A CO statement for a Course — what StudentTopicPerformanceView's
    generalised attainment loop groups by."""

    BLOOM_CHOICES = [
        ("remember", "Remember"), ("understand", "Understand"), ("apply", "Apply"),
        ("analyse", "Analyse"), ("evaluate", "Evaluate"), ("create", "Create"),
    ]

    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="course_outcomes")
    code = models.CharField(max_length=10, help_text='e.g. "CO1".')
    statement = models.TextField()
    bloom_level = models.CharField(max_length=12, choices=BLOOM_CHOICES, blank=True)
    target_attainment_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=60,
        help_text="% a student must score on this CO's tagged questions to count as attained.",
    )
    target_student_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=60,
        help_text="% of students who must clear the threshold above for class-level attainment.",
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Course Outcome"
        verbose_name_plural = "Course Outcomes"
        ordering = ["order", "code"]
        constraints = [
            models.UniqueConstraint(fields=["course", "code"], name="uniq_course_outcome_code"),
        ]

    def __str__(self):
        return f"{self.course.course_code} {self.code}"


class POCOMapping(models.Model):
    """The CO-PO articulation matrix, with the 1/2/3 strength NBA's SAR asks for."""

    STRENGTH_CHOICES = [(1, "Low (1)"), (2, "Medium (2)"), (3, "High (3)")]

    course_outcome = models.ForeignKey(
        CourseOutcome, on_delete=models.CASCADE, related_name="po_mappings",
    )
    program_outcome = models.ForeignKey(
        ProgramOutcome, on_delete=models.CASCADE, related_name="co_mappings",
    )
    strength = models.PositiveSmallIntegerField(default=1, choices=STRENGTH_CHOICES)

    class Meta:
        verbose_name = "CO-PO Mapping"
        verbose_name_plural = "CO-PO Mappings"
        constraints = [
            models.UniqueConstraint(
                fields=["course_outcome", "program_outcome"], name="uniq_co_po_pair",
            ),
        ]

    def __str__(self):
        return f"{self.course_outcome.code} -> {self.program_outcome.code} ({self.strength})"

from django.db import models
from django.db.models import Q

from .department import Department


# Course Model (now linked to Department only — college scoping is via tenant schema)
class Course(models.Model):
    """
    A subject/paper *as defined by one regulation* — not a degree programme, which
    is `Program`.

    The name stays `Course` because six models FK it (Exam, Schedule, Assignment,
    SyllabusTopic, Question, and ExamQuestion via topic), and because a rename
    would prompt during the auto-makemigrations that runs on the production host.

    Credits live here rather than on a separate CurriculumCourse join. The
    alternative was considered and rejected: all six FKs point at Course, so
    `exam.course.credits` would have to become
    `CurriculumCourse.objects.get(course=..., regulation=???)`, where the
    regulation can only come from the student — making credit resolution
    per-(result, student) and able to silently pick the wrong scheme's row. That
    is the class of bug that quietly corrupts a transcript. The cost of absorbing
    is that an unchanged course must be copied into each new regulation, which a
    clone-regulation action solves, and which colleges want as a button anyway.
    """

    TYPE_CORE = "core"
    TYPE_CHOICES = [
        ("core", "Core"),
        ("elective_prof", "Professional Elective"),
        ("elective_open", "Open Elective"),
        ("lab", "Laboratory"),
        ("project", "Project"),
        ("internship", "Internship"),
        ("mandatory_nc", "Mandatory Non-Credit"),
        ("value_added", "Value Added"),
        ("skill", "Skill Enhancement"),
        ("mooc", "MOOC / SWAYAM"),
    ]

    # unique=True removed — see the two constraints in Meta. A single global
    # unique breaks the moment two regulations both define CS301.
    course_code = models.CharField(max_length=20)
    course_name = models.CharField(max_length=255)
    # PROTECT, previously CASCADE: deleting a Department silently deleted its
    # Courses. Once courses carry credits and are referenced by grade awards, a
    # partial cascade becomes a data-loss event.
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name='courses'
    )

    # ── academic spine ──
    regulation = models.ForeignKey(
        "campusflow_app.Regulation", on_delete=models.PROTECT,
        null=True, blank=True, related_name="courses",
        help_text="Null for legacy rows created before the curriculum spine existed.",
    )
    semester_number = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Curriculum position 1..N. NOT a calendar term — see Term.",
    )
    course_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default=TYPE_CORE)
    credits = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    lecture_hours = models.PositiveSmallIntegerField(default=0)
    tutorial_hours = models.PositiveSmallIntegerField(default=0)
    practical_hours = models.PositiveSmallIntegerField(default=0)
    is_credit_bearing = models.BooleanField(
        default=True,
        help_text="False for audit and mandatory non-credit courses, which are excluded from SGPA.",
    )
    counts_toward_cgpa = models.BooleanField(
        default=True,
        help_text="Separate from is_credit_bearing on purpose: some regulations count a "
                  "course for SGPA but not CGPA, and 0-credit mandatory courses still "
                  "appear on the transcript as pass/fail.",
    )
    canonical_code = models.CharField(
        max_length=20, blank=True, db_index=True,
        help_text="Regulation-independent identity — CS301 for both 21CS301 and "
                  "22CS301 — so trend reporting can follow a course across schemes.",
    )
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Course"
        verbose_name_plural = "Courses"
        constraints = [
            models.UniqueConstraint(
                fields=["regulation", "course_code"],
                name="uniq_course_code_per_regulation",
            ),
            # Preserves today's exact behaviour for every pre-spine row: legacy
            # courses keep global uniqueness, new ones are unique per regulation.
            models.UniqueConstraint(
                fields=["course_code"], condition=Q(regulation__isnull=True),
                name="uniq_legacy_course_code",
            ),
        ]
        indexes = [models.Index(fields=["regulation", "semester_number"])]

    def __str__(self):
        return f"{self.course_code} - {self.course_name}"

    @property
    def total_contact_hours(self):
        return self.lecture_hours + self.tutorial_hours + self.practical_hours

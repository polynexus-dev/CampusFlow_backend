"""
Grading Schemes & Credit-Weighted Results
==========================================
Configurable, per-regulation grade bands — replacing the percentage thresholds
hardcoded in `StudentExamResult.compute_grade()` (models/result.py) and its
seven-letter GRADE_CHOICES, which has no O and no AB and so cannot express most
Indian regulations — plus the course-level, credit-weighted results those bands
produce: CourseGradeAward, TermGradeSheet, StudentAcademicSummary.

Two scheme models rather than one because the *scale* (10-point, 4-point,
absolute vs relative) and the *bands* within it vary independently, and a
Regulation needs to point at a scale that outlives any single band edit.

`StudentExamResult` is deliberately left alone. It records one assessment
component (one exam), not a final course grade — CourseGradeAward is the
course grade, computed from all of a student's exam results for a course
within a term, and the two coexist: results feed awards. Changing
GRADE_CHOICES on StudentExamResult today would invalidate existing rows for no
benefit, since it is not what SGPA/CGPA are computed from.

CourseGradeAward stores every value needed to reprint a transcript — credits,
grade_points, credit_points, grading_scheme — frozen at compute time, rather
than deriving them live from Course.credits and GradeBand on every read. This
is deliberate: `StudentExamResult.save()` already shows what happens without
it — it unconditionally recomputes grade/is_pass on every save, so editing an
unrelated field silently re-grades a published result against whatever the
current thresholds happen to be. A frozen award cannot be moved by an
unrelated later edit to a Course's credits or a GradeBand's cutoffs; only an
explicit, audited recompute (services/grading.py) can change a published one.
"""

from django.db import models
from django.db.models import F, Q


class GradingScheme(models.Model):
    """A grading scale, e.g. "VTU 10-point (2021)"."""

    name = models.CharField(max_length=100, unique=True)
    max_points = models.DecimalField(
        max_digits=4, decimal_places=2, default=10,
        help_text="Highest grade point on this scale — 10 for a 10-point scale.",
    )
    passing_grade_points = models.DecimalField(
        max_digits=4, decimal_places=2, default=4,
        help_text="Minimum grade points that count as a pass.",
    )
    rounding_decimals = models.PositiveSmallIntegerField(
        default=2, help_text="Decimal places for computed SGPA/CGPA.",
    )
    is_absolute = models.BooleanField(
        default=True,
        help_text="True for fixed percentage bands. False for relative/curve grading.",
    )
    is_default = models.BooleanField(
        default=False,
        help_text="The scheme used when a Regulation names none. At most one may be default.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Grading Scheme"
        verbose_name_plural = "Grading Schemes"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["is_default"], condition=Q(is_default=True),
                name="uniq_default_grading_scheme",
            ),
        ]

    def __str__(self):
        return self.name

    def band_for_percentage(self, percentage):
        """
        The band a percentage falls into, or None. Read from the prefetched
        `bands` when available so callers looping over many results do not
        issue a query each time.
        """
        if percentage is None:
            return None
        for band in self.bands.all():
            if band.min_percentage <= percentage <= band.max_percentage:
                return band
        return None


class GradeBand(models.Model):
    """One letter grade within a scheme, with its percentage range and points."""

    scheme = models.ForeignKey(
        GradingScheme, on_delete=models.CASCADE, related_name="bands",
    )
    letter = models.CharField(
        max_length=5, help_text="O, A+, A, B+, B, C, P, F, AB, I, W.",
    )
    min_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    max_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    grade_points = models.DecimalField(max_digits=4, decimal_places=2)
    is_pass = models.BooleanField(default=True)
    counts_in_gpa = models.BooleanField(
        default=True,
        help_text="False for W (withdrawn) and I (incomplete), which sit outside the average.",
    )
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Grade Band"
        verbose_name_plural = "Grade Bands"
        ordering = ["-min_percentage"]
        constraints = [
            models.UniqueConstraint(
                fields=["scheme", "letter"], name="uniq_grade_letter_per_scheme",
            ),
            models.CheckConstraint(
                condition=Q(max_percentage__gte=F("min_percentage")),
                name="grade_band_range_valid",
            ),
        ]

    def __str__(self):
        return f"{self.scheme.name}: {self.letter} ({self.min_percentage}-{self.max_percentage}%)"


class CourseGradeAward(models.Model):
    """
    The final course grade for one registration — the credit-weighted result
    SGPA/CGPA are computed from. One per StudentCourseRegistration.
    """

    SOURCE_COMPUTED = "computed"
    SOURCE_CHOICES = [
        (SOURCE_COMPUTED, "Computed from exam results"),
        ("manual", "Manually entered"),
        ("imported", "Imported from a previous system"),
    ]

    registration = models.OneToOneField(
        "campusflow_app.StudentCourseRegistration", on_delete=models.CASCADE,
        related_name="grade_award",
    )
    # Denormalised from registration.student / registration.term — every
    # transcript and gradesheet query filters on these directly.
    student = models.ForeignKey(
        "campusflow_app.StudentProfile", on_delete=models.CASCADE,
        related_name="course_grade_awards",
    )
    term = models.ForeignKey(
        "campusflow_app.Term", on_delete=models.PROTECT,
        related_name="course_grade_awards",
    )

    credits = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text="Frozen copy of the course's credits at compute time.",
    )
    internal_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    external_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    total_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    max_marks = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    percentage = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text="STORED, unlike StudentExamResult.percentage which is a @property "
                  "and therefore cannot be queried or aggregated in SQL.",
    )
    grade_letter = models.CharField(max_length=5)
    grade_points = models.DecimalField(max_digits=4, decimal_places=2)
    credit_points = models.DecimalField(
        max_digits=7, decimal_places=2,
        help_text="credits x grade_points, stored so SGPA is a plain SUM/SUM in SQL.",
    )
    is_pass = models.BooleanField(default=False)
    counts_in_gpa = models.BooleanField(
        default=True,
        help_text="False when the course is not credit-bearing or the grade band "
                  "(e.g. W, I) sits outside the average.",
    )
    grading_scheme = models.ForeignKey(
        "campusflow_app.GradingScheme", on_delete=models.PROTECT,
        related_name="awards",
        help_text="FROZEN — which scheme produced grade_letter, regardless of what "
                  "the Regulation points at later.",
    )
    attempt_number = models.PositiveSmallIntegerField(default=1)
    source = models.CharField(max_length=10, choices=SOURCE_CHOICES, default=SOURCE_COMPUTED)
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Course Grade Award"
        verbose_name_plural = "Course Grade Awards"
        indexes = [
            models.Index(fields=["student", "term"]),
            models.Index(fields=["term", "is_published"]),
        ]

    def __str__(self):
        return f"{self.student.student_id} - {self.registration.offering.course.course_code}: {self.grade_letter}"


class TermGradeSheet(models.Model):
    """One student's aggregate result for one term — the SGPA record."""

    student = models.ForeignKey(
        "campusflow_app.StudentProfile", on_delete=models.CASCADE,
        related_name="term_grade_sheets",
    )
    term = models.ForeignKey(
        "campusflow_app.Term", on_delete=models.PROTECT, related_name="grade_sheets",
    )
    semester_number = models.PositiveSmallIntegerField(
        help_text="The student's curriculum position for this term, frozen at compute time.",
    )
    credits_registered = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    credits_earned = models.DecimalField(max_digits=6, decimal_places=1, default=0)
    credit_points_earned = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    sgpa = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    backlog_count = models.PositiveSmallIntegerField(default=0)
    result_status = models.CharField(
        max_length=15, default="incomplete",
        choices=[
            ("pass", "Pass"), ("fail", "Fail"),
            ("withheld", "Withheld"), ("incomplete", "Incomplete"),
        ],
    )
    is_published = models.BooleanField(default=False)
    published_at = models.DateTimeField(null=True, blank=True)
    computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Term Grade Sheet"
        verbose_name_plural = "Term Grade Sheets"
        constraints = [
            models.UniqueConstraint(
                fields=["student", "term"], name="uniq_gradesheet_student_term",
            ),
        ]
        indexes = [models.Index(fields=["term", "result_status"])]

    def __str__(self):
        return f"{self.student.student_id} - {self.term}: SGPA {self.sgpa}"


class StudentAcademicSummary(models.Model):
    """
    One row per student — the CGPA record every dashboard, promotion screen and
    NAAC/NBA report reads. Also the natural home for the APAAR/ABC identifiers
    a later phase will add.
    """

    student = models.OneToOneField(
        "campusflow_app.StudentProfile", on_delete=models.CASCADE,
        related_name="academic_summary",
    )
    credits_earned = models.DecimalField(max_digits=7, decimal_places=1, default=0)
    credits_required = models.DecimalField(max_digits=7, decimal_places=1, null=True, blank=True)
    credit_points_earned = models.DecimalField(max_digits=9, decimal_places=2, default=0)
    cgpa = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    active_backlog_count = models.PositiveSmallIntegerField(default=0)
    highest_semester_cleared = models.PositiveSmallIntegerField(default=0)
    last_computed_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Student Academic Summary"
        verbose_name_plural = "Student Academic Summaries"

    def __str__(self):
        return f"{self.student.student_id}: CGPA {self.cgpa}"

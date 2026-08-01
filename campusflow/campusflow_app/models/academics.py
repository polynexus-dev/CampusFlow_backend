"""
Academic Calendar
=================
The calendar half of the academic spine: `AcademicYear` and `Term`.

Before this, "which semester are we in" had no answer anywhere in the system.
`semester` and `academic_year` were free-text strings duplicated across Exam,
Schedule, StudentProfile, FeeStructure and PromotionBatch, and the frontend
hardcoded "Semester 1" / "2025-2026" — so every exam created was stamped with
whatever the form defaulted to. Seed data already drifted between "Semester 4"
and "4th Semester", meaning any join on those strings was broken.

These two models give a single source of truth. They are deliberately additive:
nothing reads the old strings differently yet, and the nullable `term` FKs on
Exam and Schedule are populated later. See models/course.py for the curriculum
half (Program/Regulation/credits), which lands separately.

Note the distinction that causes the most confusion downstream:
  * `Term` is a *calendar* period — "Odd Semester 2025-2026", a real date range.
  * A curriculum position ("this course is taught in semester 3") is NOT a Term.
    That lives on the course as a plain integer, because semester 3 recurs every
    year while a Term happens once.
"""

from datetime import date

from django.contrib.auth.models import User
from django.db import models
from django.db.models import F, Q

from .department import Department


class AcademicYear(models.Model):
    """
    One academic session, e.g. "2025-2026". Indian HEIs run July-June, which is
    what services/academics.py assumes when deriving a year from today's date.
    """

    name = models.CharField(
        max_length=9, unique=True,
        help_text='Canonical form "2025-2026". Used as the display label everywhere.',
    )
    start_date = models.DateField(help_text="Typically 1 July.")
    end_date = models.DateField(help_text="Typically 30 June of the following year.")
    is_current = models.BooleanField(
        default=False,
        help_text="Exactly one AcademicYear may be current; enforced by a partial unique constraint.",
    )
    is_closed = models.BooleanField(
        default=False,
        help_text="Set once results are finalised. Closed years reject new terms and exams.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Academic Year"
        verbose_name_plural = "Academic Years"
        ordering = ["-start_date"]
        constraints = [
            # Partial unique: many rows may be False, only one may be True.
            models.UniqueConstraint(
                fields=["is_current"], condition=Q(is_current=True),
                name="uniq_current_academic_year",
            ),
            models.CheckConstraint(
                condition=Q(end_date__gt=F("start_date")),
                name="academic_year_end_after_start",
            ),
        ]

    def __str__(self):
        return self.name

    @property
    def contains_today(self):
        return self.start_date <= date.today() <= self.end_date


class Term(models.Model):
    """
    A teaching period inside an AcademicYear — the thing Exam, Schedule and
    (later) CourseOffering point at instead of a free-text string.
    """

    KIND_ODD = "odd"
    KIND_EVEN = "even"
    KIND_CHOICES = [
        (KIND_ODD, "Odd Semester"),
        (KIND_EVEN, "Even Semester"),
        ("summer", "Summer Term"),
        ("annual", "Annual"),
        ("trimester", "Trimester"),
    ]

    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.CASCADE, related_name="terms",
    )
    name = models.CharField(
        max_length=50,
        help_text='Display name, e.g. "Odd Semester" or "Semester 1".',
    )
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=KIND_ODD)
    sequence = models.PositiveSmallIntegerField(
        default=1,
        help_text="Order within the academic year: 1 for odd/first, 2 for even/second.",
    )
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(
        default=False,
        help_text="Exactly one Term may be current across all years.",
    )
    result_entry_open = models.BooleanField(
        default=True,
        help_text="When False, marks entry for exams in this term is closed.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Term"
        verbose_name_plural = "Terms"
        ordering = ["-academic_year__start_date", "sequence"]
        constraints = [
            models.UniqueConstraint(
                fields=["academic_year", "sequence"], name="uniq_term_sequence_per_year",
            ),
            models.UniqueConstraint(
                fields=["academic_year", "name"], name="uniq_term_name_per_year",
            ),
            # Global, not per-year: "the current term" is a single system-wide fact.
            models.UniqueConstraint(
                fields=["is_current"], condition=Q(is_current=True),
                name="uniq_current_term",
            ),
            models.CheckConstraint(
                condition=Q(end_date__gt=F("start_date")),
                name="term_end_after_start",
            ),
        ]
        indexes = [models.Index(fields=["start_date", "end_date"])]

    def __str__(self):
        return f"{self.name} ({self.academic_year.name})"

    @property
    def contains_today(self):
        return self.start_date <= date.today() <= self.end_date


# ---------------------------------------------------------------------
# Curriculum structure
# ---------------------------------------------------------------------
# Department currently doubles as the branch — StudentProfile.department is the
# only real academic FK a student has, and `program_enrolled_in` is free text.
# Program takes over the branch role so Department can go back to being an
# organisational unit.


class Program(models.Model):
    """A degree/branch, e.g. "B.Tech Computer Science & Engineering"."""

    LEVEL_CHOICES = [
        ("ug", "Undergraduate"),
        ("pg", "Postgraduate"),
        ("diploma", "Diploma"),
        ("phd", "Doctoral"),
        ("certificate", "Certificate"),
    ]

    name = models.CharField(max_length=200)
    code = models.CharField(max_length=20, help_text="Short code, e.g. BTCSE.")
    short_name = models.CharField(
        max_length=50, blank=True,
        help_text="Display form, e.g. B.Tech CS. Capped at 50 to fit the legacy "
                  "StudentProfile.program_enrolled_in column it mirrors during cutover.",
    )
    level = models.CharField(max_length=15, choices=LEVEL_CHOICES, default="ug")
    department = models.ForeignKey(
        Department, on_delete=models.PROTECT, related_name="programs",
    )
    duration_years = models.DecimalField(max_digits=3, decimal_places=1, default=4)
    total_terms = models.PositiveSmallIntegerField(
        default=8, help_text="Number of curriculum semesters, e.g. 8 for a 4-year degree.",
    )
    total_credits_required = models.DecimalField(
        max_digits=6, decimal_places=1, null=True, blank=True,
    )
    # NEP hooks. Nullable and unread for now — costs nothing here and saves a
    # migration on these tables when the APAAR/ABC work lands.
    nep_multiple_entry_exit = models.BooleanField(default=False)
    aicte_program_code = models.CharField(max_length=30, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Program"
        verbose_name_plural = "Programs"
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["code"], name="uniq_program_code"),
        ]
        indexes = [models.Index(fields=["department", "is_active"])]

    def __str__(self):
        return f"{self.code} - {self.name}"


class Regulation(models.Model):
    """
    A versioned curriculum scheme, e.g. R2023. Owns the grading scheme and the
    graduation rules, which is what makes grading configurable per programme
    rather than hardcoded.
    """

    STATUS_CHOICES = [
        ("draft", "Draft"),
        ("active", "Active"),
        ("archived", "Archived"),
    ]

    program = models.ForeignKey(
        Program, on_delete=models.CASCADE, related_name="regulations",
    )
    code = models.CharField(max_length=30, help_text="e.g. R2023 or 2021 Scheme.")
    name = models.CharField(max_length=200, blank=True)
    effective_from_year = models.PositiveSmallIntegerField(
        help_text="First admission year this scheme applies to.",
    )
    effective_to_year = models.PositiveSmallIntegerField(null=True, blank=True)
    grading_scheme = models.ForeignKey(
        "campusflow_app.GradingScheme", on_delete=models.PROTECT,
        null=True, blank=True, related_name="regulations",
        help_text="Falls back to the default scheme when unset.",
    )
    min_credits_to_graduate = models.DecimalField(
        max_digits=6, decimal_places=1, null=True, blank=True,
    )
    max_backlogs_to_promote = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Drives the suggested promotion decision once promotion reads marks.",
    )
    is_locked = models.BooleanField(
        default=False,
        help_text="Once locked, credits and L-T-P on its courses cannot change. "
                  "Protects transcripts already issued under this scheme.",
    )
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default="draft")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Regulation"
        verbose_name_plural = "Regulations"
        ordering = ["-effective_from_year", "code"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "code"], name="uniq_regulation_per_program",
            ),
        ]
        indexes = [models.Index(fields=["program", "status"])]

    def __str__(self):
        return f"{self.program.code} {self.code}"

    @property
    def effective_grading_scheme(self):
        """The scheme to grade against — this regulation's, or the tenant default."""
        if self.grading_scheme_id:
            return self.grading_scheme
        from .grading import GradingScheme
        return GradingScheme.objects.filter(is_default=True).first()


class Batch(models.Model):
    """
    An admitted cohort, e.g. 2025-2029. The single place a regulation is decided:
    students inherit it from their batch rather than choosing one, so a cohort
    cannot end up split across schemes by accident.
    """

    program = models.ForeignKey(
        Program, on_delete=models.PROTECT, related_name="batches",
    )
    regulation = models.ForeignKey(
        Regulation, on_delete=models.PROTECT, related_name="batches",
    )
    admission_year = models.PositiveSmallIntegerField()
    name = models.CharField(max_length=50, help_text="e.g. 2025-2029.")
    expected_graduation_year = models.PositiveSmallIntegerField(null=True, blank=True)
    current_semester_number = models.PositiveSmallIntegerField(
        default=1,
        help_text="Curriculum position of the bulk of this batch; advanced by a promotion run.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Batch"
        verbose_name_plural = "Batches"
        ordering = ["-admission_year", "program__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "admission_year"], name="uniq_batch_per_program_year",
            ),
        ]
        indexes = [models.Index(fields=["program", "is_active"])]

    def __str__(self):
        return f"{self.program.code} {self.name}"


class Section(models.Model):
    """
    A division within a batch, scoped per semester rather than per batch. That is
    deliberate: colleges re-cut sections when electives begin, so "A/B in
    semesters 1-4, A/B/C in 5-8" must be expressible. A batch-only section
    cannot represent it, and the workaround is free text again.
    """

    batch = models.ForeignKey(
        Batch, on_delete=models.CASCADE, related_name="sections",
    )
    name = models.CharField(
        max_length=10,
        help_text="e.g. A. Capped at 10 to mirror the legacy section_division.",
    )
    semester_number = models.PositiveSmallIntegerField(
        help_text="Curriculum semester this section applies to.",
    )
    capacity = models.PositiveSmallIntegerField(null=True, blank=True)
    # User rather than TeachingStaffProfile: the codebase is split, but
    # Schedule.faculty and Exam.invigilator both use User, and it avoids a
    # second lookup during permission checks.
    mentor = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="mentored_sections",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Section"
        verbose_name_plural = "Sections"
        ordering = ["semester_number", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch", "semester_number", "name"],
                name="uniq_section_per_batch_sem",
            ),
        ]

    def __str__(self):
        return f"{self.batch} Sem {self.semester_number} - {self.name}"

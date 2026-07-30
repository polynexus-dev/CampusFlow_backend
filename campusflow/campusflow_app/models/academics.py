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

from django.db import models
from django.db.models import F, Q


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

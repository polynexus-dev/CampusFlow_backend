"""
Grading Schemes
===============
Configurable, per-regulation grade bands — replacing the percentage thresholds
hardcoded in `StudentExamResult.compute_grade()` (models/result.py) and its
seven-letter GRADE_CHOICES, which has no O and no AB and so cannot express most
Indian regulations.

Two models rather than one because the *scale* (10-point, 4-point, absolute vs
relative) and the *bands* within it vary independently, and a Regulation needs
to point at a scale that outlives any single band edit.

`StudentExamResult` is deliberately left alone for now. It records one
assessment component, not a final course grade; the credit-weighted course
grade lands in a later PR and will consume these bands. Changing
GRADE_CHOICES today would invalidate existing rows.
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

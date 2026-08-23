"""
NIRF (National Institutional Ranking Framework) data compilation — the
figures NIRF's own Data Capture System asks for that have nowhere else to
live in this schema. Everything else NIRF needs (student strength, gender/
category/disability splits, region diversity via StudentProfile.permanent_state,
faculty counts, placement activity, government-scholarship reconciliation via
StudentScholarshipRecord) is already computed from existing models — see
services/nirf_compilation.py.

Deliberately does NOT store or compute an estimated NIRF score/rank: the
actual weightages and normalization formula are government-set and revised
most years, so any score this system produced would risk being a stale or
wrong number presented as official. This model only holds raw figures the
IQAC/management enters themselves.
"""
from django.contrib.auth.models import User
from django.db import models

from .finance import FinancialYear


class NIRFDataEntry(models.Model):
    """One year's manually-entered NIRF figures for one ranking category.
    `nirf_category` is free text (e.g. "Engineering", "Overall") rather than
    a hardcoded choice list — NIRF's category list is long and occasionally
    revised, and an incomplete/wrong enum would be worse than free text."""

    financial_year = models.ForeignKey(FinancialYear, on_delete=models.CASCADE, related_name="nirf_entries")
    nirf_category = models.CharField(max_length=100, help_text='e.g. "Engineering", "Management", "Overall".')

    # RP — Research and Professional Practice
    sponsored_research_funding_lakhs = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    consultancy_income_lakhs = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    patents_filed = models.PositiveIntegerField(default=0)
    patents_granted = models.PositiveIntegerField(default=0)
    publications_count = models.PositiveIntegerField(default=0)

    # TLR — Teaching-Learning and Resources
    library_expenditure_lakhs = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # GO — Graduation Outcomes (the part placement/exam records don't cover)
    students_admitted_higher_studies = models.PositiveIntegerField(default=0)
    students_qualified_govt_exams = models.PositiveIntegerField(
        default=0, help_text="e.g. GATE/UPSC/state PSC qualifiers among the graduating batch.",
    )

    notes = models.TextField(blank=True)

    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "NIRF Data Entry"
        verbose_name_plural = "NIRF Data Entries"
        ordering = ["-financial_year__start_date", "nirf_category"]
        constraints = [
            models.UniqueConstraint(fields=["financial_year", "nirf_category"], name="uniq_nirf_entry_year_category"),
        ]

    def __str__(self):
        return f"NIRF {self.nirf_category} — {self.financial_year.label}"

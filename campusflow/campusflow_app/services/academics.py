"""
Academic calendar resolution
============================
Answers "which term are we in" — a question the system previously could not
answer at all.

Provisioning is lazy on first read, matching the idiom already used for module
permissions (views/module_permissions.py get_or_create on GET). That avoids the
usual dual-write problem for new per-tenant seed data: without it, every new
model needs both a backfill for existing tenants and an addition to
TenantCreateSerializer.create() for future ones. Here, the first caller in any
tenant schema creates what it needs and every later caller finds it.
"""

from datetime import date

from django.db import transaction

from ..models.academics import AcademicYear, Term

# Indian HEIs run July-June. An academic year starting in July 2025 is "2025-2026".
ACADEMIC_YEAR_START_MONTH = 7


def derive_academic_year(on_date=None):
    """
    Return (name, start_date, end_date) for the academic year containing `on_date`.

    July onwards belongs to the year that starts in this calendar year; January
    to June belongs to the year that started last July.
    """
    on_date = on_date or date.today()
    start_year = on_date.year if on_date.month >= ACADEMIC_YEAR_START_MONTH else on_date.year - 1
    return (
        f"{start_year}-{start_year + 1}",
        date(start_year, ACADEMIC_YEAR_START_MONTH, 1),
        date(start_year + 1, ACADEMIC_YEAR_START_MONTH - 1, 30),
    )


def _term_bounds(academic_year, sequence):
    """
    Odd term = July-December of the starting year.
    Even term = January-June of the following year.
    """
    start_year = academic_year.start_date.year
    if sequence == 1:
        return (
            Term.KIND_ODD, "Odd Semester",
            date(start_year, 7, 1), date(start_year, 12, 31),
        )
    return (
        Term.KIND_EVEN, "Even Semester",
        date(start_year + 1, 1, 1), date(start_year + 1, 6, 30),
    )


@transaction.atomic
def get_or_create_academic_year(on_date=None):
    """Fetch (or lazily create) the AcademicYear covering `on_date`."""
    name, start, end = derive_academic_year(on_date)
    year, _ = AcademicYear.objects.get_or_create(
        name=name, defaults={"start_date": start, "end_date": end},
    )
    return year


@transaction.atomic
def get_or_create_terms(academic_year):
    """Ensure both the odd and even Term rows exist for a year. Returns them ordered."""
    for sequence in (1, 2):
        kind, name, start, end = _term_bounds(academic_year, sequence)
        Term.objects.get_or_create(
            academic_year=academic_year, sequence=sequence,
            defaults={"kind": kind, "name": name, "start_date": start, "end_date": end},
        )
    return list(academic_year.terms.order_by("sequence"))


@transaction.atomic
def set_current_term(term):
    """
    Make `term` the single current Term, and its year the single current
    AcademicYear.

    The partial unique constraints allow only one True row each, and they are not
    deferrable, so the old flag must be cleared before the new one is set —
    hence two statements per model rather than one. `.update()` is used
    deliberately: it bypasses the pre_save/post_save audit signals, which would
    otherwise fire an extra SELECT and INSERT per row for a bookkeeping flag.
    """
    Term.objects.filter(is_current=True).exclude(pk=term.pk).update(is_current=False)
    Term.objects.filter(pk=term.pk).update(is_current=True)

    AcademicYear.objects.filter(is_current=True).exclude(
        pk=term.academic_year_id
    ).update(is_current=False)
    AcademicYear.objects.filter(pk=term.academic_year_id).update(is_current=True)

    term.refresh_from_db()
    return term


def get_current_term(on_date=None):
    """
    The current Term, resolved in three steps:

      1. An explicitly flagged current Term wins — an administrator's choice is
         never silently overridden, even if its dates have passed.
      2. Otherwise the Term whose date range contains today.
      3. Otherwise lazily provision the year and terms for today and flag the
         date-matching one.

    Returns a Term. Only ever returns None if step 3 somehow finds no matching
    range, which cannot happen for a July-June year covering all 12 months.
    """
    explicit = Term.objects.filter(is_current=True).select_related("academic_year").first()
    if explicit:
        return explicit

    on_date = on_date or date.today()
    dated = (
        Term.objects.filter(start_date__lte=on_date, end_date__gte=on_date)
        .select_related("academic_year")
        .first()
    )
    if dated:
        return set_current_term(dated)

    year = get_or_create_academic_year(on_date)
    terms = get_or_create_terms(year)
    for term in terms:
        if term.start_date <= on_date <= term.end_date:
            return set_current_term(term)

    return set_current_term(terms[0]) if terms else None


def get_current_academic_year(on_date=None):
    """The current AcademicYear, derived from the current Term."""
    term = get_current_term(on_date)
    return term.academic_year if term else None


# ---------------------------------------------------------------------
# Grading schemes
# ---------------------------------------------------------------------

# A 10-point absolute scale, the most common shape across Indian universities
# (AICTE/UGC guidance, VTU/JNTU/Anna variants). Bands end at .99 rather than at
# whole numbers so no percentage falls between two bands: 89.5 must grade as A+,
# not as nothing.
DEFAULT_SCHEME_NAME = "Standard 10-Point Scale"
DEFAULT_GRADE_BANDS = [
    # letter, min%, max%, points, is_pass
    ("O",  90, 100.00, 10, True),
    ("A+", 80, 89.99, 9, True),
    ("A",  70, 79.99, 8, True),
    ("B+", 60, 69.99, 7, True),
    ("B",  55, 59.99, 6, True),
    ("C",  50, 54.99, 5, True),
    ("P",  40, 49.99, 4, True),
    ("F",  0, 39.99, 0, False),
]


@transaction.atomic
def get_default_grading_scheme():
    """
    Fetch (or lazily create) the tenant's default grading scheme with its bands.

    Same lazy-provisioning rationale as the calendar: no backfill command and no
    change to tenant provisioning is needed, because the first caller in a schema
    creates what it needs.

    Note this does NOT create the absent/incomplete letters (AB, I, W). Those
    carry regulation-specific rules about whether they count in the average, so
    an administrator should add them deliberately rather than inherit a guess.
    """
    from ..models.grading import GradeBand, GradingScheme

    scheme = GradingScheme.objects.filter(is_default=True).first()
    if scheme is None:
        scheme, _ = GradingScheme.objects.get_or_create(
            name=DEFAULT_SCHEME_NAME,
            defaults={
                "max_points": 10,
                "passing_grade_points": 4,
                "is_absolute": True,
                "is_default": True,
            },
        )

    if not scheme.bands.exists():
        GradeBand.objects.bulk_create([
            GradeBand(
                scheme=scheme, letter=letter,
                min_percentage=low, max_percentage=high,
                grade_points=points, is_pass=is_pass,
                counts_in_gpa=True, order=index,
            )
            for index, (letter, low, high, points, is_pass) in enumerate(DEFAULT_GRADE_BANDS)
        ])

    return scheme

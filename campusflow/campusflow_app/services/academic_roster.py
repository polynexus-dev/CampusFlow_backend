"""
Single source of truth for "which students are in this class/scope" — the
question BulkGenerateInvoicesView (views/fees.py), the promotion roster query
(views/promotion.py), the exam visibility filter (views/exam.py) and the
assignment notification fan-out (models/assignment.py) each answer today by
matching StudentProfile.department alone or by exact string equality on the
legacy academic fields.

During the parallel run, neither the structured FKs nor the legacy free-text
fields on StudentProfile can be trusted alone: some students have been
backfilled and carry only the FK for a dimension, some have not been touched
and carry only the string, most carry both. For every dimension supplied, a
student is included if EITHER form matches. Matching on only one form is
precisely what turns a partially-backfilled tenant into a partial, silent
under-bill — 500 of 600 students resolve, invoices generate, success is
reported, and the other 100 are never billed until a parent calls.
"""

from django.db.models import Q

from ..models.profile import StudentProfile

# (fk_field, fk_value, string_field, string_value) tuples, built from whichever
# criteria the caller supplies. Department is handled separately: it is the one
# dimension every StudentProfile has always carried as a real FK, so there is
# no parallel-run ambiguity to resolve for it.
_DIMENSIONS = (
    ("program_id", "program_enrolled_in"),
    ("batch_id", "batch_academic_year"),
    ("current_semester_number", "current_semester_year"),
)


def resolve_student_roster(*, department_id=None,
                            program_id=None, legacy_program=None,
                            batch_id=None, legacy_batch=None,
                            semester_number=None, legacy_semester=None,
                            section_id=None):
    """
    Returns (queryset, diagnostics).

    diagnostics = {"matched": N, "resolved_by_fk": N, "unresolved_by_fk": N}

    `matched` is the roster this function actually returns — it never misses a
    student that today's exact-string matching would have found, because every
    dimension is OR'd between its structured and legacy form.

    `unresolved_by_fk` is the number of matched students a future FK-only query
    would silently drop: either because a dimension was only ever given a
    legacy value (the caller — typically FeeStructure — has not been migrated
    for that field), or because a matched student's own FK for that dimension
    is unset or does not agree with the criterion. This is the number to check
    before ever cutting a call site over to FK-only matching, and the number to
    surface to an admin as "N of these students still need backfilling."

    department_id is a hard AND filter; every other dimension is OR'd between
    its structured and legacy form, then the dimensions are AND'd together.
    section_id is a hard AND filter on the FK only — sections did not exist
    before this schema, so there is no legacy string to fall back to.
    """
    qs = StudentProfile.objects.all()

    if department_id:
        qs = qs.filter(department_id=department_id)

    fk_only_q = Q()
    fk_fully_specified = True

    for fk_field, string_field in _DIMENSIONS:
        fk_value = {"program_id": program_id, "batch_id": batch_id,
                    "current_semester_number": semester_number}[fk_field]
        string_value = {"program_enrolled_in": legacy_program,
                         "batch_academic_year": legacy_batch,
                         "current_semester_year": legacy_semester}[string_field]

        if fk_value is None and not string_value:
            continue  # this dimension is not part of the scope at all

        dim_q = Q()
        if fk_value is not None:
            dim_q |= Q(**{fk_field: fk_value})
            fk_only_q &= Q(**{fk_field: fk_value})
        else:
            fk_fully_specified = False
        if string_value:
            dim_q |= Q(**{string_field: string_value})
        qs = qs.filter(dim_q)

    if section_id:
        qs = qs.filter(section_id=section_id)
        fk_only_q &= Q(section_id=section_id)

    matched = qs.count()
    resolved_by_fk = qs.filter(fk_only_q).count() if (fk_fully_specified and matched) else 0

    diagnostics = {
        "matched": matched,
        "resolved_by_fk": resolved_by_fk,
        "unresolved_by_fk": matched - resolved_by_fk,
    }
    return qs, diagnostics


def resolve_roster_for_fee_structure(fee_structure):
    """
    Convenience wrapper: extracts both the FK and legacy criteria straight off
    a FeeStructure row, so callers never have to remember which of the two
    forms to read off which field.
    """
    return resolve_student_roster(
        department_id=fee_structure.department_id,
        program_id=fee_structure.program_id,
        legacy_program=fee_structure.program_enrolled_in,
        batch_id=fee_structure.batch_id,
        legacy_batch=fee_structure.batch_academic_year,
        semester_number=fee_structure.semester_number,
        legacy_semester=fee_structure.current_semester_year,
    )

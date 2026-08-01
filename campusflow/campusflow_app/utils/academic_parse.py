"""
Pure parsing helpers for the legacy free-text academic fields on StudentProfile
(program_enrolled_in, batch_academic_year, current_semester_year,
section_division).

These exist because the four fields already hold inconsistent formats across
seed data and, presumably, real tenants — "Semester 4" vs "4th Semester" vs
"SEM-IV" for the same thing, and "2024-2025" (an academic year) vs "2025-2029"
(a batch span) in the SAME column. Nothing here writes to the database or
touches a queryset; every function takes a string and returns a parsed value or
None. None means "could not parse" — never a guess. A guessed Program or
Batch is worse than a blank one, because it looks authoritative and is not.
"""

import re

_ROMAN_OR_WORD_SEMESTER = {
    "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8,
    "ix": 9, "x": 10, "xi": 11, "xii": 12,
    "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6,
    "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10,
}

_YEAR_RANGE_RE = re.compile(r"(\d{4})\s*[-/–]\s*(\d{2,4})")


def parse_semester_number(raw):
    """
    'Semester 4' | '4th Semester' | 'SEM-IV' | 'IV' | 'Fourth Sem' | '4' -> 4.
    Anything else, including a semester outside 1..12, -> None.
    """
    if not raw:
        return None
    text = str(raw).strip().lower()
    if not text:
        return None

    # First integer 1..12 anywhere in the string.
    for match in re.finditer(r"\d+", text):
        value = int(match.group())
        if 1 <= value <= 12:
            return value

    # Roman numeral or English ordinal token, isolated by non-word boundaries.
    for token in re.split(r"[^a-z]+", text):
        if token in _ROMAN_OR_WORD_SEMESTER:
            return _ROMAN_OR_WORD_SEMESTER[token]

    return None


def parse_academic_year_or_batch_span(raw):
    """
    Both an academic year ("2024-2025") and a batch admission span
    ("2025-2029") live in the same `batch_academic_year` column today, and they
    must be told apart before either can be migrated correctly.

    Returns a dict: {"kind": "academic_year", "name": "2024-2025",
                      "start_year": 2024, "end_year": 2025}
                 or {"kind": "batch_span", "start_year": 2025, "end_year": 2029}
                 or None if unparseable.

    An academic year always spans exactly one year (end = start + 1); anything
    wider is treated as a batch's admission-to-graduation span, never as an
    academic year with a typo — silently "fixing" a wrong year is exactly the
    kind of invented data this module refuses to produce.
    """
    if not raw:
        return None
    text = str(raw).strip()
    if not text:
        return None

    match = _YEAR_RANGE_RE.search(text)
    if not match:
        return None

    start_year = int(match.group(1))
    end_raw = match.group(2)
    # "2024-25" -> end year 2025, using the start year's century.
    end_year = int(end_raw) if len(end_raw) == 4 else (start_year // 100) * 100 + int(end_raw)
    if end_year <= start_year:
        return None

    if end_year - start_year == 1:
        return {
            "kind": "academic_year",
            "name": f"{start_year}-{end_year}",
            "start_year": start_year,
            "end_year": end_year,
        }
    return {"kind": "batch_span", "start_year": start_year, "end_year": end_year}


def normalize_section_name(raw):
    """'-', '', 'N/A', 'n/a', None -> None. Otherwise stripped, upper-cased,
    capped at 10 chars to match Section.name's max_length."""
    if not raw:
        return None
    text = str(raw).strip()
    if not text or text.upper() in ("-", "N/A", "NA", "NONE"):
        return None
    return text.upper()[:10]


def normalize_program_text(raw):
    """Case/whitespace/punctuation-insensitive form used to fuzzy-match
    program_enrolled_in against Program.name/short_name/code."""
    if not raw:
        return ""
    text = str(raw).strip().lower()
    text = text.replace(".", "").replace(",", "")
    return re.sub(r"\s+", " ", text)

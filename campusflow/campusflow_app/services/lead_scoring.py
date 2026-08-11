"""
campusflow_app/services/lead_scoring.py

Rule-based (deliberately NOT machine-learned) admissions lead-priority
scoring — same reasoning as services/risk_scoring.py: no historical
multi-year admission-cycle data exists yet to train a real
conversion-probability model against, so this scores observable signals
(engagement, recency, completeness, source quality) rather than predicting
yield. SIGNAL_WEIGHTS and the tier thresholds are starting heuristics that
should be recalibrated once real conversion outcomes are observed.

Unlike risk_scoring.py, every signal here always has a value (a lead with
zero logged activity is a valid "cold" reading, not "insufficient data"),
so there's no graceful-degradation/re-normalization step — the composite
is a plain fixed weighted sum.

Mirrors services/outcome_attainment.py / risk_scoring.py's module-level
pure-function style: functions take a Lead instance, return plain
values/dicts, no side effects, no request coupling.
"""

from django.utils import timezone

from ..models.admissions import Lead

SIGNAL_WEIGHTS = {
    "engagement": 0.35,
    "recency": 0.25,
    "completeness": 0.20,
    "source": 0.20,
}

TIER_HOT_THRESHOLD = 70
TIER_WARM_THRESHOLD = 40

# Diminishing returns above this many logged activities — a lead doesn't
# need infinite calls logged to be considered maximally engaged.
ENGAGEMENT_SATURATION_COUNT = 5

# A lead with no activity in this many days is treated as going cold
# regardless of how engaged it looked earlier.
RECENCY_STALE_AFTER_DAYS = 14

SOURCE_SCORES = {
    Lead.SOURCE_REFERRAL: 100.0,
    Lead.SOURCE_EVENT: 90.0,
    Lead.SOURCE_AGENT: 80.0,
    Lead.SOURCE_WALK_IN: 70.0,
    Lead.SOURCE_WEBSITE: 50.0,
    Lead.SOURCE_OTHER: 30.0,
}


def _engagement_signal(lead) -> float:
    count = lead.activities.count()
    return min(100.0, (count / ENGAGEMENT_SATURATION_COUNT) * 100)


def _recency_signal(lead) -> float:
    last_activity = lead.activities.order_by("-created_at").values_list("created_at", flat=True).first()
    anchor = last_activity or lead.created_at
    days_since = (timezone.now() - anchor).days

    if days_since <= 3:
        return 100.0
    if days_since <= 7:
        return 70.0
    if days_since <= RECENCY_STALE_AFTER_DAYS:
        return 40.0
    return 10.0


def _completeness_signal(lead) -> float:
    fields_present = sum([
        bool(lead.phone),
        bool(lead.interested_department_id),
        bool(lead.interested_program_id),
    ])
    return (fields_present / 3) * 100


def _source_signal(lead) -> float:
    return SOURCE_SCORES.get(lead.source, 30.0)


def _tier_for_score(score) -> str:
    if score >= TIER_HOT_THRESHOLD:
        return Lead.TIER_HOT
    if score >= TIER_WARM_THRESHOLD:
        return Lead.TIER_WARM
    return Lead.TIER_COLD


def compute_priority_score(lead) -> dict:
    """
    Scores one lead. Only meaningful for leads still being worked
    (Lead.ACTIVE_STATUSES) — callers may still call this on a
    closed/enrolled lead (e.g. for display of its last-known score), but
    there's no reason to recompute it going forward once a lead is closed.
    """
    signals = {
        "engagement": _engagement_signal(lead),
        "recency": _recency_signal(lead),
        "completeness": _completeness_signal(lead),
        "source": _source_signal(lead),
    }
    priority_score = sum(SIGNAL_WEIGHTS[key] * value for key, value in signals.items())

    return {
        "priority_score": round(priority_score, 1),
        "priority_tier": _tier_for_score(priority_score),
        "signals": signals,
    }

"""
campusflow_app/ai_narrative.py

Local, on-prem first-draft narrative writing for NAAC/NBA SSR/AQAR
accreditation criteria — talks to Ollama (a text model, e.g. llama3.2:3b)
over HTTP instead of a third-party API, so evidence data never leaves the
machine running Ollama. Sibling to ai_grading.py — same "small pure
functions, one custom exception, never writes to the database" shape (the
caller, run_accreditation_narrative_draft in tasks.py, owns all
persistence).
"""

import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "narrative": {
            "type": "string",
            "description": "The SSR/AQAR criterion write-up in formal accreditation-report prose.",
        },
        "caveats": {
            "type": "string",
            "description": "Gaps or weak spots in the available evidence the reviewer should double-check "
                            "before submitting this narrative, e.g. sub-metrics with no evidence at all. "
                            "Empty string if there's nothing to flag.",
        },
    },
    "required": ["narrative", "caveats"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You are an accreditation writing assistant helping an IQAC (Internal Quality Assurance Cell) "
    "coordinator draft a first-pass write-up for one NAAC or NBA self-study criterion. Your draft is "
    "reviewed and edited by the coordinator before it is submitted anywhere — accuracy and honest "
    "flagging of gaps matter more than a polished-sounding narrative.\n\n"
    "Write in the formal, factual prose style expected of an Indian higher-education accreditation "
    "self-study report (SSR/AQAR): third person, institution as subject, no first-person voice, no "
    "marketing language. Base every claim strictly on the evidence items provided — do not invent "
    "numbers, dates, or achievements that aren't in the evidence. If the evidence for this criterion "
    "is thin or missing entirely for a sub-aspect, say so plainly in the narrative rather than papering "
    "over the gap, and also list it in caveats so the reviewer knows exactly what to chase down before "
    "submission."
)


class NarrativeDraftError(Exception):
    """Raised for any failure drafting a narrative — safe to store verbatim as AccreditationNarrativeDraft.error_message."""


def _evidence_summary(criterion, financial_year) -> list:
    evidence = criterion.evidence.filter(financial_year=financial_year).select_related(
        "department", "linked_certificate",
    )
    return [
        {
            "department": item.department.name if item.department else "institution-wide",
            "description": item.description or "",
            "linked_certificate": item.linked_certificate.certificate_type.name if item.linked_certificate else None,
            "linked_record": (
                f"{item.linked_object_type} #{item.linked_object_id}" if item.linked_object_type else None
            ),
            "has_file": bool(item.file),
            "status": item.status,
        }
        for item in evidence
    ]


def build_criterion_narrative(criterion, financial_year) -> dict:
    """
    Drafts a narrative for one AccreditationCriterion + FinancialYear from
    its EvidenceItem set. Raises NarrativeDraftError on any failure. Caller
    is responsible for checking there's at least one evidence item before
    calling this (see the 400 guard in CriterionNarrativeDraftRequestView).
    """
    evidence_summary = _evidence_summary(criterion, financial_year)

    user_message = (
        f"Criterion: {criterion.get_body_display()} {criterion.code} — {criterion.title}\n"
        f"Financial year: {financial_year.label}\n\n"
        f"Evidence items on file for this criterion and year:\n"
        f"{json.dumps(evidence_summary, indent=2)}\n\n"
        "Draft the SSR/AQAR narrative for this criterion from the evidence above."
    )

    payload = {
        "model": settings.AI_NARRATIVE_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "format": _OUTPUT_SCHEMA,
        "stream": False,
        "options": {"temperature": 0.2, "num_predict": 4096, "num_ctx": settings.AI_NARRATIVE_NUM_CTX},
    }

    try:
        response = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=settings.AI_NARRATIVE_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.ConnectionError as e:
        raise NarrativeDraftError(
            f"Could not reach the local drafting model at {settings.OLLAMA_BASE_URL} — "
            f"is `ollama serve` running and has `{settings.AI_NARRATIVE_MODEL}` been pulled? ({e})"
        ) from e
    except requests.Timeout as e:
        raise NarrativeDraftError(
            f"Local drafting model timed out after {settings.AI_NARRATIVE_REQUEST_TIMEOUT_SECONDS}s: {e}"
        ) from e
    except requests.HTTPError as e:
        raise NarrativeDraftError(f"Drafting service error ({response.status_code}): {response.text[:500]}") from e
    except requests.RequestException as e:
        raise NarrativeDraftError(f"Could not reach the drafting service: {e}") from e

    data = response.json()

    if data.get("done_reason") == "length":
        raise NarrativeDraftError("The drafting model's response was truncated before completing — try again.")

    text = (data.get("message") or {}).get("content")
    if not text:
        raise NarrativeDraftError("The drafting model returned no usable content.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise NarrativeDraftError(f"The drafting model returned invalid JSON: {e}") from e

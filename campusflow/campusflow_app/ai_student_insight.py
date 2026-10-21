"""
campusflow_app/ai_student_insight.py

Local, on-prem interpretation of a student's already-computed performance
data — talks to Ollama over HTTP, same as ai_grading.py/ai_narrative.py, so
a student's exam/topic data never leaves the machine running Ollama.

This is a pure interpretation layer: the caller (run_student_insight_generation
in tasks.py) passes in the exact JSON StudentProgressView/
StudentTopicPerformanceView already computed — no new DB queries happen
here, and the model is instructed never to invent a number that isn't in
that input. It only turns real figures into a plain-language read and a
short list of next steps.
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
            "description": "A short (3-5 sentence), plain-language read of this student's performance — "
                            "what's going well, what isn't, addressed to a student/parent/teacher audience.",
        },
        "recommendations": {
            "type": "array",
            "items": {"type": "string"},
            "description": "2-4 concrete, actionable next steps, each naming a specific topic or course from "
                            "the data provided — never a vague generality like 'study harder'.",
        },
    },
    "required": ["narrative", "recommendations"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You are an academic-performance assistant helping a student, parent, or teacher understand one "
    "student's exam performance. You will be given already-computed, verified performance data — overall "
    "trend, per-course averages, and per-topic percentages from evaluated exams. Your job is only to "
    "interpret this data in plain language and suggest concrete next steps.\n\n"
    "Base every claim strictly on the figures provided — never invent a score, a topic name, or a course "
    "name that isn't in the data. If the data is thin (few exams, few topics tagged), say so plainly rather "
    "than overstating confidence. Write for a student/parent audience: clear, encouraging where the data "
    "supports it, direct about weak spots without being harsh. This is advisory interpretation, not a "
    "grade or an official record — never claim more certainty than the underlying data supports."
)


class StudentInsightError(Exception):
    """Raised for any failure generating an insight — safe to store verbatim as StudentInsightSnapshot.error_message."""


def build_student_insight(progress_data: dict, topic_data: dict) -> dict:
    """
    Drafts a narrative + recommendations from StudentProgressView's and
    StudentTopicPerformanceView's already-computed payloads. Raises
    StudentInsightError on any failure. Caller owns all persistence.
    """
    # Compact JSON: every prompt token costs time on a CPU model.
    def compact(value):
        return json.dumps(value, separators=(",", ":"), default=str)

    user_message = (
        f"Student: {progress_data.get('student_name', 'Unknown')}\n\n"
        f"Overall performance:\n{compact(progress_data.get('overall', {}))}\n\n"
        f"By course:\n{compact(progress_data.get('by_course', []))}\n\n"
        f"By topic (from evaluated answer scripts):\n{compact(topic_data.get('topics', []))}\n\n"
        f"Course-outcome attainment:\n{compact(topic_data.get('course_outcomes', []))}\n\n"
        "Write the narrative and recommendations for this student's performance from the data above."
    )

    payload = {
        "model": settings.AI_NARRATIVE_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "format": _OUTPUT_SCHEMA,
        "stream": False,
        # A 3-5 sentence read + 2-4 recommendations is ~250 tokens; 2048 let a
        # rambling reply run for minutes on CPU. num_ctx must stay equal to the
        # other AI_NARRATIVE_MODEL callers, or Ollama reloads the model each switch.
        "options": {"temperature": 0.2, "num_predict": 600, "num_ctx": settings.AI_NARRATIVE_NUM_CTX},
    }

    base_url = (getattr(settings, "OLLAMA_BASE_URL", "") or "http://localhost:11434").rstrip("/")
    try:
        response = requests.post(
            f"{base_url}/api/chat",
            json=payload,
            timeout=settings.AI_NARRATIVE_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.ConnectionError as e:
        raise StudentInsightError(
            f"Could not reach the local drafting model at {base_url} — "
            f"is `ollama serve` running and has `{settings.AI_NARRATIVE_MODEL}` been pulled? ({e})"
        ) from e
    except requests.Timeout as e:
        raise StudentInsightError(
            f"Local drafting model timed out after {settings.AI_NARRATIVE_REQUEST_TIMEOUT_SECONDS}s: {e}"
        ) from e
    except requests.HTTPError as e:
        raise StudentInsightError(f"Drafting service error ({response.status_code}): {response.text[:500]}") from e
    except requests.RequestException as e:
        raise StudentInsightError(f"Could not reach the drafting service: {e}") from e

    data = response.json()
    # Ollama reports where the time went (nanoseconds) — the first thing to
    # check when insights feel slow: model load vs. reading the prompt vs. writing.
    logger.info(
        "student insight timing: total=%.1fs load=%.1fs prompt=%s tok/%.1fs output=%s tok/%.1fs",
        data.get("total_duration", 0) / 1e9, data.get("load_duration", 0) / 1e9,
        data.get("prompt_eval_count"), data.get("prompt_eval_duration", 0) / 1e9,
        data.get("eval_count"), data.get("eval_duration", 0) / 1e9,
    )

    if data.get("done_reason") == "length":
        raise StudentInsightError("The drafting model's response was truncated before completing — try again.")

    text = (data.get("message") or {}).get("content")
    if not text:
        raise StudentInsightError("The drafting model returned no usable content.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise StudentInsightError(f"The drafting model returned invalid JSON: {e}") from e

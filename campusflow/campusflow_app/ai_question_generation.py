"""
campusflow_app/ai_question_generation.py

Local, on-prem question authoring — talks to Ollama over HTTP, same shape as
ai_grading.py/ai_narrative.py/ai_student_insight.py. Only ever called to fill
a marks shortfall the Question Bank couldn't cover for one topic during
paper generation (see the gap-fill step in views/paper_setting.py) — this is
"Question Bank first, AI fills gaps," not a from-scratch AI paper.

Grounded in the syllabus topic's own name/description and a handful of the
topic's *existing* bank question texts, used strictly as style/difficulty
calibration — the model is explicitly told never to reproduce an example
verbatim. Every question this produces is saved as a real Question bank row
with ai_generated=True, so a faculty member reviewing the composed paper
(before FinalizePaperView locks it — the human checkpoint) can see exactly
which questions weren't human-authored.
"""

import json
import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {
            "type": "string",
            "description": "The new exam question — a genuinely new question testing the same topic/concept, "
                            "not a reworded copy of any example given.",
        },
        "caveat": {
            "type": "string",
            "description": "Anything the reviewing faculty member should double-check before using this "
                            "question as-is (e.g. 'verify the numeric answer', 'may need a diagram'). "
                            "Empty string if there's nothing to flag.",
        },
    },
    "required": ["text", "caveat"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = (
    "You are an exam-question-writing assistant helping a faculty member fill a gap in an exam paper. "
    "The question bank for one syllabus topic doesn't have enough questions to reach the marks target, so "
    "you are asked to write one new question for that specific topic, at a specific marks value and "
    "difficulty. Your draft is reviewed by a faculty member before the paper is finalized — write a "
    "genuinely useful, correct, gradeable question, not a placeholder.\n\n"
    "You may be shown a few existing questions from the same topic's bank as style and difficulty "
    "reference only — never copy or lightly reword one of them; write a distinct question that tests the "
    "same underlying concept a different way. Match the requested marks value: a low-mark question should "
    "be answerable briefly, a high-mark question should require a fuller answer (derivation, multi-part, "
    "essay, etc. as appropriate to the subject). If you're not confident the question is well-formed or "
    "gradeable, say so plainly in the caveat rather than silently producing something weak."
)


class QuestionGenerationError(Exception):
    """Raised for any failure generating a question — safe to surface as a paper-generation warning."""


def generate_question(course, topic, target_marks, difficulty, existing_examples) -> dict:
    """
    existing_examples: list of question text strings from the same topic's
    bank, for style/difficulty calibration only. Raises
    QuestionGenerationError on any failure — the caller (the paper
    generation gap-fill loop) treats that as "couldn't fill this gap,"
    exactly like a bank shortfall, never a hard failure of the whole
    generation request.
    """
    examples_block = (
        "\n".join(f"- {ex}" for ex in existing_examples[:5])
        if existing_examples else "(no existing questions for this topic yet — write from the topic description alone)"
    )
    user_message = (
        f"Course: {course.course_name} ({course.course_code})\n"
        f"Topic: {topic.name}\n"
        f"Topic description: {topic.description or '(none provided)'}\n"
        f"Target marks: {target_marks}\n"
        f"Difficulty: {difficulty}\n\n"
        f"Existing questions for this topic (style/difficulty reference only — do not copy):\n{examples_block}\n\n"
        "Write one new question for this topic at the target marks and difficulty."
    )

    payload = {
        "model": settings.AI_NARRATIVE_MODEL,
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": user_message},
        ],
        "format": _OUTPUT_SCHEMA,
        "stream": False,
        "options": {"temperature": 0.4, "num_predict": 1024, "num_ctx": settings.AI_NARRATIVE_NUM_CTX},
    }

    try:
        response = requests.post(
            f"{settings.OLLAMA_BASE_URL}/api/chat",
            json=payload,
            timeout=settings.AI_NARRATIVE_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.ConnectionError as e:
        raise QuestionGenerationError(
            f"Could not reach the local drafting model at {settings.OLLAMA_BASE_URL} — "
            f"is `ollama serve` running and has `{settings.AI_NARRATIVE_MODEL}` been pulled? ({e})"
        ) from e
    except requests.Timeout as e:
        raise QuestionGenerationError(
            f"Local drafting model timed out after {settings.AI_NARRATIVE_REQUEST_TIMEOUT_SECONDS}s: {e}"
        ) from e
    except requests.HTTPError as e:
        raise QuestionGenerationError(f"Drafting service error ({response.status_code}): {response.text[:500]}") from e
    except requests.RequestException as e:
        raise QuestionGenerationError(f"Could not reach the drafting service: {e}") from e

    data = response.json()

    if data.get("done_reason") == "length":
        raise QuestionGenerationError("The drafting model's response was truncated before completing — try again.")

    text = (data.get("message") or {}).get("content")
    if not text:
        raise QuestionGenerationError("The drafting model returned no usable content.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise QuestionGenerationError(f"The drafting model returned invalid JSON: {e}") from e

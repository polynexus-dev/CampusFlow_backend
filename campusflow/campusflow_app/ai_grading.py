"""
campusflow_app/ai_grading.py

Claude-powered first-pass grading for scanned answer scripts. Mirrors the
shape of face_utils.py: a lazy singleton client, small pure functions, and a
single custom exception the caller (the Celery task in tasks.py) can catch
without needing to know about the Anthropic SDK's exception hierarchy.

Never writes to the database — that's the caller's job. This module only
fetches an image and asks Claude to grade it.
"""

import base64
import json
import logging

import anthropic
import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ALLOWED_IMAGE_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
IMAGE_FETCH_TIMEOUT_SECONDS = 15
IMAGE_FETCH_CHUNK_SIZE = 65536

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string", "description": "Question key, matching the question structure (e.g. 'Q1')."},
                    "score": {"type": "number", "description": "Suggested marks awarded for this question."},
                    "max_marks": {"type": "number", "description": "Max marks for this question, echoed from the question structure."},
                    "rationale": {"type": "string", "description": "One or two sentences explaining the suggested score."},
                    "confidence": {"type": "number", "description": "0-1 confidence that this score is correct."},
                },
                "required": ["key", "score", "max_marks", "rationale", "confidence"],
                "additionalProperties": False,
            },
        },
        "overall_confidence": {"type": "number", "description": "0-1 overall confidence across the whole paper."},
        "overall_notes": {"type": "string", "description": "Anything the evaluator should double-check before trusting this suggestion."},
    },
    "required": ["questions", "overall_confidence", "overall_notes"],
    "additionalProperties": False,
}

_client = None


class AIGradingError(Exception):
    """Raised for any failure fetching the scanned image or grading it — safe to store verbatim as AIGradingSuggestion.error_message."""


def _get_client() -> anthropic.Anthropic:
    global _client
    if _client is None:
        kwargs = {"api_key": settings.ANTHROPIC_API_KEY} if settings.ANTHROPIC_API_KEY else {}
        _client = anthropic.Anthropic(**kwargs)
    return _client


def fetch_scanned_image(url: str) -> tuple[bytes, str]:
    """
    Fetches the scanned answer-sheet image from its storage URL, validating
    content type and enforcing AI_GRADING_MAX_IMAGE_BYTES. Returns
    (image_bytes, media_type).
    """
    try:
        response = requests.get(url, timeout=IMAGE_FETCH_TIMEOUT_SECONDS, stream=True)
        response.raise_for_status()
    except requests.RequestException as e:
        raise AIGradingError(f"Could not fetch scanned paper image: {e}") from e

    media_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
    if media_type not in ALLOWED_IMAGE_MEDIA_TYPES:
        raise AIGradingError(
            f"Scanned paper URL did not return a supported image type (got '{media_type or 'unknown'}')."
        )

    max_bytes = settings.AI_GRADING_MAX_IMAGE_BYTES
    chunks = []
    total = 0
    for chunk in response.iter_content(chunk_size=IMAGE_FETCH_CHUNK_SIZE):
        total += len(chunk)
        if total > max_bytes:
            raise AIGradingError(f"Scanned paper image exceeds the {max_bytes // (1024 * 1024)} MB limit.")
        chunks.append(chunk)

    return b"".join(chunks), media_type


def _build_system_prompt(question_structure: dict, answer_key: dict) -> str:
    return (
        "You are an exam grading assistant giving a human evaluator a first-pass score "
        "suggestion for a scanned handwritten answer script. Your suggestion is reviewed by "
        "a qualified evaluator before it counts for anything, so honest uncertainty matters "
        "more than confident-sounding answers.\n\n"
        "For each question, read the student's handwritten answer in the image and assign a "
        "score out of that question's max marks. Use the rubric where one is given; where no "
        "rubric is given, use general academic judgment appropriate to the question. If "
        "handwriting is illegible or an answer is missing, score it 0 and say so plainly in "
        "the rationale rather than guessing at content you cannot read.\n\n"
        f"Question structure (question key -> max marks): {json.dumps(question_structure, sort_keys=True)}\n\n"
        f"Answer key / rubric (question key -> max_marks and rubric text, where provided): "
        f"{json.dumps(answer_key, sort_keys=True)}\n\n"
        "Return one entry in `questions` for every question key present in the question "
        "structure above, each with a suggested score, the question's max marks, a one- or "
        "two-sentence rationale, and a confidence between 0 and 1 (how sure you are the score "
        "itself is correct, not how sure you are of the underlying answer). Also return an "
        "overall_confidence and overall_notes summarizing anything the evaluator should "
        "double-check before trusting this suggestion."
    )


def grade_scanned_paper(image_bytes: bytes, media_type: str, question_structure: dict, answer_key: dict) -> dict:
    """
    Sends the scanned answer image + rubric to Claude and returns the parsed
    structured suggestion (matching _OUTPUT_SCHEMA). Raises AIGradingError on
    any failure — API errors, a model refusal, or unparseable output.
    """
    import base64

    client = _get_client()
    system_prompt = _build_system_prompt(question_structure, answer_key)

    try:
        response = client.messages.create(
            model=settings.AI_GRADING_MODEL,
            max_tokens=4096,
            system=[
                {
                    "type": "text",
                    "text": system_prompt,
                    # Shared verbatim across every paper in the same exam/session —
                    # caches after the first call so only the per-paper image is
                    # billed at full price on subsequent papers.
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                        },
                    },
                    {
                        "type": "text",
                        "text": "Grade this scanned answer script against the rubric above and "
                                "return the structured JSON result described.",
                    },
                ],
            }],
            output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
        )
    except anthropic.NotFoundError as e:
        raise AIGradingError(f"Grading model not found: {e}") from e
    except anthropic.RateLimitError as e:
        raise AIGradingError(f"Grading service is rate-limited, try again shortly: {e}") from e
    except anthropic.APIStatusError as e:
        raise AIGradingError(f"Grading service error ({e.status_code}): {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise AIGradingError(f"Could not reach the grading service: {e}") from e

    if response.stop_reason == "refusal":
        raise AIGradingError("The grading model declined to process this request.")
    if response.stop_reason == "max_tokens":
        raise AIGradingError("The grading model's response was truncated before completing — try again.")

    text = next((block.text for block in response.content if block.type == "text"), None)
    if not text:
        raise AIGradingError("The grading model returned no usable content.")

    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise AIGradingError(f"The grading model returned invalid JSON: {e}") from e

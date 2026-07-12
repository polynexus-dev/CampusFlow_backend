"""
Celery tasks.

Currently just one: the CPU-bound half of the face-attendance pipeline
(liveness + motion checks + ArcFace embedding extraction). It deliberately
does no DB access and knows nothing about tenants, students, or lectures —
that logic stays in MarkAttendanceView, which calls this task synchronously
via `.get(timeout=...)` and only moves on to DB reads/writes once it has a
result. Keeping the task DB-free avoids needing django-tenants schema
context inside the Celery worker process entirely.
"""

import base64
import logging

from celery import shared_task

from .face_utils import (
    _analyse_image,
    _decode_image,
    basic_liveness_check,
    check_frame_motion,
    check_head_motion,
    extract_embedding,
)

logger = logging.getLogger(__name__)


@shared_task(name="campusflow_app.run_face_pipeline")
def run_face_pipeline(photo_b64: str, photo_prev_b64: str | None, challenge_type: str) -> dict:
    """
    Run liveness, motion-liveness, and embedding extraction for one
    attendance attempt. Photos are base64-encoded because Celery task
    arguments go through the Redis broker as JSON.

    Returns a plain dict (JSON-safe) — the embedding, if extracted, is a
    list of floats rather than an ndarray.
    """
    photo_bytes = base64.b64decode(photo_b64)

    # Detect once and reuse the result across liveness, motion, and embedding
    # extraction below instead of each independently re-running InsightFace
    # detection on this same "action" frame — confirmed via
    # bench_face_pipeline.py to be ~3x redundant inference per attempt
    # (~1.9s), the single biggest lever on attendance-rush throughput.
    # Falls back to face=None on detection failure; basic_liveness_check
    # then redoes (and correctly errors on) detection itself, same as before.
    cv_image = _decode_image(photo_bytes)
    try:
        face, _ = _analyse_image(cv_image=cv_image)
    except ValueError:
        face = None

    liveness_passed, liveness_msg = basic_liveness_check(
        photo_bytes, _face=face, _cv_image=cv_image,
    )
    if not liveness_passed:
        return {
            "liveness_passed": False,
            "liveness_msg": liveness_msg,
            "motion_ok": False,
            "motion_msg": "",
            "embedding": None,
            "embedding_error": None,
        }

    if not photo_prev_b64:
        return {
            "liveness_passed": True,
            "liveness_msg": liveness_msg,
            "motion_ok": False,
            "motion_msg": "Baseline photo is required for verification.",
            "embedding": None,
            "embedding_error": None,
        }

    photo_prev_bytes = base64.b64decode(photo_prev_b64)

    # `face`/`cv_image` are guaranteed non-None here: liveness_passed can
    # only be True if _analyse_image succeeded on this exact image, whether
    # via the precompute above or basic_liveness_check's own fallback (which
    # would raise the same ValueError deterministically on the same input).
    try:
        if challenge_type == "blink":
            motion_ok, motion_score, motion_msg = check_frame_motion(
                photo_prev_bytes, photo_bytes, _face2=face, _img2=cv_image,
            )
        else:
            motion_ok, motion_score, motion_msg = check_head_motion(
                photo_prev_bytes, photo_bytes, challenge_type, _face2=face, _img2=cv_image,
            )
    except ValueError as e:
        motion_ok, motion_score, motion_msg = False, 0.0, str(e)

    if not motion_ok:
        return {
            "liveness_passed": True,
            "liveness_msg": liveness_msg,
            "motion_ok": False,
            "motion_score": motion_score,
            "motion_msg": motion_msg,
            "embedding": None,
            "embedding_error": None,
        }

    try:
        embedding = extract_embedding(_face=face)
        embedding_list = embedding.tolist()
        embedding_error = None
    except ValueError as e:
        embedding_list = None
        embedding_error = str(e)

    return {
        "liveness_passed": True,
        "liveness_msg": liveness_msg,
        "motion_ok": True,
        "motion_score": motion_score,
        "motion_msg": motion_msg,
        "embedding": embedding_list,
        "embedding_error": embedding_error,
    }

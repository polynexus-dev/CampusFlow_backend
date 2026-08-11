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
from django.conf import settings
from django_tenants.utils import schema_context

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


@shared_task(name="campusflow_app.run_ai_grading_suggestion", time_limit=300, soft_time_limit=270)
def run_ai_grading_suggestion(schema_name: str, suggestion_id: int) -> None:
    """
    Fetches a ScannedPaper's scanned image, grades it via a local Ollama
    vision model, and writes the result onto the AIGradingSuggestion row.
    Unlike run_face_pipeline, this task does need DB + tenant-schema access
    (it reads the exam's rubric and writes the suggestion), so it wraps its
    body in schema_context — the same per-tenant pattern used by the
    fine_tune_face_embeddings management command. Its own time_limit is
    much higher than CELERY_TASK_TIME_LIMIT because CPU-bound local LLM
    inference on a scanned image runs far longer than the local ONNX
    inference the default budgets for.

    Never raises — any failure is recorded on the suggestion row as
    status="failed" so the caller (which fired this with .delay(), not
    .get()) can find out by polling, not by catching an exception here.
    """
    from .ai_grading import AIGradingError, fetch_scanned_image, grade_scanned_paper
    from .models.ai_grading import AIGradingSuggestion

    with schema_context(schema_name):
        try:
            suggestion = AIGradingSuggestion.objects.select_related(
                "scanned_paper__session__exam",
            ).get(pk=suggestion_id)
        except AIGradingSuggestion.DoesNotExist:
            logger.error("run_ai_grading_suggestion: suggestion %s not found in schema %s", suggestion_id, schema_name)
            return

        paper = suggestion.scanned_paper
        exam = paper.session.exam

        try:
            image_bytes, _media_type = fetch_scanned_image(paper.scanned_file_url)
            result = grade_scanned_paper(
                image_bytes, exam.question_structure, exam.answer_key,
            )
        except AIGradingError as e:
            suggestion.status = "failed"
            suggestion.error_message = str(e)
            suggestion.save(update_fields=["status", "error_message"])
            return
        except Exception as e:  # noqa: BLE001 - last-resort guard so a bug here always lands as a visible failed suggestion
            logger.exception("run_ai_grading_suggestion: unexpected error grading suggestion %s", suggestion_id)
            suggestion.status = "failed"
            suggestion.error_message = f"Unexpected error: {e}"
            suggestion.save(update_fields=["status", "error_message"])
            return

        question_scores_suggested = {
            q["key"]: {
                "score": q["score"],
                "max_marks": q["max_marks"],
                "rationale": q["rationale"],
                "confidence": q["confidence"],
            }
            for q in result.get("questions", [])
        }
        suggestion.question_scores_suggested = question_scores_suggested
        suggestion.overall_confidence = result.get("overall_confidence")
        suggestion.overall_notes = result.get("overall_notes", "")
        suggestion.model_used = getattr(settings, "AI_GRADING_MODEL", "")
        suggestion.save(update_fields=[
            "question_scores_suggested", "overall_confidence", "overall_notes", "model_used",
        ])


@shared_task(name="campusflow_app.run_accreditation_narrative_draft", time_limit=240, soft_time_limit=210)
def run_accreditation_narrative_draft(schema_name: str, draft_id: int) -> None:
    """
    Drafts an SSR/AQAR criterion narrative via a local Ollama text model and
    writes it onto the AccreditationNarrativeDraft row. Same shape as
    run_ai_grading_suggestion: schema_context-wrapped (Celery workers have
    no ambient tenant context), never raises (the caller polls via
    .delay(), not .get()), and a higher time_limit than the file-level
    Celery default since local CPU prose generation runs far longer than
    the local ONNX inference the default budgets for.
    """
    from .ai_narrative import NarrativeDraftError, build_criterion_narrative
    from .models.accreditation_narrative import AccreditationNarrativeDraft

    with schema_context(schema_name):
        try:
            draft = AccreditationNarrativeDraft.objects.select_related(
                "criterion", "financial_year",
            ).get(pk=draft_id)
        except AccreditationNarrativeDraft.DoesNotExist:
            logger.error("run_accreditation_narrative_draft: draft %s not found in schema %s", draft_id, schema_name)
            return

        try:
            result = build_criterion_narrative(draft.criterion, draft.financial_year)
        except NarrativeDraftError as e:
            draft.status = "failed"
            draft.error_message = str(e)
            draft.save(update_fields=["status", "error_message"])
            return
        except Exception as e:  # noqa: BLE001 - last-resort guard so a bug here always lands as a visible failed draft
            logger.exception("run_accreditation_narrative_draft: unexpected error drafting %s", draft_id)
            draft.status = "failed"
            draft.error_message = f"Unexpected error: {e}"
            draft.save(update_fields=["status", "error_message"])
            return

        draft.narrative_text = result.get("narrative", "")
        draft.caveats = result.get("caveats", "")
        draft.model_used = getattr(settings, "AI_GRADING_MODEL", "")
        draft.save(update_fields=["narrative_text", "caveats", "model_used"])


@shared_task(name="campusflow_app.run_generate_timetable", time_limit=90, soft_time_limit=80)
def run_generate_timetable(schema_name: str, run_id: int) -> None:
    """
    Solves the timetabling CSP for one TimetableGenerationRun via CP-SAT
    (services/timetable_generation.py) and writes the result as draft
    Schedule rows (is_draft=True) linked to the run — never live rows.
    Same shape as the other tasks in this file: schema_context-wrapped,
    fetch-or-log-and-return, never raises past the task boundary. The task's
    own time_limit (90s) sits above the solver's internal search budget
    (TIMETABLE_SOLVER_TIME_LIMIT_SECONDS, default 60s) to leave headroom for
    the DB writes.
    """
    import datetime
    import time

    from .models.offerings import CourseOffering
    from .models.schedule import Schedule
    from .models.timetable_generation import TimetableGenerationRun
    from .services.timetable_generation import TimetableInfeasibleError, generate_timetable

    def add_one_hour(start_time):
        # Every v1 slot is exactly 1 hour (see TIMETABLE_SLOT_START_TIMES) —
        # combine with a throwaway date so the stdlib handles any edge case,
        # then discard the date again.
        return (datetime.datetime.combine(datetime.date.today(), start_time)
                + datetime.timedelta(hours=1)).time()

    with schema_context(schema_name):
        try:
            run = TimetableGenerationRun.objects.select_related("term", "department").get(pk=run_id)
        except TimetableGenerationRun.DoesNotExist:
            logger.error("run_generate_timetable: run %s not found in schema %s", run_id, schema_name)
            return

        started = time.monotonic()
        try:
            placements = generate_timetable(run.term, department=run.department)
        except TimetableInfeasibleError as e:
            run.status = "infeasible"
            run.solve_time_seconds = time.monotonic() - started
            run.unscheduled_offerings = e.unscheduled_offering_ids
            run.save(update_fields=["status", "solve_time_seconds", "unscheduled_offerings"])
            return
        except Exception as e:  # noqa: BLE001 - last-resort guard so a bug here always lands as a visible failed run
            logger.exception("run_generate_timetable: unexpected error solving run %s", run_id)
            run.status = "failed"
            run.error_message = f"Unexpected error: {e}"
            run.save(update_fields=["status", "error_message"])
            return

        solve_time = time.monotonic() - started
        course_id_by_offering = dict(
            CourseOffering.objects.filter(
                id__in={p["offering_id"] for p in placements},
            ).values_list("id", "course_id")
        )
        draft_rows = [
            Schedule(
                course_id=course_id_by_offering[placement["offering_id"]],
                faculty_id=placement["faculty_id"],
                classroom_id=placement["classroom_id"],
                day_of_week=placement["day_of_week"],
                start_time=placement["start_time"],
                end_time=add_one_hour(placement["start_time"]),
                semester=run.term.name,
                academic_year=run.term.academic_year.name,
                term=run.term,
                course_offering_id=placement["offering_id"],
                is_draft=True,
                generation_run=run,
            )
            for placement in placements
        ]
        Schedule.objects.bulk_create(draft_rows)

        run.status = "completed"
        run.solve_time_seconds = solve_time
        run.save(update_fields=["status", "solve_time_seconds"])

import json
import logging
from collections import defaultdict
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone
from django_tenants.utils import tenant_context
from tenants.models import Tenant

from campusflow_app.face_utils import blend_embedding, l2_normalize
from campusflow_app.models.face_embedding import FaceEmbedding, FaceEmbeddingSample

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        "Monthly self-improvement pass for face-recognition templates. The ArcFace "
        "backbone itself is never retrained — instead this consolidates each "
        "student's accumulated high-confidence FaceEmbeddingSample captures (logged "
        "by MarkAttendanceView) into a robust, outlier-rejected candidate template.\n\n"
        "This command NEVER writes to the live FaceEmbedding table. Candidates are "
        "staged as a JSON file under FACE_FINE_TUNED_OUTPUT_ROOT/<tenant>/<YYYY-MM>/ "
        "for review/testing. Run `promote_fine_tuned_embeddings` afterwards to apply "
        "a candidate file you've reviewed and are happy with.\n\n"
        "Intended to run once a month via cron / Task Scheduler, e.g.:\n"
        "  0 3 1 * * cd /path/to/campusflow && python manage.py fine_tune_face_embeddings"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what candidates would be staged without writing the JSON file "
                 "or marking samples as staged.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        min_samples = settings.FACE_MONTHLY_FINE_TUNE_MIN_SAMPLES
        outlier_floor = settings.FACE_MONTHLY_FINE_TUNE_OUTLIER_FLOOR
        blend_weight = settings.FACE_MONTHLY_FINE_TUNE_BLEND_WEIGHT

        self.stdout.write(
            f"[{timezone.now()}] Starting monthly face-embedding fine-tune "
            f"(dry_run={dry_run}, min_samples={min_samples})..."
        )

        total_staged = 0
        for tenant in Tenant.objects.exclude(schema_name="public"):
            with tenant_context(tenant):
                staged = self._stage_tenant(tenant.schema_name, min_samples, outlier_floor, blend_weight, dry_run)
            if staged:
                self.stdout.write(f"Schema '{tenant.schema_name}': staged {staged} candidate(s) for review.")
            total_staged += staged

        self.stdout.write(self.style.SUCCESS(
            f"Monthly face-embedding fine-tune completed — "
            f"{total_staged} candidate(s) staged for review across all schemas."
        ))

    def _stage_tenant(self, schema_name, min_samples, outlier_floor, blend_weight, dry_run):
        samples_by_key = defaultdict(list)
        for sample in FaceEmbeddingSample.objects.filter(
            staged_at__isnull=True, consumed_at__isnull=True
        ).select_related("student"):
            samples_by_key[(sample.student_id, sample.angle)].append(sample)

        candidates = []
        samples_to_stage = []
        samples_to_discard = []

        for (student_id, angle), samples in samples_by_key.items():
            if len(samples) < min_samples:
                continue

            try:
                record = FaceEmbedding.objects.get(student_id=student_id, angle=angle)
            except FaceEmbedding.DoesNotExist:
                # Student re-registered or removed their template since these
                # samples were captured — the samples no longer apply.
                samples_to_discard.extend(samples)
                continue

            old_embedding = np.array(record.embedding, dtype=np.float32)
            sample_embeddings = np.stack(
                [np.array(s.embedding, dtype=np.float32) for s in samples]
            )

            # Outlier rejection: drop captures that drifted too far from the
            # CURRENT template — guards against a single spoofed/bad capture
            # (that slipped past liveness) skewing the consolidated centroid.
            similarities = sample_embeddings @ old_embedding
            keep_mask = similarities >= outlier_floor
            retained_samples = [s for s, keep in zip(samples, keep_mask) if keep]
            retained_embeddings = sample_embeddings[keep_mask]
            rejected = len(samples) - len(retained_samples)

            if rejected:
                logger.warning(
                    "Monthly fine-tune — student_id=%s angle=%s rejected %d/%d "
                    "samples as outliers (floor=%.2f)",
                    student_id, angle, rejected, len(samples), outlier_floor,
                )

            if len(retained_samples) < max(3, min_samples // 2):
                # Not enough trustworthy data this cycle — don't stage a candidate,
                # but still retire the batch so it isn't re-evaluated forever.
                samples_to_discard.extend(samples)
                continue

            new_centroid = l2_normalize(retained_embeddings.mean(axis=0))
            consolidated = blend_embedding(old_embedding, new_centroid, blend_weight)
            similarity_old_vs_new = float(old_embedding @ consolidated)

            self.stdout.write(
                f"  student_id={student_id} ({samples[0].student.student_id}) angle={angle}: "
                f"staging candidate from {len(retained_samples)} samples ({rejected} rejected), "
                f"similarity to current template={similarity_old_vs_new:.4f}"
            )

            candidates.append({
                "student_pk": student_id,
                "student_code": samples[0].student.student_id,
                "angle": angle,
                "sample_ids": [s.id for s in retained_samples],
                "retained_count": len(retained_samples),
                "rejected_count": rejected,
                "sample_count_before": record.sample_count,
                "sample_count_after": record.sample_count + len(retained_samples),
                "similarity_old_vs_new": similarity_old_vs_new,
                "old_embedding": old_embedding.tolist(),
                "new_embedding": consolidated.tolist(),
            })
            # Only the samples that actually fed the candidate are staged;
            # outlier-rejected ones are discarded (their capture didn't fit
            # the existing template well and shouldn't silently keep piling up).
            samples_to_stage.extend(retained_samples)
            samples_to_discard.extend(s for s, keep in zip(samples, keep_mask) if not keep)

        if dry_run:
            return len(candidates)

        now = timezone.now()
        if samples_to_stage:
            for sample in samples_to_stage:
                sample.staged_at = now
            FaceEmbeddingSample.objects.bulk_update(samples_to_stage, ["staged_at"])
        if samples_to_discard:
            # Rejected/orphaned samples are marked consumed directly — they were
            # evaluated and are not going into any candidate, so there's nothing
            # left to promote for them.
            for sample in samples_to_discard:
                sample.consumed_at = now
            FaceEmbeddingSample.objects.bulk_update(samples_to_discard, ["consumed_at"])

        if candidates:
            self._write_manifest(schema_name, candidates, min_samples, outlier_floor, blend_weight)

        return len(candidates)

    def _write_manifest(self, schema_name, candidates, min_samples, outlier_floor, blend_weight):
        now = timezone.now()
        month_dir = Path(settings.FACE_FINE_TUNED_OUTPUT_ROOT) / schema_name / now.strftime("%Y-%m")
        month_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = month_dir / f"candidates_{now.strftime('%Y%m%dT%H%M%S')}.json"
        manifest = {
            "generated_at": now.isoformat(),
            "tenant_schema": schema_name,
            "settings": {
                "min_samples": min_samples,
                "outlier_floor": outlier_floor,
                "blend_weight": blend_weight,
            },
            "candidates": candidates,
        }

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        self.stdout.write(
            f"  Wrote {len(candidates)} candidate(s) to {manifest_path} — "
            f"review, then run: python manage.py promote_fine_tuned_embeddings "
            f"--file \"{manifest_path}\""
        )

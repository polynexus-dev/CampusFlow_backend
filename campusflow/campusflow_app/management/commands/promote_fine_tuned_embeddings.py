import json
from pathlib import Path

import numpy as np
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django_tenants.utils import tenant_context
from tenants.models import Tenant

from campusflow_app.models.face_embedding import FaceEmbedding, FaceEmbeddingSample

# Candidate is skipped (not applied) if the live template drifted from what was
# recorded at staging time by more than this — e.g. the student re-registered,
# or a real-time adaptive nudge landed, after the candidate was staged.
SAFETY_SIMILARITY_FLOOR = 0.999


class Command(BaseCommand):
    help = (
        "Apply a reviewed candidate file produced by `fine_tune_face_embeddings` to "
        "the live FaceEmbedding table. Nothing from the monthly job is ever applied "
        "automatically — you review the JSON (or test it) first, then run this.\n\n"
        "Examples:\n"
        "  python manage.py promote_fine_tuned_embeddings --file fine_tuned_embeddings/acme/2026-07/candidates_20260709T031500.json\n"
        "  python manage.py promote_fine_tuned_embeddings --tenant acme --month 2026-07\n"
        "  python manage.py promote_fine_tuned_embeddings --tenant acme --month 2026-07 --dry-run"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--file", help="Path to one specific candidates_*.json manifest to apply."
        )
        parser.add_argument(
            "--tenant", help="Tenant schema name — applies every pending manifest for that tenant/month."
        )
        parser.add_argument(
            "--month", help="Month folder to scan, format YYYY-MM. Required when using --tenant without --file."
        )
        parser.add_argument(
            "--dry-run", action="store_true",
            help="Report what would be applied without touching the database or moving files.",
        )
        parser.add_argument(
            "--force", action="store_true",
            help="Apply even if the live template has drifted from what was recorded at staging time.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        if options["file"]:
            manifest_paths = [Path(options["file"])]
        elif options["tenant"] and options["month"]:
            month_dir = Path(settings.FACE_FINE_TUNED_OUTPUT_ROOT) / options["tenant"] / options["month"]
            manifest_paths = sorted(month_dir.glob("candidates_*.json")) if month_dir.exists() else []
            if not manifest_paths:
                self.stdout.write(f"No pending candidate files found in {month_dir}.")
                return
        else:
            raise CommandError("Provide either --file, or both --tenant and --month.")

        for manifest_path in manifest_paths:
            self._apply_manifest(manifest_path, dry_run, options["force"])

    def _apply_manifest(self, manifest_path, dry_run, force):
        if not manifest_path.exists():
            raise CommandError(f"Manifest not found: {manifest_path}")

        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)

        schema_name = manifest["tenant_schema"]
        try:
            tenant = Tenant.objects.get(schema_name=schema_name)
        except Tenant.DoesNotExist:
            raise CommandError(f"Tenant schema '{schema_name}' not found (from {manifest_path}).")

        self.stdout.write(f"Applying {manifest_path} ({len(manifest['candidates'])} candidate(s)) to '{schema_name}'...")

        applied, skipped = 0, 0
        with tenant_context(tenant):
            for candidate in manifest["candidates"]:
                if self._apply_candidate(candidate, dry_run, force):
                    applied += 1
                else:
                    skipped += 1

        self.stdout.write(self.style.SUCCESS(
            f"  {applied} applied, {skipped} skipped."
        ))

        if not dry_run and skipped == 0:
            applied_dir = manifest_path.parent / "applied"
            applied_dir.mkdir(exist_ok=True)
            manifest_path.rename(applied_dir / manifest_path.name)
            self.stdout.write(f"  Moved manifest to {applied_dir / manifest_path.name}")
        elif not dry_run and skipped:
            self.stdout.write(
                "  Some candidates were skipped — manifest left in place. "
                "Re-run fine_tune_face_embeddings to generate a fresh candidate for skipped students."
            )

    def _apply_candidate(self, candidate, dry_run, force):
        student_pk = candidate["student_pk"]
        angle = candidate["angle"]
        student_code = candidate.get("student_code", student_pk)

        try:
            record = FaceEmbedding.objects.get(student_id=student_pk, angle=angle)
        except FaceEmbedding.DoesNotExist:
            self.stdout.write(f"  SKIP student={student_code} angle={angle}: template no longer exists.")
            return False

        if not force:
            current = np.array(record.embedding, dtype=np.float32)
            staged_old = np.array(candidate["old_embedding"], dtype=np.float32)
            drift = float(current @ staged_old)
            if drift < SAFETY_SIMILARITY_FLOOR:
                self.stdout.write(
                    f"  SKIP student={student_code} angle={angle}: live template drifted since "
                    f"staging (similarity={drift:.5f} < {SAFETY_SIMILARITY_FLOOR}). Use --force to override."
                )
                return False

        self.stdout.write(
            f"  APPLY student={student_code} angle={angle}: "
            f"sample_count {candidate['sample_count_before']} -> {candidate['sample_count_after']}, "
            f"similarity to previous template={candidate['similarity_old_vs_new']:.4f}"
        )

        if dry_run:
            return True

        record.embedding = candidate["new_embedding"]
        record.sample_count = candidate["sample_count_after"]
        record.save(update_fields=["embedding", "sample_count", "updated_at"])

        now = timezone.now()
        FaceEmbeddingSample.objects.filter(
            id__in=candidate["sample_ids"], consumed_at__isnull=True
        ).update(consumed_at=now)

        return True

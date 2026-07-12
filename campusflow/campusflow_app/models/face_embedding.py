from django.db import models
from .profile import StudentProfile

class FaceEmbedding(models.Model):
    """
    Stores a 512-dimensional facial embedding vector for a specific
    face angle of a student. Stores the ArcFace embedding vector as a list of floats.
    """

    class Angle(models.TextChoices):
        FRONT = "front", "Front"
        LEFT = "left", "Left Profile"
        RIGHT = "right", "Right Profile"

    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="face_embeddings",
    )
    angle = models.CharField(max_length=10, choices=Angle.choices)
    image = models.ImageField(
        upload_to="face_templates/",
        null=True,
        blank=True,
        help_text="Registered face image file for this angle.",
    )
    embedding = models.JSONField(
        help_text="512-d ArcFace embedding vector as a list of floats.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(
        auto_now=True,
        help_text="Last time this template was nudged by adaptive learning or monthly fine-tuning.",
    )
    sample_count = models.PositiveIntegerField(
        default=1,
        help_text="Number of live captures folded into this template so far (real-time + monthly).",
    )

    class Meta:
        db_table = "face_embeddings"
        verbose_name = "Face Embedding"
        verbose_name_plural = "Face Embeddings"
        # One embedding per angle per student
        constraints = [
            models.UniqueConstraint(
                fields=["student", "angle"],
                name="unique_student_angle",
            )
        ]

    def __str__(self):
        return f"{self.student} — {self.get_angle_display()}"


class FaceEmbeddingSample(models.Model):
    """
    Append-only log of high-confidence live embeddings captured during
    attendance verification (FACE_ADAPTIVE_LEARNING_THRESHOLD or above).

    Lifecycle:
      1. MarkAttendanceView writes one of these rows for every high-confidence
         verified capture (also nudges the live template immediately via a
         small, bounded EMA step — separate from this staging pipeline).
      2. The monthly `fine_tune_face_embeddings` command consumes unstaged rows
         per student/angle, computes a robust outlier-rejected candidate
         centroid, writes it to a JSON file under
         FACE_FINE_TUNED_OUTPUT_ROOT/<schema>/<YYYY-MM>/ for review, and sets
         `staged_at` on the rows it used (so they aren't picked up again).
      3. The `promote_fine_tuned_embeddings` command applies a reviewed
         candidate file to the live FaceEmbedding template and sets
         `consumed_at` on the staged rows it promoted.
    """

    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="face_embedding_samples",
    )
    angle = models.CharField(max_length=10, choices=FaceEmbedding.Angle.choices)
    embedding = models.JSONField(
        help_text="512-d live ArcFace embedding captured during a verified attendance match.",
    )
    confidence_score = models.FloatField(
        help_text="Cosine similarity score against the stored template at capture time.",
    )
    captured_at = models.DateTimeField(auto_now_add=True)
    staged_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set once the monthly fine-tune job has folded this sample into a candidate file pending review.",
    )
    consumed_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Set once a reviewed candidate containing this sample has been promoted into the live template.",
    )

    class Meta:
        db_table = "face_embedding_samples"
        verbose_name = "Face Embedding Sample"
        verbose_name_plural = "Face Embedding Samples"
        ordering = ["-captured_at"]

    def __str__(self):
        return f"{self.student} — {self.angle} sample @ {self.captured_at:%Y-%m-%d}"


class BiometricConsentLog(models.Model):
    """
    Explicitly logs the consent details of students agreeing to register
    and process biometric data (face templates) for attendance tracking.
    """
    student = models.ForeignKey(
        StudentProfile,
        on_delete=models.CASCADE,
        related_name="biometric_consents"
    )
    consent_given = models.BooleanField(default=True)
    consent_timestamp = models.DateTimeField(auto_now_add=True)
    consent_version = models.CharField(max_length=10, default="v1.0")
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, null=True, blank=True)

    class Meta:
        db_table = "biometric_consent_logs"
        verbose_name = "Biometric Consent Log"
        verbose_name_plural = "Biometric Consent Logs"
        ordering = ["-consent_timestamp"]

    def __str__(self):
        return f"Biometric Consent for {self.student} at {self.consent_timestamp}"


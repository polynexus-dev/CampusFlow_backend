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

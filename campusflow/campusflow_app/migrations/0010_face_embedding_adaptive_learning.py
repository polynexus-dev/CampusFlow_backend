import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("campusflow_app", "0009_administratorprofile_consent_given_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="faceembedding",
            name="sample_count",
            field=models.PositiveIntegerField(
                default=1,
                help_text="Number of live captures folded into this template so far (real-time + monthly).",
            ),
        ),
        migrations.AddField(
            model_name="faceembedding",
            name="updated_at",
            field=models.DateTimeField(
                auto_now=True,
                help_text="Last time this template was nudged by adaptive learning or monthly fine-tuning.",
            ),
        ),
        migrations.CreateModel(
            name="FaceEmbeddingSample",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "angle",
                    models.CharField(
                        choices=[
                            ("front", "Front"),
                            ("left", "Left Profile"),
                            ("right", "Right Profile"),
                        ],
                        max_length=10,
                    ),
                ),
                (
                    "embedding",
                    models.JSONField(
                        help_text="512-d live ArcFace embedding captured during a verified attendance match."
                    ),
                ),
                (
                    "confidence_score",
                    models.FloatField(
                        help_text="Cosine similarity score against the stored template at capture time."
                    ),
                ),
                ("captured_at", models.DateTimeField(auto_now_add=True)),
                (
                    "staged_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Set once the monthly fine-tune job has folded this sample into a candidate file pending review.",
                        null=True,
                    ),
                ),
                (
                    "consumed_at",
                    models.DateTimeField(
                        blank=True,
                        help_text="Set once a reviewed candidate containing this sample has been promoted into the live template.",
                        null=True,
                    ),
                ),
                (
                    "student",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="face_embedding_samples",
                        to="campusflow_app.studentprofile",
                    ),
                ),
            ],
            options={
                "verbose_name": "Face Embedding Sample",
                "verbose_name_plural": "Face Embedding Samples",
                "db_table": "face_embedding_samples",
                "ordering": ["-captured_at"],
            },
        ),
    ]

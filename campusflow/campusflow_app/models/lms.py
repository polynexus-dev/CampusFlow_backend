"""
Course content library (LMS). Docs/college_gap_closure_plan.md §1.3.

Content hangs off a CourseOffering (a course taught to a batch in a term), so
a student sees exactly the offerings they are registered for. Modules can
point at a SyllabusTopic, which keeps content and syllabus coverage linked.

Video is links only (YouTube unlisted, Drive, etc.), not uploads: hosting
video has a real storage and bandwidth cost we take on only when a paying
customer asks for it.
"""
from django.contrib.auth.models import User
from django.db import models

from .offerings import CourseOffering
from .profile import StudentProfile


class CourseModule(models.Model):
    offering = models.ForeignKey(CourseOffering, on_delete=models.CASCADE, related_name="lms_modules")
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True)
    syllabus_topic = models.ForeignKey(
        "campusflow_app.SyllabusTopic", on_delete=models.SET_NULL, null=True, blank=True, related_name="lms_modules",
    )
    order = models.PositiveSmallIntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="lms_modules_created")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["offering", "order", "id"]

    def __str__(self):
        return self.title


class LearningResource(models.Model):
    TYPE_FILE = "file"
    TYPE_VIDEO = "video_url"
    TYPE_LINK = "link"
    TYPE_NOTE = "note"
    TYPE_CHOICES = [
        (TYPE_FILE, "File"),
        (TYPE_VIDEO, "Video link"),
        (TYPE_LINK, "Web link"),
        (TYPE_NOTE, "Text note"),
    ]

    module = models.ForeignKey(CourseModule, on_delete=models.CASCADE, related_name="resources")
    title = models.CharField(max_length=255)
    resource_type = models.CharField(max_length=12, choices=TYPE_CHOICES)
    file = models.FileField(upload_to="lms/resources/", null=True, blank=True)
    url = models.URLField(max_length=1000, blank=True)
    body = models.TextField(blank=True, help_text="Text content for a note.")
    is_published = models.BooleanField(default=True)
    release_at = models.DateTimeField(
        null=True, blank=True, help_text="If set, students only see the resource from this time.",
    )
    order = models.PositiveSmallIntegerField(default=0)
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="lms_resources_uploaded")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["module", "order", "id"]

    def __str__(self):
        return self.title


class ResourceView(models.Model):
    """Engagement signal for AI student insight and risk scoring."""
    resource = models.ForeignKey(LearningResource, on_delete=models.CASCADE, related_name="views")
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="resource_views")
    first_viewed_at = models.DateTimeField(auto_now_add=True)
    last_viewed_at = models.DateTimeField(auto_now=True)
    view_count = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["resource", "student"], name="uniq_resource_view_per_student"),
        ]

from django.db import models
from django.contrib.auth.models import User
from .department import Department
from .course import Course

class Assignment(models.Model):
    title = models.CharField(
        max_length=255,
        help_text="Title of the assignment."
    )
    description = models.TextField(
        help_text="Detailed description and instructions for the assignment."
    )
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name='assignments',
        help_text="Department this assignment belongs to."
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, related_name='assignments',
        help_text="Course/subject of the assignment."
    )
    due_date = models.DateTimeField(
        help_text="Due date and time for submissions."
    )
    attachment = models.FileField(
        upload_to='assignments/attachments/', null=True, blank=True,
        help_text="Optional instruction document or template."
    )
    notify_parents = models.BooleanField(
        default=False,
        help_text="If true, a notification is sent to the guardians of every student in this assignment's department when created.",
    )
    # OBE: an assignment tagged with a CO and a numeric max_marks counts as CO
    # evidence (services/co_evidence.py assignment_evidence).
    course_outcome = models.ForeignKey(
        'campusflow_app.CourseOutcome', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='assignments',
        help_text="Course outcome this assignment assesses. Feeds CO attainment.",
    )
    max_marks = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text="Maximum marks. Required for the assignment to count toward CO attainment.",
    )
    created_by = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='assignments_created',
        help_text="Faculty member who posted this assignment."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Assignment"
        verbose_name_plural = "Assignments"
        ordering = ['-due_date']

    def __str__(self):
        return f"{self.title} ({self.course.course_code})"

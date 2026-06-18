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

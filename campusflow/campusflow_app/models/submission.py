from django.db import models
from django.contrib.auth.models import User
from .assignment import Assignment

class AssignmentSubmission(models.Model):
    STATUS_CHOICES = [
        ('submitted', 'Submitted'),
        ('graded', 'Graded'),
    ]

    assignment = models.ForeignKey(
        Assignment, on_delete=models.CASCADE, related_name='submissions',
        help_text="The assignment this submission belongs to."
    )
    student = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='submissions',
        help_text="The student who submitted this work."
    )
    submitted_at = models.DateTimeField(auto_now_add=True)
    attachment = models.FileField(
        upload_to='assignments/submissions/', null=True, blank=True,
        help_text="Uploaded file containing student's answers."
    )
    text_submission = models.TextField(
        blank=True, null=True,
        help_text="Optional text-based response or notes from student."
    )
    grade = models.CharField(
        max_length=20, blank=True, null=True,
        help_text="Grade or score assigned by the faculty."
    )
    feedback = models.TextField(
        blank=True, null=True,
        help_text="Grading feedback or remarks from the instructor."
    )
    status = models.CharField(
        max_length=20, choices=STATUS_CHOICES, default='submitted',
        help_text="Current grading status."
    )

    class Meta:
        verbose_name = "Assignment Submission"
        verbose_name_plural = "Assignment Submissions"
        unique_together = ('assignment', 'student')
        ordering = ['-submitted_at']

    def __str__(self):
        return f"Submission: {self.assignment.title} by {self.student.username}"

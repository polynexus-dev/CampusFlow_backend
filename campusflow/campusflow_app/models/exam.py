from django.db import models
from django.contrib.auth.models import User
from .department import Department
from .course import Course
from .classroom import Classroom


class ExamType(models.Model):
    """
    Configurable exam categories (e.g. Mid-Term, End Semester, Practical, Viva).
    """
    name = models.CharField(max_length=100, help_text="e.g. Mid-Term, End Semester")
    code = models.CharField(max_length=10, unique=True, help_text="Short code, e.g. MID, END, PRAC")

    class Meta:
        verbose_name = "Exam Type"
        verbose_name_plural = "Exam Types"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class Exam(models.Model):
    """
    Represents a single scheduled exam for a course in a department.
    Includes room allocation, invigilator assignment, and timing.
    """
    STATUS_CHOICES = [
        ('scheduled', 'Scheduled'),
        ('ongoing', 'Ongoing'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]

    name = models.CharField(max_length=255, help_text="e.g. CSE Mid-Term Exam June 2026")
    exam_type = models.ForeignKey(
        ExamType, on_delete=models.CASCADE,
        related_name='exams'
    )
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE,
        related_name='exams'
    )
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE,
        related_name='exams'
    )
    date = models.DateField()
    start_time = models.TimeField()
    end_time = models.TimeField()
    classroom = models.ForeignKey(
        Classroom, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='exams',
        help_text="Room allocated for this exam."
    )
    total_marks = models.PositiveIntegerField(default=100)
    passing_marks = models.PositiveIntegerField(default=35)
    semester = models.CharField(max_length=50, blank=True, null=True)
    academic_year = models.CharField(max_length=9, blank=True, null=True, help_text="e.g. 2025-2026")
    invigilator = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='invigilated_exams',
        help_text="Faculty assigned as invigilator."
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='exams_created'
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='scheduled')
    instructions = models.TextField(blank=True, null=True, help_text="Special instructions for this exam.")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Exam"
        verbose_name_plural = "Exams"
        ordering = ['date', 'start_time']

    def __str__(self):
        return f"{self.name} — {self.date} ({self.start_time}-{self.end_time})"

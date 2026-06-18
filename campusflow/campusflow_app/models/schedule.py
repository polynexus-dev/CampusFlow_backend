from django.db import models
from .department import Department
from .course import Course
from django.contrib.auth.models import User
from .classroom import Classroom


# Schedule Model (linking courses, faculty, and classrooms for lectures) — scoped per tenant schema
class Schedule(models.Model):
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    faculty = models.ForeignKey(User, on_delete=models.CASCADE, related_name='scheduled_classes') # Profile handles role filtering
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='scheduled_lectures', null=True, blank=True)
    day_of_week = models.CharField(max_length=10, choices=[
        ('Monday', 'Monday'), ('Tuesday', 'Tuesday'), ('Wednesday', 'Wednesday'),
        ('Thursday', 'Thursday'), ('Friday', 'Friday'), ('Saturday', 'Saturday'), ('Sunday', 'Sunday')
    ])
    start_time = models.TimeField()
    end_time = models.TimeField()
    semester = models.CharField(max_length=50)
    academic_year = models.CharField(max_length=9) # e.g., "2024-2025"
    substitute_faculty = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='substituted_classes',
                                       help_text="The faculty currently assigned if different from original scheduled faculty.")

    class Meta:
        verbose_name = "Schedule"
        verbose_name_plural = "Schedules"
        unique_together = ('course', 'classroom', 'day_of_week', 'start_time') # Prevent overlapping schedules in same room

    def __str__(self):
        return f"{self.course.course_code} on {self.day_of_week} {self.start_time}-{self.end_time} at {self.classroom.name}"
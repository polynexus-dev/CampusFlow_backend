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
    # Structured replacement for the two free-text fields above. Added ahead of
    # the code that reads it so this busy table needs only one migration, not two.
    # Nothing reads `term` yet; the strings remain authoritative until backfilled.
    term = models.ForeignKey(
        "campusflow_app.Term", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="schedules",
        help_text="Academic term this schedule belongs to. Supersedes semester/academic_year.",
    )
    substitute_faculty = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='substituted_classes',
                                       help_text="The faculty currently assigned if different from original scheduled faculty.")
    # The three fields below back automatic timetable generation
    # (services/timetable_generation.py). Additive/nullable, same posture as
    # `term` above — existing manually-created rows are unaffected
    # (course_offering/generation_run null, is_draft defaults False i.e. "live").
    course_offering = models.ForeignKey(
        "campusflow_app.CourseOffering", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="schedules",
        help_text="Set when this row was produced by (or reconciled against) timetable generation, "
                   "which schedules against CourseOffering rather than bare Course.",
    )
    is_draft = models.BooleanField(
        default=False,
        help_text="True for a row produced by an unreviewed TimetableGenerationRun. Draft rows are "
                   "excluded from normal schedule views until the run is applied.",
    )
    generation_run = models.ForeignKey(
        "campusflow_app.TimetableGenerationRun", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="draft_schedules",
    )

    class Meta:
        verbose_name = "Schedule"
        verbose_name_plural = "Schedules"
        unique_together = ('course', 'classroom', 'day_of_week', 'start_time') # Prevent overlapping schedules in same room

    def __str__(self):
        return f"{self.course.course_code} on {self.day_of_week} {self.start_time}-{self.end_time} at {self.classroom.name}"
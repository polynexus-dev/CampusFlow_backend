"""
Course Offerings & Registration
===============================
The missing join the rest of the academic spine has been waiting on. Today,
"which students are taking this course" is answered by department alone:
`views/result.py`'s ExamClassStatsView counts `total_students =
StudentProfile.objects.filter(department=exam.department).count()` — "class
size" is the whole department, not the actual roster. Same pattern in
views/exam.py's student visibility filter and models/assignment.py's
notification fan-out.

A CourseOffering is (course x term x batch [x section]) — the concrete
instance of a course being taught once. A StudentCourseRegistration is a
student's enrollment in one. Once these exist, "who is in this course" is a
real query instead of a department-wide guess, and it is the thing credits,
SGPA and attendance rosters all key off going forward.
"""

from django.contrib.auth.models import User
from django.db import models
from django.db.models import Q

from .academics import Batch, Section, Term
from .course import Course
from .profile import StudentProfile


class CourseOffering(models.Model):
    """One concrete instance of a course being taught: this course, this term,
    this batch (optionally narrowed to one section)."""

    course = models.ForeignKey(Course, on_delete=models.PROTECT, related_name="offerings")
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="offerings")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="offerings")
    section = models.ForeignKey(
        Section, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="offerings",
        help_text="Null = open to the whole batch, e.g. an open elective spanning sections.",
    )
    faculty = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="course_offerings",
    )
    max_seats = models.PositiveSmallIntegerField(null=True, blank=True)
    credits_override = models.DecimalField(
        max_digits=4, decimal_places=1, null=True, blank=True,
        help_text="Rare per-offering deviation from course.credits — leave unset in the normal case.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Course Offering"
        verbose_name_plural = "Course Offerings"
        constraints = [
            models.UniqueConstraint(
                fields=["course", "term", "section"],
                name="uniq_offering_course_term_section",
            ),
            # Postgres treats NULLs as distinct, so the constraint above does
            # NOT stop two batch-wide (section=None) offerings of the same
            # course in one term. This closes that gap explicitly.
            models.UniqueConstraint(
                fields=["course", "term", "batch"], condition=Q(section__isnull=True),
                name="uniq_batchwide_offering",
            ),
        ]
        indexes = [
            models.Index(fields=["term", "batch"]),
            models.Index(fields=["faculty", "term"]),
        ]

    def __str__(self):
        return f"{self.course.course_code} - {self.term} ({self.batch.name})"

    @property
    def effective_credits(self):
        return self.credits_override if self.credits_override is not None else self.course.credits


class StudentCourseRegistration(models.Model):
    """A student's enrollment in one CourseOffering."""

    STATUS_REGISTERED = "registered"
    STATUS_CHOICES = [
        (STATUS_REGISTERED, "Registered"),
        ("dropped", "Dropped"),
        ("withdrawn", "Withdrawn"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("detained", "Detained (attendance)"),
    ]
    ATTEMPT_REGULAR = "regular"
    ATTEMPT_CHOICES = [
        (ATTEMPT_REGULAR, "Regular"),
        ("supplementary", "Supplementary"),
        ("improvement", "Improvement"),
        ("repeat", "Repeat / Re-registration"),
    ]

    student = models.ForeignKey(
        StudentProfile, on_delete=models.CASCADE, related_name="course_registrations",
    )
    offering = models.ForeignKey(
        CourseOffering, on_delete=models.PROTECT, related_name="registrations",
    )
    # Denormalised from offering.term — every report filters on term, and this
    # avoids a join for the common case. Kept consistent because it is set
    # once at creation from offering.term and offerings never change term.
    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="registrations")
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_REGISTERED)
    attempt_type = models.CharField(max_length=15, choices=ATTEMPT_CHOICES, default=ATTEMPT_REGULAR)
    attempt_number = models.PositiveSmallIntegerField(
        default=1, help_text="1 for a first attempt; incremented for a supplementary/repeat re-registration.",
    )
    registered_at = models.DateTimeField(auto_now_add=True)
    registered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="registrations_created",
    )

    class Meta:
        verbose_name = "Student Course Registration"
        verbose_name_plural = "Student Course Registrations"
        constraints = [
            # Without attempt_number in the key, a student could never
            # re-register for a course they failed — the entire supplementary
            # exam workflow depends on this being part of the uniqueness key,
            # not just (student, offering).
            models.UniqueConstraint(
                fields=["student", "offering", "attempt_number"],
                name="uniq_student_offering_attempt",
            ),
        ]
        indexes = [
            models.Index(fields=["term", "student"]),
            models.Index(fields=["offering", "status"]),
        ]

    def __str__(self):
        return f"{self.student.student_id} - {self.offering} (attempt {self.attempt_number})"

    def save(self, *args, **kwargs):
        # offering_id guard: if it's missing entirely, let the DB's own NOT
        # NULL constraint raise a clear IntegrityError rather than this
        # accessing self.offering and raising RelatedObjectDoesNotExist first.
        if not self.term_id and self.offering_id:
            self.term_id = self.offering.term_id
        super().save(*args, **kwargs)

"""
NBA indirect attainment — the survey half of Outcome-Based Education that
services/outcome_attainment.py's direct (exam-marks-derived) computation was
missing. NBA's SAR template recognises four indirect channels: course-exit,
programme-exit, employer, and alumni surveys, each asking respondents to rate
how well a Program Outcome was achieved on a 1-5 Likert scale.

Two models, mirroring the CO/PO shape already established in models/outcomes.py:
`OutcomeIndirectSurvey` is the campaign (which channel, which program/course,
which academic year); `OutcomeIndirectSurveyResponse` is one respondent's
rating of one Program Outcome. A response is scoped to a single PO per row
(not a JSON blob per respondent, unlike ScannedPaper.question_scores) because
survey volume is small enough that a normalized row lets
compute_program_outcome_indirect_attainment (services/outcome_attainment.py)
use plain ORM aggregation instead of parsing JSON per request.

`respondent_label` is free text rather than a User/StudentProfile FK: an
employer or alumnus filling in an employer/alumni survey has no system
account to key off of — the same reasoning CommitteeMembership.external_member_name
and AntiRaggingUndertaking.parent_guardian_name already use for this codebase's
other "the real-world signer may not be a system user" fields.
"""
from django.core.exceptions import ValidationError
from django.db import models

from .academics import AcademicYear, Program
from .course import Course
from .outcomes import ProgramOutcome


class OutcomeIndirectSurvey(models.Model):
    TYPE_COURSE_EXIT = "course_exit"
    TYPE_PROGRAMME_EXIT = "programme_exit"
    TYPE_EMPLOYER = "employer"
    TYPE_ALUMNI = "alumni"
    TYPE_CHOICES = [
        (TYPE_COURSE_EXIT, "Course-Exit Survey"),
        (TYPE_PROGRAMME_EXIT, "Programme-Exit Survey"),
        (TYPE_EMPLOYER, "Employer Survey"),
        (TYPE_ALUMNI, "Alumni Survey"),
    ]

    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="indirect_surveys")
    course = models.ForeignKey(
        Course, on_delete=models.CASCADE, null=True, blank=True, related_name="indirect_surveys",
        help_text="Required for course-exit surveys; must be left blank for the other three "
                   "programme-level channels.",
    )
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="indirect_surveys")
    survey_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    is_open = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Outcome Indirect Survey"
        verbose_name_plural = "Outcome Indirect Surveys"
        ordering = ["-academic_year__start_date", "survey_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "course", "academic_year", "survey_type"],
                name="uniq_indirect_survey_per_scope",
            ),
        ]

    def clean(self):
        if self.survey_type == self.TYPE_COURSE_EXIT and not self.course_id:
            raise ValidationError("Course-exit surveys must specify a course.")
        if self.survey_type != self.TYPE_COURSE_EXIT and self.course_id:
            raise ValidationError("Only course-exit surveys may specify a course.")

    def __str__(self):
        scope = self.course.course_code if self.course_id else self.program.code
        return f"{self.get_survey_type_display()} — {scope} ({self.academic_year})"


class OutcomeIndirectSurveyResponse(models.Model):
    survey = models.ForeignKey(OutcomeIndirectSurvey, on_delete=models.CASCADE, related_name="responses")
    program_outcome = models.ForeignKey(
        ProgramOutcome, on_delete=models.CASCADE, related_name="indirect_survey_responses",
    )
    respondent_label = models.CharField(
        max_length=255, blank=True,
        help_text="Free text — e.g. an alumni/employer name or an anonymised roll number.",
    )
    rating = models.PositiveSmallIntegerField(
        choices=[(i, str(i)) for i in range(1, 6)],
        help_text="1-5 Likert-scale rating of how well this Program Outcome was achieved.",
    )
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Outcome Indirect Survey Response"
        verbose_name_plural = "Outcome Indirect Survey Responses"
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.survey} — {self.program_outcome.code}: {self.rating}/5"

"""
AQAR/SSR content-completeness — the remaining gaps in NAAC's two flagship
reports (#1 AQAR, #2 SSR/DVV), which draw from the same document generator
(services/naac_ssr_export.py). Four new models, each closing one named gap:

- FacultyResearchOutput replaces the single generic "faculty publication
  link" EvidenceItem.linked_object_type pointer (see models/compliance.py's
  EvidenceItem docstring) with real per-record publications/grants/patents —
  still attachable as NAAC evidence via that same generic pointer if an IQAC
  coordinator wants to cite one against a specific criterion.
- StudentFeedback mirrors CommitteeComplaint's status/action_taken/
  resolution_date shape (models/statutory_committee.py) — the same
  "received -> action taken -> closed" lifecycle, applied to feedback
  instead of a grievance.
- InstitutionalEvent is the source deck's own top recommendation ("log
  events, committees and evidence as they happen"). It has no evidence
  fields of its own by design: EvidenceItem's existing generic
  linked_object_type/linked_object_id pointer already lets one be cited as
  NAAC evidence against a criterion — "doubles as evidence once linked
  back", not a second evidence concept to maintain.
- AccreditationSubmission covers IIQA and DVV clarification with the exact
  same draft/submitted/signed_off state machine EvidenceItem already uses
  (same status choices, same submit()/sign_off() shape) — a new model
  because IIQA/DVV content (a query + a response, or a standalone annual
  submission) doesn't fit EvidenceItem's criterion+file shape, but the
  *workflow* is deliberately not reinvented.

The fifth AQAR/SSR gap (5-year audited financials) needs no new model at
all — see ComplianceCertificate.financial_year in models/compliance.py and
AuditedFinancialsCoverageView in views/aqar_ssr.py.
"""
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone

from .course import Course
from .department import Department
from .finance import FinancialYear
from .profile import StudentProfile, TeachingStaffProfile


class FacultyResearchOutput(models.Model):
    TYPE_PUBLICATION = "publication"
    TYPE_GRANT = "grant"
    TYPE_PATENT = "patent"
    TYPE_CHOICES = [
        (TYPE_PUBLICATION, "Publication"),
        (TYPE_GRANT, "Research Grant"),
        (TYPE_PATENT, "Patent"),
    ]

    faculty = models.ForeignKey(TeachingStaffProfile, on_delete=models.CASCADE, related_name="research_outputs")
    financial_year = models.ForeignKey(FinancialYear, on_delete=models.PROTECT, related_name="faculty_research_outputs")
    output_type = models.CharField(max_length=15, choices=TYPE_CHOICES)
    title = models.CharField(max_length=500)

    # Publication-specific (blank for grant/patent rows).
    journal_or_venue = models.CharField(max_length=255, blank=True)
    is_peer_reviewed = models.BooleanField(default=False)
    doi_or_url = models.CharField(max_length=500, blank=True)

    # Grant-specific.
    funding_agency = models.CharField(max_length=255, blank=True)
    grant_amount_lakhs = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    # Patent-specific.
    PATENT_FILED = "filed"
    PATENT_PUBLISHED = "published"
    PATENT_GRANTED = "granted"
    PATENT_STATUS_CHOICES = [
        (PATENT_FILED, "Filed"), (PATENT_PUBLISHED, "Published"), (PATENT_GRANTED, "Granted"),
    ]
    patent_number = models.CharField(max_length=100, blank=True)
    patent_status = models.CharField(max_length=15, choices=PATENT_STATUS_CHOICES, blank=True)

    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Faculty Research Output"
        verbose_name_plural = "Faculty Research Outputs"
        ordering = ["-financial_year__start_date", "faculty__employee_id"]

    def __str__(self):
        return f"{self.faculty.employee_id} — {self.get_output_type_display()}: {self.title[:60]}"


class StudentFeedback(models.Model):
    STATUS_RECEIVED = "received"
    STATUS_UNDER_REVIEW = "under_review"
    STATUS_ACTION_TAKEN = "action_taken"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_RECEIVED, "Received"),
        (STATUS_UNDER_REVIEW, "Under Review"),
        (STATUS_ACTION_TAKEN, "Action Taken"),
        (STATUS_CLOSED, "Closed"),
    ]

    student = models.ForeignKey(
        StudentProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="feedback_submissions",
        help_text="Nullable for anonymous feedback — same reasoning as CommitteeComplaint.complainant.",
    )
    is_anonymous = models.BooleanField(default=False)
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_feedback",
    )
    course = models.ForeignKey(
        Course, on_delete=models.SET_NULL, null=True, blank=True, related_name="student_feedback",
    )
    financial_year = models.ForeignKey(FinancialYear, on_delete=models.CASCADE, related_name="student_feedback")
    category = models.CharField(max_length=100, blank=True, help_text='e.g. "Curriculum", "Faculty", "Infrastructure".')
    feedback_text = models.TextField()
    filed_date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_RECEIVED)
    action_taken = models.TextField(blank=True)
    action_taken_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Student Feedback"
        verbose_name_plural = "Student Feedback"
        ordering = ["-filed_date"]

    def __str__(self):
        pk_val = getattr(self, "pk", None) or "Unsaved"
        return f"Feedback #{pk_val} — {self.get_status_display()}"

    def record_action(self, action_text):
        self.action_taken = action_text
        self.action_taken_date = timezone.localdate()
        self.status = self.STATUS_ACTION_TAKEN
        self.save(update_fields=["action_taken", "action_taken_date", "status", "updated_at"])


class InstitutionalEvent(models.Model):
    """Logged as it happens, per the source deck's own top recommendation.
    Deliberately carries no file/evidence field of its own — attach one via
    EvidenceItem(linked_object_type='InstitutionalEvent', linked_object_id=...)
    against whichever criterion it's cited as evidence for, reusing the
    existing generic pointer instead of a parallel evidence mechanism."""

    title = models.CharField(max_length=255)
    event_type = models.CharField(
        max_length=100, blank=True,
        help_text='Free text, e.g. "Workshop", "Extension Activity", "Guest Lecture", "Cultural Fest" — '
                   "NAAC's own event categories are numerous and occasionally revised.",
    )
    department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="institutional_events",
        help_text="Blank for institution-wide events.",
    )
    financial_year = models.ForeignKey(FinancialYear, on_delete=models.CASCADE, related_name="institutional_events")
    event_date = models.DateField()
    description = models.TextField(blank=True)
    participants_count = models.PositiveIntegerField(default=0)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Institutional Event"
        verbose_name_plural = "Institutional Events"
        ordering = ["-event_date"]

    def __str__(self):
        return f"{self.title} ({self.event_date})"


class AccreditationSubmission(models.Model):
    """IIQA (annual eligibility submission, one per cycle) and DVV
    clarifications (NAAC's Data Validation & Verification queries against a
    submitted SSR), sharing EvidenceItem's exact draft/submitted/signed_off
    workflow — see this module's docstring for why that's a new model
    rather than reusing EvidenceItem's table directly."""

    TYPE_IIQA = "iiqa"
    TYPE_DVV_CLARIFICATION = "dvv_clarification"
    TYPE_CHOICES = [
        (TYPE_IIQA, "IIQA"),
        (TYPE_DVV_CLARIFICATION, "DVV Clarification"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_SIGNED_OFF = "signed_off"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_SIGNED_OFF, "Signed Off"),
    ]

    submission_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    financial_year = models.ForeignKey(FinancialYear, on_delete=models.CASCADE, related_name="accreditation_submissions")
    query_text = models.TextField(
        blank=True, help_text="DVV clarifications only: the query/objection raised by NAAC's DVV team.",
    )
    content = models.TextField(
        blank=True, help_text="The IIQA submission content, or the IQAC's clarification response for a DVV query.",
    )
    file = models.FileField(upload_to="accreditation_submissions/", blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    prepared_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    submitted_at = models.DateTimeField(null=True, blank=True)
    signed_off_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="signed_off_accreditation_submissions",
    )
    signed_off_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Accreditation Submission"
        verbose_name_plural = "Accreditation Submissions"
        ordering = ["-financial_year__start_date", "submission_type"]

    def __str__(self):
        return f"{self.get_submission_type_display()} — {self.financial_year.label} [{self.status}]"

    def submit(self):
        self.status = self.STATUS_SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at"])

    def sign_off(self, by_user):
        self.status = self.STATUS_SIGNED_OFF
        self.signed_off_by = by_user
        self.signed_off_at = timezone.now()
        self.save(update_fields=["status", "signed_off_by", "signed_off_at"])

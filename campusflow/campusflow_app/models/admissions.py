"""
campusflow_app/models/admissions.py

The pre-admission pipeline this codebase was missing entirely: a Lead
(prospective student, not yet a User/StudentProfile) progresses
Inquiry -> Contacted -> Application Submitted -> Admitted -> Enrolled, with
a Rejected/Withdrawn branch off any active stage. Converting an Admitted
Lead into a real StudentProfile reuses the same primitives
AdminEnrollStudentView already uses (see views/admissions.py) rather than
duplicating that account-creation logic from scratch.

priority_score/priority_tier are a rule-based (not ML) heuristic — see
services/lead_scoring.py for why, and for the scoring logic itself. Unlike
StudentRiskScore (a nightly-cron cached table over hundreds of students),
a Lead's signals are cheap to compute, so these fields are recomputed
synchronously and explicitly via recompute_priority_score(), called by the
views after any state-changing action — not on a schedule.
"""

from django.conf import settings
from django.db import models
from django.utils import timezone

from .department import Department


class Lead(models.Model):
    SOURCE_WEBSITE = "website"
    SOURCE_REFERRAL = "referral"
    SOURCE_WALK_IN = "walk_in"
    SOURCE_AGENT = "agent"
    SOURCE_EVENT = "event"
    SOURCE_OTHER = "other"
    SOURCE_CHOICES = [
        (SOURCE_WEBSITE, "Website"),
        (SOURCE_REFERRAL, "Referral"),
        (SOURCE_WALK_IN, "Walk-in"),
        (SOURCE_AGENT, "Agent/Consultant"),
        (SOURCE_EVENT, "Education Fair/Event"),
        (SOURCE_OTHER, "Other"),
    ]

    STATUS_INQUIRY = "inquiry"
    STATUS_CONTACTED = "contacted"
    STATUS_APPLICATION_SUBMITTED = "application_submitted"
    STATUS_ADMITTED = "admitted"
    STATUS_ENROLLED = "enrolled"
    STATUS_REJECTED = "rejected"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [
        (STATUS_INQUIRY, "Inquiry"),
        (STATUS_CONTACTED, "Contacted"),
        (STATUS_APPLICATION_SUBMITTED, "Application Submitted"),
        (STATUS_ADMITTED, "Admitted"),
        (STATUS_ENROLLED, "Enrolled"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_WITHDRAWN, "Withdrawn"),
    ]
    # Leads still being worked — the only ones a priority score means anything for.
    ACTIVE_STATUSES = {STATUS_INQUIRY, STATUS_CONTACTED, STATUS_APPLICATION_SUBMITTED, STATUS_ADMITTED}

    TIER_HOT = "hot"
    TIER_WARM = "warm"
    TIER_COLD = "cold"
    TIER_CHOICES = [(TIER_HOT, "Hot"), (TIER_WARM, "Warm"), (TIER_COLD, "Cold")]

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100, blank=True)
    email = models.EmailField()
    phone = models.CharField(max_length=15, blank=True)

    interested_department = models.ForeignKey(
        Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="leads",
    )
    interested_program = models.ForeignKey(
        "campusflow_app.Program", on_delete=models.SET_NULL, null=True, blank=True, related_name="leads",
    )
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default=SOURCE_WEBSITE)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default=STATUS_INQUIRY)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )

    guardian_name = models.CharField(max_length=255, blank=True)
    guardian_email = models.EmailField(blank=True)
    guardian_phone = models.CharField(max_length=15, blank=True)

    notes = models.TextField(blank=True)

    priority_score = models.FloatField(default=0)
    priority_tier = models.CharField(max_length=10, choices=TIER_CHOICES, default=TIER_COLD)
    priority_computed_at = models.DateTimeField(null=True, blank=True)

    converted_student = models.ForeignKey(
        "campusflow_app.StudentProfile", on_delete=models.SET_NULL, null=True, blank=True, related_name="from_lead",
    )
    close_reason = models.TextField(blank=True, help_text="Rejection or withdrawal reason.")

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    contacted_at = models.DateTimeField(null=True, blank=True)
    admitted_at = models.DateTimeField(null=True, blank=True)
    enrolled_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "admission_leads"
        verbose_name = "Lead"
        verbose_name_plural = "Leads"
        ordering = ["-priority_score", "-created_at"]

    def __str__(self):
        return f"{self.first_name} {self.last_name} <{self.email}> [{self.status}]"

    def mark_contacted(self):
        if self.status != self.STATUS_INQUIRY:
            raise ValueError(f"Cannot mark contacted from status '{self.status}'.")
        self.status = self.STATUS_CONTACTED
        self.contacted_at = timezone.now()
        self.save(update_fields=["status", "contacted_at", "updated_at"])

    def submit_application(self):
        if self.status != self.STATUS_CONTACTED:
            raise ValueError(f"Cannot submit application from status '{self.status}'.")
        self.status = self.STATUS_APPLICATION_SUBMITTED
        self.save(update_fields=["status", "updated_at"])

    def admit(self):
        if self.status != self.STATUS_APPLICATION_SUBMITTED:
            raise ValueError(f"Cannot admit from status '{self.status}'.")
        self.status = self.STATUS_ADMITTED
        self.admitted_at = timezone.now()
        self.save(update_fields=["status", "admitted_at", "updated_at"])

    def close(self, outcome, reason=""):
        if outcome not in (self.STATUS_REJECTED, self.STATUS_WITHDRAWN):
            raise ValueError("outcome must be 'rejected' or 'withdrawn'.")
        if self.status not in self.ACTIVE_STATUSES:
            raise ValueError(f"Cannot close a lead already in status '{self.status}'.")
        self.status = outcome
        self.close_reason = reason
        self.closed_at = timezone.now()
        self.save(update_fields=["status", "close_reason", "closed_at", "updated_at"])

    def recompute_priority_score(self):
        from ..services.lead_scoring import compute_priority_score

        result = compute_priority_score(self)
        self.priority_score = result["priority_score"]
        self.priority_tier = result["priority_tier"]
        self.priority_computed_at = timezone.now()
        self.save(update_fields=["priority_score", "priority_tier", "priority_computed_at", "updated_at"])


class LeadActivity(models.Model):
    TYPE_CALL = "call"
    TYPE_EMAIL = "email"
    TYPE_MEETING = "meeting"
    TYPE_NOTE = "note"
    TYPE_STATUS_CHANGE = "status_change"
    TYPE_CHOICES = [
        (TYPE_CALL, "Call"),
        (TYPE_EMAIL, "Email"),
        (TYPE_MEETING, "Meeting"),
        (TYPE_NOTE, "Note"),
        (TYPE_STATUS_CHANGE, "Status Change"),
    ]

    lead = models.ForeignKey(Lead, on_delete=models.CASCADE, related_name="activities")
    activity_type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "admission_lead_activities"
        verbose_name = "Lead Activity"
        verbose_name_plural = "Lead Activities"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.get_activity_type_display()} on {self.lead} @ {self.created_at:%Y-%m-%d}"

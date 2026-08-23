"""
Statutory committee compliance — Anti-Ragging Committee (UGC Anti-Ragging
Regulations 2009), Internal Complaints Committee / ICC (Sexual Harassment of
Women at Workplace Act 2013, "POSH"), and Grievance Redressal Committee (UGC
Grievance Redressal Regulations 2018). All three share the same shape — a
committee with appointed members, a complaint register, and meeting minutes —
so one model set serves all three via `committee_type` rather than three
near-identical copies.

Confidentiality is load-bearing, not incidental: POSH Act Section 16 legally
requires ICC complaint details to stay confidential to the appointed
committee members only. Access is enforced by committee membership
(permissions.IsCommitteeMember), not by the base role hierarchy every other
permission check in this codebase uses — an HOD who isn't on the ICC must
not see POSH complaint details just because they outrank the complainant.
See views/statutory_committee.py for the enforcement and
CommitteeAnnualReportView for the aggregate-only reporting boundary.
"""
from django.contrib.auth.models import User
from django.db import models

from .academics import AcademicYear


class StatutoryCommittee(models.Model):
    TYPE_ANTI_RAGGING = "anti_ragging"
    TYPE_ICC_POSH = "icc_posh"
    TYPE_GRIEVANCE_REDRESSAL = "grievance_redressal"
    TYPE_CHOICES = [
        (TYPE_ANTI_RAGGING, "Anti-Ragging Committee"),
        (TYPE_ICC_POSH, "Internal Complaints Committee (POSH)"),
        (TYPE_GRIEVANCE_REDRESSAL, "Grievance Redressal Committee"),
    ]

    committee_type = models.CharField(max_length=25, choices=TYPE_CHOICES)
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.PROTECT, related_name="statutory_committees")
    formed_date = models.DateField()
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Statutory Committee"
        verbose_name_plural = "Statutory Committees"
        ordering = ["-academic_year__start_date", "committee_type"]
        constraints = [
            models.UniqueConstraint(
                fields=["committee_type", "academic_year"], name="uniq_committee_type_per_year",
            ),
        ]

    def __str__(self):
        return f"{self.get_committee_type_display()} — {self.academic_year}"


class CommitteeMembership(models.Model):
    """Who is actually appointed to a committee — the table
    IsCommitteeMember checks against. `user` is nullable because POSH
    mandates an external member (typically an NGO/social-work background
    person) who has no system account."""

    committee = models.ForeignKey(StatutoryCommittee, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(User, on_delete=models.CASCADE, null=True, blank=True, related_name="committee_memberships")
    external_member_name = models.CharField(max_length=255, blank=True)
    external_member_details = models.CharField(
        max_length=255, blank=True, help_text="e.g. affiliation, for the mandatory external member.",
    )
    role_in_committee = models.CharField(
        max_length=100, help_text='e.g. "Presiding Officer", "Student Representative", "External Member".',
    )
    appointed_date = models.DateField()

    class Meta:
        verbose_name = "Committee Membership"
        verbose_name_plural = "Committee Memberships"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(user__isnull=False, external_member_name="")
                    | models.Q(user__isnull=True) & ~models.Q(external_member_name="")
                ),
                name="committee_member_is_user_xor_external",
            ),
        ]

    def __str__(self):
        who = self.user.get_full_name() or self.user.username if self.user else self.external_member_name
        return f"{who} — {self.role_in_committee} ({self.committee})"


class CommitteeComplaint(models.Model):
    STATUS_RECEIVED = "received"
    STATUS_UNDER_INVESTIGATION = "under_investigation"
    STATUS_HEARING_SCHEDULED = "hearing_scheduled"
    STATUS_RESOLVED = "resolved"
    STATUS_CLOSED = "closed"
    STATUS_WITHDRAWN = "withdrawn"
    STATUS_CHOICES = [
        (STATUS_RECEIVED, "Received"),
        (STATUS_UNDER_INVESTIGATION, "Under Investigation"),
        (STATUS_HEARING_SCHEDULED, "Hearing Scheduled"),
        (STATUS_RESOLVED, "Resolved"),
        (STATUS_CLOSED, "Closed"),
        (STATUS_WITHDRAWN, "Withdrawn"),
    ]

    committee = models.ForeignKey(StatutoryCommittee, on_delete=models.PROTECT, related_name="complaints")
    complainant = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="filed_committee_complaints",
        help_text="Nullable for anonymous grievance submissions. POSH does not forbid capturing this — "
                   "it forbids disclosing it outside the committee, which is enforced by IsCommitteeMember, "
                   "not by omitting the field.",
    )
    is_anonymous = models.BooleanField(default=False)
    category = models.CharField(max_length=150, blank=True, help_text='e.g. "Verbal harassment", "Ragging — senior batch".')
    description = models.TextField()
    filed_date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default=STATUS_RECEIVED)
    action_taken = models.TextField(blank=True)
    resolution_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Committee Complaint"
        verbose_name_plural = "Committee Complaints"
        ordering = ["-filed_date"]

    def __str__(self):
        return f"Complaint #{self.id} — {self.committee} ({self.status})"


class CommitteeMeeting(models.Model):
    committee = models.ForeignKey(StatutoryCommittee, on_delete=models.CASCADE, related_name="meetings")
    meeting_date = models.DateField()
    attendees = models.ManyToManyField(CommitteeMembership, related_name="meetings_attended", blank=True)
    minutes_text = models.TextField(blank=True)
    action_items = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Committee Meeting"
        verbose_name_plural = "Committee Meetings"
        ordering = ["-meeting_date"]

    def __str__(self):
        return f"{self.committee} meeting on {self.meeting_date}"

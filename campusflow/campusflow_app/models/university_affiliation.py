"""
University affiliation & LIC (Local Inquiry Committee) — closes roadmap gap
#4. Built from scratch per the roadmap's own assessment: nothing in this
schema modeled a university's continuation-of-affiliation process before.
Four pieces, each reusing a shape already established elsewhere rather than
inventing new state machines:

- AffiliationApplication is the per-program-per-year overall application,
  including the LIC (Local Inquiry Committee) visit that decides it — same
  draft/submitted/approved/rejected shape as FeeRegulatingAuthoritySubmission
  and AccreditationSubmission, since this is exactly the same kind of
  "proposal to an external regulator" workflow.
- TeacherApprovalProposal is a per-faculty university approval, the same
  pending/approved/rejected + reviewed shape RevaluationRequest and
  ResultCorrectionRequest already use.
- FacultyWorkloadStatement and ReservationRosterEntry are flat per-year
  records (no approval workflow of their own — they're compiled *into* an
  AffiliationApplication's submission, not separately adjudicated), the
  same shape as SeatMatrix.

RESERVATION_CATEGORY_CHOICES is the standard UGC/state faculty-recruitment
roster category set (distinct from QUOTA_CHOICES in
models/dte_cet_admissions.py, which is Maharashtra's *student admission*
quota list — faculty reservation and student admission reservation are
governed by different rules and category groupings, so sharing one choices
list between them would be actively wrong, not just untidy).
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .academics import AcademicYear, Program
from .department import Department
from .profile import TeachingStaffProfile

RESERVATION_CATEGORY_CHOICES = [
    ("ur", "Unreserved (UR)"),
    ("sc", "SC"),
    ("st", "ST"),
    ("obc", "OBC"),
    ("ews", "EWS"),
    ("pwd", "PWD"),
]


class AffiliationApplication(models.Model):
    STATUS_DRAFT = "draft"
    STATUS_SUBMITTED = "submitted"
    STATUS_LIC_VISIT_SCHEDULED = "lic_visit_scheduled"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_SUBMITTED, "Submitted"),
        (STATUS_LIC_VISIT_SCHEDULED, "LIC Visit Scheduled"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    LIC_COMPLIANT = "compliant"
    LIC_CONDITIONAL = "conditional"
    LIC_NON_COMPLIANT = "non_compliant"
    LIC_STATUS_CHOICES = [
        (LIC_COMPLIANT, "Compliant"),
        (LIC_CONDITIONAL, "Conditional"),
        (LIC_NON_COMPLIANT, "Non-Compliant"),
    ]

    program = models.ForeignKey(Program, on_delete=models.CASCADE, related_name="affiliation_applications")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="affiliation_applications")
    status = models.CharField(max_length=25, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    university_reference_number = models.CharField(max_length=100, blank=True)

    lic_visit_date = models.DateField(null=True, blank=True)
    lic_committee_members = models.TextField(blank=True)
    lic_observations = models.TextField(blank=True)
    lic_compliance_status = models.CharField(max_length=15, choices=LIC_STATUS_CHOICES, blank=True)
    lic_report_file = models.FileField(upload_to="affiliation_lic_reports/", blank=True, null=True)

    remarks = models.TextField(blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Affiliation Application"
        verbose_name_plural = "Affiliation Applications"
        ordering = ["-academic_year__start_date", "program__code"]
        constraints = [
            models.UniqueConstraint(
                fields=["program", "academic_year"], name="uniq_affiliation_application_per_program_per_year",
            ),
        ]

    def __str__(self):
        return f"Affiliation {self.program.code} — {self.academic_year} [{self.status}]"

    def submit(self):
        self.status = self.STATUS_SUBMITTED
        self.submitted_at = timezone.now()
        self.save(update_fields=["status", "submitted_at", "updated_at"])

    def record_lic_visit(self, visit_date, committee_members="", observations="", compliance_status=""):
        self.status = self.STATUS_LIC_VISIT_SCHEDULED
        self.lic_visit_date = visit_date
        self.lic_committee_members = committee_members
        self.lic_observations = observations
        self.lic_compliance_status = compliance_status
        self.save(update_fields=[
            "status", "lic_visit_date", "lic_committee_members", "lic_observations",
            "lic_compliance_status", "updated_at",
        ])

    def record_decision(self, decision, university_reference_number="", remarks=""):
        if decision not in (self.STATUS_APPROVED, self.STATUS_REJECTED):
            raise ValueError("decision must be approved or rejected.")
        self.status = decision
        self.decided_at = timezone.now()
        if university_reference_number:
            self.university_reference_number = university_reference_number
        if remarks:
            self.remarks = remarks
        self.save(update_fields=[
            "status", "decided_at", "university_reference_number", "remarks", "updated_at",
        ])


class TeacherApprovalProposal(models.Model):
    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_APPROVED, "Approved"),
        (STATUS_REJECTED, "Rejected"),
    ]

    faculty = models.ForeignKey(TeachingStaffProfile, on_delete=models.CASCADE, related_name="approval_proposals")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="teacher_approval_proposals")
    program = models.ForeignKey(
        Program, on_delete=models.SET_NULL, null=True, blank=True, related_name="teacher_approval_proposals",
        help_text="Blank for a department-wide approval not tied to one program.",
    )
    designation_applied_for = models.CharField(max_length=100, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    university_approval_number = models.CharField(max_length=100, blank=True)
    remarks = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Teacher Approval Proposal"
        verbose_name_plural = "Teacher Approval Proposals"
        ordering = ["-submitted_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["faculty", "academic_year"], name="uniq_teacher_approval_per_faculty_per_year",
            ),
        ]

    def __str__(self):
        return f"{self.faculty.employee_id} — {self.academic_year} [{self.status}]"

    def record_decision(self, decision, university_approval_number="", remarks="", by_user=None):
        if decision not in (self.STATUS_APPROVED, self.STATUS_REJECTED):
            raise ValueError("decision must be approved or rejected.")
        self.status = decision
        self.reviewed_by = by_user
        self.reviewed_at = timezone.now()
        if university_approval_number:
            self.university_approval_number = university_approval_number
        if remarks:
            self.remarks = remarks
        self.save(update_fields=[
            "status", "reviewed_by", "reviewed_at", "university_approval_number", "remarks",
        ])


class FacultyWorkloadStatement(models.Model):
    """One faculty member's teaching-workload figures for one academic
    year's affiliation submission — compiled into AffiliationApplication,
    not separately adjudicated."""

    faculty = models.ForeignKey(TeachingStaffProfile, on_delete=models.CASCADE, related_name="workload_statements")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="workload_statements")
    teaching_hours_per_week = models.DecimalField(max_digits=5, decimal_places=2)
    courses_taught = models.TextField(
        blank=True, help_text='Free text summary, e.g. "CS301 Data Structures, CS402 Algorithms".',
    )
    administrative_hours_per_week = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Faculty Workload Statement"
        verbose_name_plural = "Faculty Workload Statements"
        ordering = ["-academic_year__start_date", "faculty__employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["faculty", "academic_year"], name="uniq_workload_statement_per_faculty_per_year",
            ),
        ]

    def __str__(self):
        return f"{self.faculty.employee_id} — {self.academic_year}: {self.teaching_hours_per_week}h/week"


class ReservationRosterEntry(models.Model):
    """One point in a department's faculty-recruitment reservation roster —
    the point-based roster system UGC/state rules require colleges to
    maintain and report to the affiliating university."""

    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="reservation_roster_entries")
    post_designation = models.CharField(max_length=100, help_text='e.g. "Assistant Professor".')
    roster_point_number = models.PositiveSmallIntegerField(help_text="This post's sequence number in the roster cycle.")
    category = models.CharField(max_length=10, choices=RESERVATION_CATEGORY_CHOICES)
    is_filled = models.BooleanField(default=False)
    filled_by = models.ForeignKey(
        TeachingStaffProfile, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
    )
    filled_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Reservation Roster Entry"
        verbose_name_plural = "Reservation Roster Entries"
        ordering = ["department__name", "post_designation", "roster_point_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["department", "post_designation", "roster_point_number"],
                name="uniq_roster_point_per_post",
            ),
        ]

    def __str__(self):
        return f"{self.department.code} {self.post_designation} #{self.roster_point_number} ({self.get_category_display()})"

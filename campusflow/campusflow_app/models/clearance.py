"""
Clearance (No-Dues) Workflow
============================
Sign-off from several offices/people before a student can be promoted, sit
for term-end exams, or receive a Transfer / No-Dues Certificate.

Shape (see Docs/clearance_flow_architecture.md):

    ClearanceDesk      an office (Library, Accounts, Hostel...) owned by a role.
    ClearanceFlow      a clearance process. College-wide flows are built by the
                       College Admin; department flows by that department's HOD.
      └ ClearanceFlowStep   who signs off, in which order: an office (desk), the
                            student's HOD, each of the student's subject teachers,
                            their section mentor, or one named person.
    ClearanceRequest   one student going through one flow for one cycle.
      └ ClearanceItem       one sign-off owed by one approver. A subject_faculty
                            step expands into one item per registered subject.
          └ ClearanceItemLog   what happened to it, by whom, when.

Clearing is always a manual decision by the approver; the dues data from the
fees/library/hostel modules is shown as a reference and never auto-clears.
"""

from django.contrib.auth.models import Group, User
from django.db import models
from django.db.models import Q

from .academics import AcademicYear, Program, Term
from .department import Department
from .offerings import CourseOffering
from .profile import StudentProfile

LINKED_MODULE_CHOICES = [
    ("fees", "Fees & Accounts"),
    ("library", "Library"),
    ("hostel", "Hostel"),
    ("none", "No linked data (manual review only)"),
]


class ClearanceDesk(models.Model):
    """
    One office that signs off as a step of a college-wide flow, e.g. Library,
    Hostel, Accounts, Exam Cell. Admin-managed per tenant since the list of
    offices differs by college.
    """
    LINKED_MODULE_CHOICES = LINKED_MODULE_CHOICES

    name = models.CharField(max_length=100)
    code = models.SlugField(max_length=50, unique=True)
    responsible_group = models.ForeignKey(
        Group, on_delete=models.PROTECT, related_name="clearance_desks",
        help_text="Which role acts on this desk's items, e.g. Librarian, Hostel Warden.",
    )
    linked_module = models.CharField(
        max_length=10, choices=LINKED_MODULE_CHOICES, default="none",
        help_text="Which existing model to pull reference dues data from for staff review.",
    )
    order = models.PositiveSmallIntegerField(default=0, help_text="Display sequence.")
    is_active = models.BooleanField(
        default=True,
        help_text="Inactive desks can't be added to flows but are kept for history.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Clearance Desk"
        verbose_name_plural = "Clearance Desks"
        ordering = ["order", "name"]

    def __str__(self):
        return self.name


class ClearanceSettings(models.Model):
    """
    One row per tenant schema: whether periodic clearance runs every semester
    or every academic year. Decides which cycle (term vs academic year) a
    periodic flow is launched for and checked against.
    """
    CADENCE_SEMESTER_END = "semester_end"
    CADENCE_YEAR_END = "year_end"
    CADENCE_CHOICES = [
        (CADENCE_SEMESTER_END, "Every Semester"),
        (CADENCE_YEAR_END, "Every Academic Year"),
    ]

    cadence = models.CharField(max_length=20, choices=CADENCE_CHOICES, default=CADENCE_SEMESTER_END)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Clearance Settings"
        verbose_name_plural = "Clearance Settings"

    def __str__(self):
        return f"Clearance cadence: {self.get_cadence_display()}"


class ClearanceFlow(models.Model):
    """A clearance process the admin (college-wide) or an HOD (own department) designs."""
    PURPOSE_PERIODIC = "periodic"
    PURPOSE_FINAL_EXIT = "final_exit"
    PURPOSE_OTHER = "other"
    PURPOSE_CHOICES = [
        (PURPOSE_PERIODIC, "Periodic (promotion / exam eligibility)"),
        (PURPOSE_FINAL_EXIT, "Final Exit (Transfer / No-Dues Certificate)"),
        (PURPOSE_OTHER, "Other (not used by any gate)"),
    ]

    MODE_PARALLEL = "parallel"
    MODE_SEQUENTIAL = "sequential"
    MODE_CHOICES = [
        (MODE_PARALLEL, "Parallel: every step receives it at once"),
        (MODE_SEQUENTIAL, "Sequential: a step receives it once the previous step is cleared"),
    ]

    STATUS_DRAFT = "draft"
    STATUS_PUBLISHED = "published"
    STATUS_CLOSED = "closed"
    STATUS_CHOICES = [
        (STATUS_DRAFT, "Draft"),
        (STATUS_PUBLISHED, "Published"),
        (STATUS_CLOSED, "Closed"),
    ]

    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, null=True, blank=True, related_name="clearance_flows",
        help_text="Blank = college-wide flow (College Admin). Set = that department's own flow (its HOD).",
    )
    purpose = models.CharField(max_length=15, choices=PURPOSE_CHOICES, default=PURPOSE_PERIODIC)
    approval_mode = models.CharField(max_length=12, choices=MODE_CHOICES, default=MODE_PARALLEL)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_DRAFT)
    allow_student_apply = models.BooleanField(
        default=False,
        help_text="Students may start this flow themselves (e.g. TC / No-Dues). Otherwise only Admin/HOD launch it.",
    )
    applies_to_programs = models.ManyToManyField(
        Program, blank=True, related_name="clearance_flows",
        help_text="Empty = every program in scope.",
    )
    applies_to_semesters = models.JSONField(
        default=list, blank=True, help_text="Curriculum semester numbers, e.g. [7, 8]. Empty = every semester.",
    )
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_flows_created",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Clearance Flow"
        verbose_name_plural = "Clearance Flows"
        ordering = ["department__name", "name"]

    def __str__(self):
        scope = self.department.code if self.department_id else "College"
        return f"{self.name} ({scope})"

    def applies_to(self, student):
        """Whether this flow's scope covers the given student."""
        if self.department_id and student.department_id != self.department_id:
            return False
        program_ids = [p.pk for p in self.applies_to_programs.all()]
        if program_ids and student.program_id not in program_ids:
            return False
        if self.applies_to_semesters and student.current_semester_number not in self.applies_to_semesters:
            return False
        return True


class ClearanceFlowStep(models.Model):
    """One stage of a flow and how its approver is found for each student."""
    APPROVER_DESK = "desk"
    APPROVER_DEPARTMENT_HOD = "department_hod"
    APPROVER_SUBJECT_FACULTY = "subject_faculty"
    APPROVER_SECTION_MENTOR = "section_mentor"
    APPROVER_SPECIFIC_USER = "specific_user"
    APPROVER_CHOICES = [
        (APPROVER_DESK, "Office / desk (a role, e.g. Librarian)"),
        (APPROVER_DEPARTMENT_HOD, "HOD of the student's department"),
        (APPROVER_SUBJECT_FACULTY, "Each subject teacher (one sign-off per registered subject)"),
        (APPROVER_SECTION_MENTOR, "Section mentor / class teacher"),
        (APPROVER_SPECIFIC_USER, "A specific person"),
    ]
    # Steps an HOD may put in a department flow. College offices belong in the
    # admin's college-wide flow, so a desk is never signed twice for one student.
    DEPARTMENT_APPROVER_TYPES = {
        APPROVER_DEPARTMENT_HOD, APPROVER_SUBJECT_FACULTY, APPROVER_SECTION_MENTOR, APPROVER_SPECIFIC_USER,
    }

    flow = models.ForeignKey(ClearanceFlow, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField(default=1, help_text="Steps with the same order run together.")
    title = models.CharField(max_length=150)
    instructions = models.TextField(blank=True, help_text="What the approver should verify before clearing.")
    approver_type = models.CharField(max_length=20, choices=APPROVER_CHOICES)
    desk = models.ForeignKey(
        ClearanceDesk, on_delete=models.PROTECT, null=True, blank=True, related_name="flow_steps",
    )
    approver_user = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_steps_assigned",
        help_text="Only for approver_type=specific_user.",
    )
    linked_module = models.CharField(
        max_length=10, choices=LINKED_MODULE_CHOICES, default="none",
        help_text="Dues data shown to the approver as reference. Defaults to the desk's own.",
    )

    class Meta:
        verbose_name = "Clearance Flow Step"
        verbose_name_plural = "Clearance Flow Steps"
        ordering = ["order", "id"]

    def __str__(self):
        return f"{self.flow.name} · {self.order}. {self.title}"


class ClearanceRequest(models.Model):
    """One student going through one flow for one cycle: a bundle of ClearanceItems."""
    CYCLE_PERIODIC = ClearanceFlow.PURPOSE_PERIODIC
    CYCLE_FINAL_EXIT = ClearanceFlow.PURPOSE_FINAL_EXIT
    CYCLE_OTHER = ClearanceFlow.PURPOSE_OTHER
    CYCLE_CHOICES = ClearanceFlow.PURPOSE_CHOICES

    STATUS_PENDING = "pending"
    STATUS_REJECTED = "rejected"
    STATUS_CLEARED = "cleared"
    STATUS_CHOICES = [
        (STATUS_PENDING, "In progress"),
        (STATUS_REJECTED, "Action needed (a step was rejected)"),
        (STATUS_CLEARED, "Cleared"),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="clearance_requests")
    flow = models.ForeignKey(
        ClearanceFlow, on_delete=models.PROTECT, null=True, blank=True, related_name="requests",
    )
    # Copied from flow.purpose so the gates (promotion, exams, certificates)
    # filter on one indexed column without a join.
    cycle_type = models.CharField(max_length=15, choices=CYCLE_CHOICES, default=CYCLE_PERIODIC)
    term = models.ForeignKey(
        Term, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_requests",
        help_text="Set for a periodic flow when the cadence is semester_end.",
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_requests",
        help_text="Set for a periodic flow when the cadence is year_end.",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    generated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_requests_generated",
        help_text="Who launched it (Admin/HOD) or applied (the student).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    # Once cleared: the student downloads the No-Dues PDF (QR -> verification_token,
    # set on first download) and submits it to their department, which receives it.
    verification_token = models.UUIDField(null=True, blank=True, unique=True, editable=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    submission_note = models.TextField(blank=True, default="")
    received_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_submissions_received",
    )
    received_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Clearance Request"
        verbose_name_plural = "Clearance Requests"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "flow", "term", "academic_year"],
                name="uniq_clearance_request_per_flow_cycle",
            ),
        ]
        indexes = [models.Index(fields=["student", "cycle_type"])]

    def __str__(self):
        return f"{self.student.student_id} · {self.flow.name if self.flow_id else self.cycle_type} ({self.status})"

    def recompute_status(self):
        """Re-derive status from item states. Any rejection wins; else all-cleared; else pending."""
        from django.utils import timezone

        item_statuses = list(self.items.values_list("status", flat=True))
        if any(s == ClearanceItem.STATUS_REJECTED for s in item_statuses):
            new_status = self.STATUS_REJECTED
        elif item_statuses and all(s == ClearanceItem.STATUS_CLEARED for s in item_statuses):
            new_status = self.STATUS_CLEARED
        elif not item_statuses and self.flow_id:
            # Nothing to sign (e.g. a subject step for a student with no
            # registered subjects): there is nothing outstanding.
            new_status = self.STATUS_CLEARED
        else:
            new_status = self.STATUS_PENDING

        self.status = new_status
        update_fields = ["status"]
        if new_status == self.STATUS_CLEARED and not self.completed_at:
            self.completed_at = timezone.now()
            update_fields.append("completed_at")
        elif new_status != self.STATUS_CLEARED and self.completed_at:
            self.completed_at = None
            update_fields.append("completed_at")
        self.save(update_fields=update_fields)
        return self.status


class ClearanceItem(models.Model):
    """One sign-off owed by one approver within a ClearanceRequest."""
    STATUS_WAITING = "waiting"
    STATUS_PENDING = "pending"
    STATUS_CLEARED = "cleared"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_WAITING, "Waiting for an earlier step"),
        (STATUS_PENDING, "Pending"),
        (STATUS_CLEARED, "Cleared"),
        (STATUS_REJECTED, "Rejected"),
    ]

    request = models.ForeignKey(ClearanceRequest, on_delete=models.CASCADE, related_name="items")
    step = models.ForeignKey(
        ClearanceFlowStep, on_delete=models.PROTECT, null=True, blank=True, related_name="items",
    )
    title = models.CharField(max_length=200, blank=True, help_text="e.g. 'Library' or 'DBMS: Prof. Rao'.")
    step_order = models.PositiveSmallIntegerField(default=1)
    desk = models.ForeignKey(
        ClearanceDesk, on_delete=models.PROTECT, null=True, blank=True, related_name="items",
    )
    offering = models.ForeignKey(
        CourseOffering, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_items",
        help_text="Set for a subject_faculty step: which subject this sign-off is for.",
    )
    approver = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_items_assigned",
        help_text="The person who signs this item. Blank for a desk item (any member of approver_group).",
    )
    approver_group = models.ForeignKey(
        Group, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_items_assigned",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    remarks = models.TextField(blank=True)
    student_note = models.TextField(blank=True, help_text="The student's note on their latest resubmission.")
    resubmit_count = models.PositiveSmallIntegerField(default=0)
    reference_snapshot = models.JSONField(
        blank=True, null=True,
        help_text="Dues/status data from the linked module, refreshed when the approver reviews it.",
    )
    cleared_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_items_actioned",
    )
    cleared_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Clearance Item"
        verbose_name_plural = "Clearance Items"
        ordering = ["step_order", "id"]
        constraints = [
            # Postgres treats NULLs as distinct, so one constraint per shape.
            models.UniqueConstraint(
                fields=["request", "step"], condition=Q(offering__isnull=True),
                name="uniq_clearance_item_per_step",
            ),
            models.UniqueConstraint(
                fields=["request", "step", "offering"], condition=Q(offering__isnull=False),
                name="uniq_clearance_item_per_step_subject",
            ),
        ]
        indexes = [
            models.Index(fields=["approver", "status"]),
            models.Index(fields=["approver_group", "status"]),
        ]

    def __str__(self):
        return f"{self.request} · {self.display_title} ({self.status})"

    @property
    def display_title(self):
        return self.title or (self.desk.name if self.desk_id else "Clearance")

    @property
    def linked_module(self):
        if self.step_id and self.step.linked_module != "none":
            return self.step.linked_module
        return self.desk.linked_module if self.desk_id else "none"


class ClearanceItemLog(models.Model):
    """Audit trail of one item: activated, cleared, rejected, resubmitted."""
    ACTION_ACTIVATED = "activated"
    ACTION_CLEARED = "cleared"
    ACTION_REJECTED = "rejected"
    ACTION_RESUBMITTED = "resubmitted"
    ACTION_CHOICES = [
        (ACTION_ACTIVATED, "Sent to approver"),
        (ACTION_CLEARED, "Cleared"),
        (ACTION_REJECTED, "Rejected"),
        (ACTION_RESUBMITTED, "Resubmitted by student"),
    ]

    item = models.ForeignKey(ClearanceItem, on_delete=models.CASCADE, related_name="logs")
    action = models.CharField(max_length=12, choices=ACTION_CHOICES)
    actor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self):
        return f"{self.item_id} {self.action}"

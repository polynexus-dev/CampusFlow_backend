"""
Clearance (No-Dues) Workflow
============================
Semester-end or year-end sign-off from multiple desks (library, hostel, fees,
academic department, ...) before a student can be promoted, sit for term-end
exams, or receive a final Transfer Certificate / No-Dues Certificate.

Cadence (semester_end vs year_end) and the desk list both vary by college, so
both are admin-configurable per tenant schema rather than hardcoded — see
ClearanceSettings and ClearanceDesk. Clearing itself is always a manual
sign-off by the desk's responsible staff group; services/clearance.py surfaces
the underlying dues data (fees/library/hostel) as a reference, it never
auto-clears.
"""

from django.contrib.auth.models import Group, User
from django.db import models

from .academics import AcademicYear, Term
from .profile import StudentProfile


class ClearanceDesk(models.Model):
    """
    One department/desk that must sign off on a clearance request, e.g.
    Library, Hostel, Fees, Exam Cell. Admin-managed per tenant since the exact
    list of desks differs by college.
    """
    LINKED_MODULE_CHOICES = [
        ("fees", "Fees & Accounts"),
        ("library", "Library"),
        ("hostel", "Hostel"),
        ("none", "No linked data (manual review only)"),
    ]

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
        help_text="Inactive desks are excluded from new clearance requests but kept for history.",
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
    One row per tenant schema — the college's clearance cadence. Fetched via
    get_or_create (see services/clearance.get_clearance_settings), the same
    lazy-singleton idiom used by the academic calendar's get_current_term.
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


class ClearanceRequest(models.Model):
    """One clearance cycle for one student — a bundle of per-desk ClearanceItems."""
    CYCLE_PERIODIC = "periodic"
    CYCLE_FINAL_EXIT = "final_exit"
    CYCLE_CHOICES = [
        (CYCLE_PERIODIC, "Periodic (promotion / exam eligibility)"),
        (CYCLE_FINAL_EXIT, "Final Exit (Transfer / No-Dues Certificate)"),
    ]

    STATUS_PENDING = "pending"
    STATUS_REJECTED = "rejected"
    STATUS_CLEARED = "cleared"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_REJECTED, "Rejected"),
        (STATUS_CLEARED, "Cleared"),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="clearance_requests")
    cycle_type = models.CharField(max_length=15, choices=CYCLE_CHOICES, default=CYCLE_PERIODIC)
    term = models.ForeignKey(
        Term, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_requests",
        help_text="Set when the tenant's cadence is semester_end.",
    )
    academic_year = models.ForeignKey(
        AcademicYear, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_requests",
        help_text="Set when the tenant's cadence is year_end, or as the final_exit anchor.",
    )
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    generated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_requests_generated",
        help_text="Blank when created by bulk system generation rather than a manual request.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Clearance Request"
        verbose_name_plural = "Clearance Requests"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "cycle_type", "term", "academic_year"],
                name="uniq_clearance_request_per_cycle",
            ),
        ]

    def __str__(self):
        return f"{self.student.student_id} · {self.get_cycle_type_display()} ({self.status})"

    def recompute_status(self):
        """Re-derive status from item states. Any rejection wins; else all-cleared; else pending."""
        from django.utils import timezone

        item_statuses = list(self.items.values_list("status", flat=True))
        if any(s == ClearanceItem.STATUS_REJECTED for s in item_statuses):
            new_status = self.STATUS_REJECTED
        elif item_statuses and all(s == ClearanceItem.STATUS_CLEARED for s in item_statuses):
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
    """One desk's sign-off within a ClearanceRequest."""
    STATUS_PENDING = "pending"
    STATUS_CLEARED = "cleared"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, "Pending"),
        (STATUS_CLEARED, "Cleared"),
        (STATUS_REJECTED, "Rejected"),
    ]

    request = models.ForeignKey(ClearanceRequest, on_delete=models.CASCADE, related_name="items")
    desk = models.ForeignKey(ClearanceDesk, on_delete=models.PROTECT, related_name="items")
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=STATUS_PENDING)
    remarks = models.TextField(blank=True)
    reference_snapshot = models.JSONField(
        blank=True, null=True,
        help_text="Dues/status data pulled from the linked module at review time, shown to staff as a reference.",
    )
    cleared_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="clearance_items_actioned",
    )
    cleared_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Clearance Item"
        verbose_name_plural = "Clearance Items"
        constraints = [
            models.UniqueConstraint(fields=["request", "desk"], name="uniq_clearance_item_per_desk"),
        ]
        ordering = ["desk__order"]

    def __str__(self):
        return f"{self.request} · {self.desk.name} ({self.status})"

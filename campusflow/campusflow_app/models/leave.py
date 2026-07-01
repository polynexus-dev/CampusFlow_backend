from django.db import models
from django.contrib.auth.models import User


class LeaveType(models.Model):
    """
    Configurable leave categories. Each college admin can define
    their own leave types with annual limits and role applicability.
    """
    name = models.CharField(max_length=100, help_text="e.g. Casual Leave, Sick Leave")
    code = models.CharField(max_length=10, unique=True, help_text="Short code, e.g. CL, SL, EL")
    max_days = models.PositiveIntegerField(default=12, help_text="Maximum days allowed per academic year.")
    is_paid = models.BooleanField(default=True, help_text="Whether this leave type is paid.")
    applicable_to = models.JSONField(
        default=list, blank=True,
        help_text="Roles this leave applies to. e.g. ['Faculty', 'Support Staff']. Empty = all staff."
    )
    carry_forward = models.BooleanField(
        default=False,
        help_text="Whether unused days can be carried to the next academic year."
    )
    description = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Leave Type"
        verbose_name_plural = "Leave Types"
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class LeaveBalance(models.Model):
    """
    Tracks per-user, per-leave-type allocation and usage for an academic year.
    """
    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='leave_balances'
    )
    leave_type = models.ForeignKey(
        LeaveType, on_delete=models.CASCADE,
        related_name='balances'
    )
    academic_year = models.CharField(
        max_length=9,
        help_text="Academic year, e.g. 2025-2026"
    )
    allocated = models.PositiveIntegerField(default=0, help_text="Total days allocated.")
    used = models.PositiveIntegerField(default=0, help_text="Days used so far.")
    carried = models.PositiveIntegerField(default=0, help_text="Days carried forward from previous year.")

    @property
    def remaining(self):
        return self.allocated + self.carried - self.used

    class Meta:
        verbose_name = "Leave Balance"
        verbose_name_plural = "Leave Balances"
        unique_together = ('user', 'leave_type', 'academic_year')

    def __str__(self):
        return f"{self.user.username} — {self.leave_type.code} ({self.academic_year}): {self.remaining} remaining"


class LeaveRequest(models.Model):
    """
    A leave application submitted by any staff member.
    Follows an approval workflow: Pending → Approved/Rejected/Cancelled.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE,
        related_name='leave_requests',
        help_text="The staff member applying for leave."
    )
    leave_type = models.ForeignKey(
        LeaveType, on_delete=models.CASCADE,
        related_name='requests'
    )
    start_date = models.DateField(help_text="First day of leave.")
    end_date = models.DateField(help_text="Last day of leave (inclusive).")
    reason = models.TextField(help_text="Reason for the leave request.")
    status = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default='pending'
    )
    approved_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='approved_leaves',
        help_text="The admin/HOD who approved or rejected this request."
    )
    rejection_reason = models.TextField(
        blank=True, null=True,
        help_text="Reason given if rejected."
    )
    applied_on = models.DateTimeField(auto_now_add=True)
    reviewed_on = models.DateTimeField(null=True, blank=True)

    @property
    def num_days(self):
        """Calculate the number of leave days (inclusive)."""
        if self.start_date and self.end_date:
            from datetime import date, datetime
            s_date = self.start_date
            e_date = self.end_date
            if isinstance(s_date, str):
                try:
                    s_date = datetime.strptime(s_date, "%Y-%m-%d").date()
                except ValueError:
                    pass
            if isinstance(e_date, str):
                try:
                    e_date = datetime.strptime(e_date, "%Y-%m-%d").date()
                except ValueError:
                    pass
            try:
                return (e_date - s_date).days + 1
            except TypeError:
                return 0
        return 0

    class Meta:
        verbose_name = "Leave Request"
        verbose_name_plural = "Leave Requests"
        ordering = ['-applied_on']

    def __str__(self):
        return f"{self.user.username} — {self.leave_type.code} ({self.start_date} to {self.end_date}) [{self.status}]"

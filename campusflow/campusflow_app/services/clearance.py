"""
Clearance workflow helpers — the eligibility rule and reference-data lookups
live here once so promotion, exam eligibility, and the certificate endpoint
never re-implement them differently.
"""

from django.db import transaction

from ..models.clearance import ClearanceDesk, ClearanceItem, ClearanceRequest, ClearanceSettings
from ..models.fees import StudentFeeInvoice
from ..models.hostel import HostelAllocation
from ..models.library import BookIssue
from ..models.profile import StudentProfile
from .academics import get_current_term


def get_clearance_settings():
    """Fetch (or lazily create) the tenant's clearance cadence."""
    settings_row, _ = ClearanceSettings.objects.get_or_create(pk=1)
    return settings_row


def get_reference_snapshot(student, desk):
    """
    Dues/status data for one desk, shown to the reviewing staff member as a
    reference. Never used to auto-clear — clearing is always the staff
    member's own decision (see Docs plan: "manual sign-off, data as reference").
    """
    if desk.linked_module == "fees":
        invoices = list(StudentFeeInvoice.objects.filter(student=student.user).exclude(status=StudentFeeInvoice.STATUS_PAID))
        return {
            "source": "fees",
            "unpaid_invoices": len(invoices),
            "amount_due": str(sum((inv.remaining_balance for inv in invoices), start=0)),
        }
    if desk.linked_module == "library":
        issues = list(BookIssue.objects.filter(student=student, status__in=["Issued", "Overdue"]))
        return {
            "source": "library",
            "outstanding_issues": len(issues),
            "total_fine": str(sum((issue.fine_amount for issue in issues), start=0)),
        }
    if desk.linked_module == "hostel":
        allocation = HostelAllocation.objects.filter(student=student, status="Allocated").first()
        return {
            "source": "hostel",
            "currently_allocated": bool(allocation),
            "room": allocation.room.room_number if allocation else None,
        }
    return {}


@transaction.atomic
def create_clearance_request(student, cycle_type, term=None, academic_year=None, generated_by=None):
    """
    Create one ClearanceRequest + one ClearanceItem per active desk for a
    student, if one doesn't already exist for this exact cycle.

    Returns (request, created).
    """
    request_obj, created = ClearanceRequest.objects.get_or_create(
        student=student, cycle_type=cycle_type, term=term, academic_year=academic_year,
        defaults={"generated_by": generated_by},
    )
    if created:
        for desk in ClearanceDesk.objects.filter(is_active=True):
            ClearanceItem.objects.create(
                request=request_obj, desk=desk,
                reference_snapshot=get_reference_snapshot(student, desk),
            )
    return request_obj, created


def bulk_generate_clearance_requests(term=None, academic_year=None, department_id=None, generated_by=None):
    """Create periodic ClearanceRequests for every active student matching the filter."""
    students = StudentProfile.objects.filter(academic_status="active")
    if department_id:
        students = students.filter(department_id=department_id)

    created_count = 0
    skipped_count = 0
    for student in students:
        _, created = create_clearance_request(
            student, ClearanceRequest.CYCLE_PERIODIC,
            term=term, academic_year=academic_year, generated_by=generated_by,
        )
        if created:
            created_count += 1
        else:
            skipped_count += 1
    return created_count, skipped_count


def is_student_cleared(student, cycle_type=ClearanceRequest.CYCLE_PERIODIC, term=None, academic_year=None):
    """
    The single eligibility rule every gate (promotion, exam list, certificate)
    calls. For cycle_type=periodic with neither term nor academic_year given,
    resolves the tenant's current cycle automatically from its cadence setting.

    A college that hasn't configured any active desks yet has not turned this
    feature on — nothing to clear, so nothing blocks (returns cleared=True).
    Otherwise, a student with no clearance request yet for the current cycle
    is NOT cleared: the process must have actually run and passed, silence is
    not consent.

    Returns (is_cleared, request_or_none).
    """
    if not ClearanceDesk.objects.filter(is_active=True).exists():
        return True, None

    if cycle_type == ClearanceRequest.CYCLE_PERIODIC and term is None and academic_year is None:
        current_term = get_current_term()
        settings_row = get_clearance_settings()
        if settings_row.cadence == ClearanceSettings.CADENCE_SEMESTER_END:
            term = current_term
        else:
            academic_year = current_term.academic_year if current_term else None

    request_obj = ClearanceRequest.objects.filter(
        student=student, cycle_type=cycle_type, term=term, academic_year=academic_year,
    ).order_by("-created_at").first()

    if request_obj is None:
        return False, None
    return request_obj.status == ClearanceRequest.STATUS_CLEARED, request_obj

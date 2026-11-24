"""
Clearance workflow rules, kept here once so the views, the gates (promotion,
exam eligibility, certificates) and the fee counter never re-implement them.

- Who approves an item is resolved when a request is created (see
  _resolve_items): a desk role, the student's HOD, each subject's teacher,
  the section mentor, or a named person. A missing person falls back to the
  student's HOD, so no item is left without someone who can act on it.
- In a sequential flow only the lowest unfinished step is "pending"; later
  steps wait (see activate_ready_items).
- A rejected item goes back to its approver once the student resubmits it.
- The gate: a student is cleared for a purpose when every published flow of
  that purpose that applies to them has a cleared request for the cycle.
"""

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from ..models.clearance import (
    ClearanceDesk, ClearanceFlow, ClearanceFlowStep, ClearanceItem, ClearanceItemLog,
    ClearanceRequest, ClearanceSettings,
)
from ..models.department import Department
from ..models.fees import StudentFeeInvoice
from ..models.hostel import HostelAllocation
from ..models.library import BookIssue
from ..models.offerings import CourseOffering, StudentCourseRegistration
from ..models.profile import StudentProfile
from .academics import get_current_term
from .notifications import notify_user

INACTIVE_REGISTRATION_STATUSES = ("dropped", "withdrawn")


# ─────────────────────────────────────────────────────────────────────────────
# Settings & cycle
# ─────────────────────────────────────────────────────────────────────────────

def get_clearance_settings():
    """Fetch (or lazily create) the tenant's clearance cadence."""
    settings_row, _ = ClearanceSettings.objects.get_or_create(pk=1)
    return settings_row


def resolve_cycle(purpose, term=None, academic_year=None):
    """
    The (term, academic_year) a request of this purpose is anchored to. Only
    periodic flows are cycle-bound: semester cadence -> term, year cadence ->
    academic year, defaulting to the current one. Other purposes are one-off.
    """
    if purpose != ClearanceFlow.PURPOSE_PERIODIC:
        return None, None
    cadence = get_clearance_settings().cadence
    if term is None and academic_year is None:
        term = get_current_term()
    if cadence == ClearanceSettings.CADENCE_SEMESTER_END:
        return term, None
    return None, (academic_year or (term.academic_year if term else None))


# ─────────────────────────────────────────────────────────────────────────────
# People
# ─────────────────────────────────────────────────────────────────────────────

def department_ids_led_by(user):
    """Departments this user is HOD of (Department.hod or their HOD profile)."""
    ids = set(Department.objects.filter(hod=user).values_list("id", flat=True))
    profile = getattr(user, "department_head_profile", None)
    if profile is not None and profile.department_id:
        ids.add(profile.department_id)
    return ids


def _hod_of(student):
    return student.department.hod if student.department_id and student.department.hod_id else None


def _user_role_names(user):
    from ..permissions import get_user_group, get_user_role_name

    return {name for name in (get_user_role_name(user), get_user_group(user)) if name}


def is_clearance_overseer(user):
    """College Admin or Principal: may see and act on every item."""
    from ..permissions import PRINCIPAL_ROLE, get_user_group, is_college_admin

    return is_college_admin(user) or get_user_group(user) == PRINCIPAL_ROLE


def is_clearance_approver(user):
    """
    Whether a flow routes sign-offs to this user: named on a step, owed an
    item, or holding the role of an active office. Such a user gets the
    clearance module even when their role doesn't (a lab assistant picked
    as a "specific person", a Store Manager office), else their inbox 403s
    and the student's request stalls on that step.
    """
    if not user.is_authenticated or getattr(user, "student_profile", None) is not None:
        return False
    return (
        ClearanceFlowStep.objects.filter(approver_user=user).exists()
        or ClearanceItem.objects.filter(approver=user).exists()
        or ClearanceDesk.objects.filter(is_active=True, responsible_group__name__in=_user_role_names(user)).exists()
    )


def items_assigned_to(user):
    """Every item routed to this user, directly or through their role."""
    return ClearanceItem.objects.filter(
        Q(approver=user) | Q(approver__isnull=True, approver_group__name__in=_user_role_names(user))
    )


def can_act_on_item(user, item):
    if is_clearance_overseer(user):
        return True
    if item.approver_id == user.id:
        return True
    if item.approver_id is None and item.approver_group_id and item.approver_group.name in _user_role_names(user):
        return True
    # The student's HOD can always step in for their own department's items.
    return item.request.student.department_id in department_ids_led_by(user)


# ─────────────────────────────────────────────────────────────────────────────
# Reference data
# ─────────────────────────────────────────────────────────────────────────────

def get_reference_snapshot(student, source):
    """
    Dues/status data shown to the approver as a reference. Never used to
    auto-clear. `source` is a module key ("fees"/"library"/"hostel") or
    anything with a linked_module attribute (desk, step, item).
    """
    module = source if isinstance(source, str) else getattr(source, "linked_module", "none")
    if module == "fees":
        invoices = list(StudentFeeInvoice.objects.filter(student=student.user).exclude(status=StudentFeeInvoice.STATUS_PAID))
        return {
            "source": "fees",
            "unpaid_invoices": len(invoices),
            "amount_due": str(sum((inv.remaining_balance for inv in invoices), start=0)),
        }
    if module == "library":
        issues = list(BookIssue.objects.filter(student=student, status__in=["Issued", "Overdue"]))
        return {
            "source": "library",
            "outstanding_issues": len(issues),
            "total_fine": str(sum((issue.fine_amount for issue in issues), start=0)),
        }
    if module == "hostel":
        allocation = HostelAllocation.objects.filter(student=student, status="Allocated").first()
        return {
            "source": "hostel",
            "currently_allocated": bool(allocation),
            "room": allocation.room.room_number if allocation else None,
        }
    return {}


def refresh_snapshot(item):
    item.reference_snapshot = get_reference_snapshot(item.request.student, item)
    item.save(update_fields=["reference_snapshot"])
    return item.reference_snapshot


# ─────────────────────────────────────────────────────────────────────────────
# Building requests
# ─────────────────────────────────────────────────────────────────────────────

def student_subject_offerings(student, term=None, academic_year=None):
    """
    The subjects a student is taking in the cycle: their course registrations,
    or, where a college doesn't record registrations, the active offerings for
    their batch/section.
    """
    if term is None and academic_year is None:
        term = get_current_term()
    registrations = StudentCourseRegistration.objects.filter(student=student).exclude(
        status__in=INACTIVE_REGISTRATION_STATUSES,
    )
    if term is not None:
        registrations = registrations.filter(term=term)
    elif academic_year is not None:
        registrations = registrations.filter(term__academic_year=academic_year)
    offerings = [
        reg.offering for reg in registrations.select_related("offering__course", "offering__faculty")
    ]
    if offerings or not student.batch_id:
        return list({o.pk: o for o in offerings}.values())

    fallback = CourseOffering.objects.filter(batch_id=student.batch_id, is_active=True).filter(
        Q(section__isnull=True) | Q(section_id=student.section_id)
    ).select_related("course", "faculty")
    if term is not None:
        fallback = fallback.filter(term=term)
    elif academic_year is not None:
        fallback = fallback.filter(term__academic_year=academic_year)
    else:
        return []
    return list(fallback)


def _resolve_items(step, student, term, academic_year):
    """The item(s) one step produces for one student, as dicts of field values."""
    base = {"step": step, "step_order": step.order, "title": step.title}
    hod = _hod_of(student)
    kind = step.approver_type

    if kind == ClearanceFlowStep.APPROVER_DESK:
        group = step.desk.responsible_group if step.desk_id else None
        return [{**base, "desk": step.desk, "approver_group": group}]
    if kind == ClearanceFlowStep.APPROVER_DEPARTMENT_HOD:
        return [{**base, "approver": hod}]
    if kind == ClearanceFlowStep.APPROVER_SECTION_MENTOR:
        mentor = student.section.mentor if student.section_id and student.section.mentor_id else None
        return [{**base, "approver": mentor or hod}]
    if kind == ClearanceFlowStep.APPROVER_SPECIFIC_USER:
        return [{**base, "approver": step.approver_user or hod}]
    if kind == ClearanceFlowStep.APPROVER_SUBJECT_FACULTY:
        rows = []
        for offering in student_subject_offerings(student, term, academic_year):
            teacher = offering.faculty
            label = f"{offering.course.course_code} {offering.course.course_name}"
            if teacher:
                label += f": {teacher.get_full_name() or teacher.username}"
            rows.append({**base, "title": f"{step.title} ({label})"[:200], "offering": offering, "approver": teacher or hod})
        return rows
    return []


def _step_module(step):
    if step.linked_module != "none":
        return step.linked_module
    return step.desk.linked_module if step.desk_id else "none"


def _log(item, action, actor=None, remarks=""):
    ClearanceItemLog.objects.create(item=item, action=action, actor=actor, remarks=remarks)


def _notify_approver(item):
    if item.approver_id:
        notify_user(
            item.approver, f"Clearance to review: {item.request.student.user.get_full_name() or item.request.student.student_id}",
            body=item.display_title, category="clearance_assigned",
            data={"item_id": item.id, "request_id": item.request_id},
        )


def activate_ready_items(request_obj, notify=True):
    """
    Move waiting items to pending where their turn has come. Parallel: all at
    once. Sequential: the lowest step order that still has unfinished items.
    """
    items = list(request_obj.items.select_related("approver", "request__student__user"))
    if not items:
        return []
    flow = request_obj.flow
    if flow is None or flow.approval_mode == ClearanceFlow.MODE_PARALLEL:
        ready = [i for i in items if i.status == ClearanceItem.STATUS_WAITING]
    else:
        unfinished_orders = [i.step_order for i in items if i.status != ClearanceItem.STATUS_CLEARED]
        if not unfinished_orders:
            return []
        current = min(unfinished_orders)
        ready = [i for i in items if i.status == ClearanceItem.STATUS_WAITING and i.step_order == current]

    for item in ready:
        item.status = ClearanceItem.STATUS_PENDING
        item.save(update_fields=["status"])
        _log(item, ClearanceItemLog.ACTION_ACTIVATED)
        if notify:
            _notify_approver(item)
    return ready


@transaction.atomic
def create_request_for_flow(flow, student, term=None, academic_year=None, generated_by=None, notify=True):
    """
    Create one ClearanceRequest for a student in a flow (and its items), unless
    one already exists for this cycle. Returns (request, created).
    """
    term, academic_year = resolve_cycle(flow.purpose, term, academic_year)
    existing = ClearanceRequest.objects.filter(
        student=student, flow=flow, term=term, academic_year=academic_year,
    ).first()
    if existing:
        return existing, False

    request_obj = ClearanceRequest.objects.create(
        student=student, flow=flow, cycle_type=flow.purpose,
        term=term, academic_year=academic_year, generated_by=generated_by,
    )
    for step in flow.steps.select_related("desk__responsible_group", "approver_user").all():
        for fields in _resolve_items(step, student, term, academic_year):
            ClearanceItem.objects.create(
                request=request_obj, status=ClearanceItem.STATUS_WAITING,
                reference_snapshot=get_reference_snapshot(student, _step_module(step)),
                **fields,
            )
    activate_ready_items(request_obj, notify=notify)
    request_obj.recompute_status()
    if notify:
        notify_user(
            student.user, f"Clearance started: {flow.name}",
            body="Track each sign-off under Clearance.", category="clearance_started",
            data={"request_id": request_obj.id},
        )
    return request_obj, True


def eligible_students(flow, department_id=None, program_id=None, semester=None, student_ids=None):
    """Active students a flow applies to, optionally narrowed further."""
    students = StudentProfile.objects.filter(academic_status="active").select_related(
        "user", "department__hod", "section__mentor",
    )
    if flow.department_id:
        students = students.filter(department_id=flow.department_id)
    elif department_id:
        students = students.filter(department_id=department_id)
    program_ids = list(flow.applies_to_programs.values_list("id", flat=True))
    if program_ids:
        students = students.filter(program_id__in=program_ids)
    if flow.applies_to_semesters:
        students = students.filter(current_semester_number__in=flow.applies_to_semesters)
    if program_id:
        students = students.filter(program_id=program_id)
    if semester:
        students = students.filter(current_semester_number=semester)
    if student_ids:
        students = students.filter(id__in=student_ids)
    return students


def launch_flow(flow, term=None, academic_year=None, generated_by=None, **filters):
    """Create requests for every eligible student. Returns (created, skipped)."""
    created_count = skipped_count = 0
    for student in eligible_students(flow, **filters):
        _, created = create_request_for_flow(
            flow, student, term=term, academic_year=academic_year, generated_by=generated_by,
        )
        if created:
            created_count += 1
        else:
            skipped_count += 1
    return created_count, skipped_count


# ─────────────────────────────────────────────────────────────────────────────
# Default flows (backward compatibility with the desk-only design)
# ─────────────────────────────────────────────────────────────────────────────

DEFAULT_FLOW_NAMES = {
    ClearanceFlow.PURPOSE_PERIODIC: "Periodic No-Dues",
    ClearanceFlow.PURPOSE_FINAL_EXIT: "Final Exit No-Dues",
    ClearanceFlow.PURPOSE_OTHER: "Clearance",
}


def ensure_default_flow(purpose):
    """
    The college-wide flow made of every active desk, used by callers written
    for the desk-only design (create_clearance_request, bulk generation, the
    legacy final-exit endpoint). Created and published on first use.
    """
    flow = ClearanceFlow.objects.filter(
        department__isnull=True, purpose=purpose, status=ClearanceFlow.STATUS_PUBLISHED,
    ).order_by("id").first()
    if flow:
        return flow
    flow = ClearanceFlow.objects.create(
        name=DEFAULT_FLOW_NAMES[purpose], purpose=purpose, status=ClearanceFlow.STATUS_PUBLISHED,
        approval_mode=ClearanceFlow.MODE_PARALLEL,
        allow_student_apply=(purpose == ClearanceFlow.PURPOSE_FINAL_EXIT),
    )
    for desk in ClearanceDesk.objects.filter(is_active=True):
        ClearanceFlowStep.objects.create(
            flow=flow, order=1, title=desk.name, approver_type=ClearanceFlowStep.APPROVER_DESK,
            desk=desk, linked_module=desk.linked_module,
        )
    return flow


def create_clearance_request(student, cycle_type, term=None, academic_year=None, generated_by=None, flow=None):
    """Create a request in `flow`, or in the college-wide default flow for cycle_type."""
    flow = flow or ensure_default_flow(cycle_type)
    return create_request_for_flow(
        flow, student, term=term, academic_year=academic_year, generated_by=generated_by, notify=False,
    )


def bulk_generate_clearance_requests(term=None, academic_year=None, department_id=None, generated_by=None):
    """Launch the default periodic flow for every active student (optionally one department)."""
    flow = ensure_default_flow(ClearanceFlow.PURPOSE_PERIODIC)
    return launch_flow(flow, term=term, academic_year=academic_year, generated_by=generated_by, department_id=department_id)


# ─────────────────────────────────────────────────────────────────────────────
# Acting on items
# ─────────────────────────────────────────────────────────────────────────────

class ClearanceActionError(Exception):
    """A user-facing refusal (wrong state, missing remarks)."""


@transaction.atomic
def act_on_item(item, user, decision, remarks=""):
    """Clear or reject one pending item, then advance the request."""
    item = ClearanceItem.objects.select_for_update().get(pk=item.pk)
    if item.status != ClearanceItem.STATUS_PENDING:
        state = "waiting for an earlier step" if item.status == ClearanceItem.STATUS_WAITING else f"already {item.status}"
        raise ClearanceActionError(f"This item is {state}.")
    if decision == ClearanceItem.STATUS_REJECTED and not remarks:
        raise ClearanceActionError("remarks is required when rejecting.")

    item.reference_snapshot = get_reference_snapshot(item.request.student, item)
    item.status = decision
    item.remarks = remarks
    item.cleared_by = user
    item.cleared_at = timezone.now()
    item.save(update_fields=["status", "remarks", "cleared_by", "cleared_at", "reference_snapshot"])
    _log(item, decision, actor=user, remarks=remarks)

    request_obj = item.request
    if decision == ClearanceItem.STATUS_CLEARED:
        activate_ready_items(request_obj)
    new_status = request_obj.recompute_status()

    student_user = request_obj.student.user
    verb = "approved" if decision == ClearanceItem.STATUS_CLEARED else "rejected"
    notify_user(
        student_user, f"{item.display_title} {verb}", body=remarks,
        category=f"clearance_{'cleared' if decision == ClearanceItem.STATUS_CLEARED else 'rejected'}",
        data={"request_id": request_obj.id, "item_id": item.id},
    )
    if new_status == ClearanceRequest.STATUS_CLEARED:
        flow_name = request_obj.flow.name if request_obj.flow_id else "Clearance"
        notify_user(
            student_user, f"{flow_name} completed", body="Every step has cleared your request.",
            category="clearance_completed", data={"request_id": request_obj.id},
        )
    return item


@transaction.atomic
def resubmit_item(item, user, note=""):
    """The student sends a rejected item back to its approver after fixing it."""
    item = ClearanceItem.objects.select_for_update().get(pk=item.pk)
    if item.status != ClearanceItem.STATUS_REJECTED:
        raise ClearanceActionError("Only a rejected item can be resubmitted.")
    item.status = ClearanceItem.STATUS_PENDING
    item.student_note = note
    item.resubmit_count += 1
    item.cleared_by = None
    item.cleared_at = None
    item.save(update_fields=["status", "student_note", "resubmit_count", "cleared_by", "cleared_at"])
    _log(item, ClearanceItemLog.ACTION_RESUBMITTED, actor=user, remarks=note)
    item.request.recompute_status()
    _notify_approver(item)
    return item


# ─────────────────────────────────────────────────────────────────────────────
# The gate
# ─────────────────────────────────────────────────────────────────────────────

def applicable_flows(student, purpose):
    """Published flows of this purpose whose scope covers the student."""
    flows = ClearanceFlow.objects.filter(
        purpose=purpose, status=ClearanceFlow.STATUS_PUBLISHED,
    ).filter(Q(department__isnull=True) | Q(department_id=student.department_id)).prefetch_related("applies_to_programs")
    return [flow for flow in flows if flow.applies_to(student)]


def clearance_status(student, purpose=ClearanceFlow.PURPOSE_PERIODIC, term=None, academic_year=None):
    """
    Returns (is_cleared, requests, missing_flows): the latest request per
    applicable flow for the cycle, and the flows the student has no request in
    yet. No applicable flows = the college hasn't switched this on = cleared.
    A flow with no request is NOT cleared: the process must have run and passed.
    """
    term, academic_year = resolve_cycle(purpose, term, academic_year)
    requests, missing = [], []
    for flow in applicable_flows(student, purpose):
        qs = ClearanceRequest.objects.filter(student=student, flow=flow)
        if purpose == ClearanceFlow.PURPOSE_PERIODIC:
            qs = qs.filter(term=term, academic_year=academic_year)
        request_obj = qs.order_by("-created_at").first()
        if request_obj is None:
            missing.append(flow)
        else:
            requests.append(request_obj)
    cleared = not missing and all(r.status == ClearanceRequest.STATUS_CLEARED for r in requests)
    return cleared, requests, missing


def is_student_cleared(student, cycle_type=ClearanceFlow.PURPOSE_PERIODIC, term=None, academic_year=None):
    """
    The single eligibility rule every gate (promotion, exam list, certificate,
    migration, convocation) calls. Returns (is_cleared, request_or_none): the
    first request still blocking the student, else the most recent one.
    """
    cleared, requests, _ = clearance_status(student, cycle_type, term, academic_year)
    blocking = [r for r in requests if r.status != ClearanceRequest.STATUS_CLEARED]
    if blocking:
        return cleared, blocking[0]
    return cleared, (max(requests, key=lambda r: r.created_at) if requests else None)


# ─────────────────────────────────────────────────────────────────────────────
# No-Dues PDF and submission to the department
# ─────────────────────────────────────────────────────────────────────────────

def clearance_verification_path(request_obj):
    """Public verify link (QR). Carries the schema so it resolves without login."""
    import uuid

    from django.db import connection

    if not request_obj.verification_token:
        request_obj.verification_token = uuid.uuid4()
        request_obj.save(update_fields=["verification_token"])
    return f"/api/clearance/verify/{connection.schema_name}/{request_obj.verification_token}/"


def clearance_pdf(request_obj, verify_url):
    """A4 No-Dues certificate for one fully cleared request: who signed each step and when."""
    import io
    from xml.sax.saxutils import escape

    from django.db import connection
    from reportlab.lib import colors
    from reportlab.lib.enums import TA_CENTER
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import cm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    from .certificates import _fmt_date, _logo_image, _qr_image, college_name

    student = request_obj.student
    user = student.user
    styles = getSampleStyleSheet()
    college = ParagraphStyle("college", parent=styles["Title"], fontSize=18, leading=22)
    address = ParagraphStyle("addr", parent=styles["Normal"], alignment=TA_CENTER, fontSize=9, textColor=colors.grey)
    title = ParagraphStyle("title", parent=styles["Heading1"], alignment=TA_CENTER, fontSize=15, spaceBefore=14, spaceAfter=4)
    sub = ParagraphStyle("sub", parent=styles["Normal"], alignment=TA_CENTER, fontSize=10, textColor=colors.HexColor("#1F3A5F"))
    body = ParagraphStyle("body", parent=styles["Normal"], fontSize=10.5, leading=16)
    cell = ParagraphStyle("cell", parent=styles["Normal"], fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=styles["Normal"], fontSize=8.5, textColor=colors.grey)

    flow_name = request_obj.flow.name if request_obj.flow_id else request_obj.get_cycle_type_display()
    cycle = " · ".join(x for x in (
        request_obj.academic_year.name if request_obj.academic_year_id else "",
        request_obj.term.name if request_obj.term_id else "",
    ) if x)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=2 * cm, rightMargin=2 * cm,
                            topMargin=1.6 * cm, bottomMargin=1.6 * cm, title=f"No-Dues Certificate - {student.student_id}")
    story = []
    logo = _logo_image(2.2, 2.2)
    if logo is not None:
        story.append(logo)
    story.append(Paragraph(escape(college_name()), college))
    tenant_address = getattr(connection.tenant, "address", "") or ""
    if tenant_address:
        story.append(Paragraph(escape(tenant_address), address))
    story.append(Table([[""]], colWidths=[17 * cm], style=TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 1.2, colors.HexColor("#1F3A5F")),
    ])))
    story.append(Paragraph("No-Dues Clearance Certificate", title))
    story.append(Paragraph(escape(flow_name + (f" ({cycle})" if cycle else "")), sub))
    story.append(Spacer(1, 0.5 * cm))

    details = [
        ("Student", user.get_full_name() or user.username),
        ("Student ID", student.student_id),
        ("Department", student.department.name if student.department_id else "-"),
        ("Program", student.program.name if getattr(student, "program_id", None) else "-"),
        ("Cleared on", _fmt_date(timezone.localtime(request_obj.completed_at).date()) if request_obj.completed_at else "-"),
    ]
    story.append(Table(
        [[Paragraph(f"<b>{escape(k)}</b>", cell), Paragraph(escape(str(v)), cell)] for k, v in details],
        colWidths=[4 * cm, 13 * cm],
        style=TableStyle([("BOTTOMPADDING", (0, 0), (-1, -1), 3)]),
    ))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        "This is to certify that the above student has no dues outstanding and every sign-off below has been cleared.",
        body,
    ))
    story.append(Spacer(1, 0.3 * cm))

    rows = [[Paragraph(f"<b>{h}</b>", cell) for h in ("#", "Sign-off", "Cleared by", "Date", "Remarks")]]
    items = request_obj.items.select_related("desk", "cleared_by").order_by("step_order", "id")
    for n, item in enumerate(items, start=1):
        cleared_by = (item.cleared_by.get_full_name() or item.cleared_by.username) if item.cleared_by_id else "-"
        rows.append([
            Paragraph(str(n), cell),
            Paragraph(escape(item.display_title), cell),
            Paragraph(escape(cleared_by), cell),
            Paragraph(_fmt_date(timezone.localtime(item.cleared_at).date()) if item.cleared_at else "-", cell),
            Paragraph(escape(item.remarks or ""), cell),
        ])
    story.append(Table(rows, colWidths=[0.8 * cm, 6.2 * cm, 3.8 * cm, 2.4 * cm, 3.8 * cm], repeatRows=1, style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E8EEF5")),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#C8D3E0")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ])))
    story.append(Spacer(1, 1.2 * cm))
    story.append(Table(
        [[_qr_image(verify_url, 2.6), Paragraph("<br/><br/><br/>Head of Department / Authorised Signatory", small)],
         [Paragraph("Scan to verify", small), ""]],
        colWidths=[8.5 * cm, 8.5 * cm],
        style=TableStyle([("ALIGN", (1, 0), (1, 0), "RIGHT"), ("VALIGN", (0, 0), (-1, -1), "BOTTOM")]),
    ))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        f"Generated by CampusNexus on {_fmt_date(timezone.localdate())}. Submit this to your department office.", small,
    ))
    doc.build(story)
    return buffer.getvalue()


def submit_to_department(request_obj, student_user, note=""):
    """The student hands their cleared No-Dues to their department; the HOD is notified."""
    if request_obj.status != ClearanceRequest.STATUS_CLEARED:
        raise ClearanceActionError("Finish every step before submitting your No-Dues to the department.")
    if request_obj.submitted_at:
        raise ClearanceActionError("Already submitted to your department.")
    request_obj.submitted_at = timezone.now()
    request_obj.submission_note = note
    request_obj.save(update_fields=["submitted_at", "submission_note"])
    hod = _hod_of(request_obj.student)
    if hod:
        notify_user(
            hod, f"No-Dues submitted: {student_user.get_full_name() or request_obj.student.student_id}",
            body=request_obj.flow.name if request_obj.flow_id else "Clearance",
            category="clearance_submitted", data={"request_id": request_obj.id},
        )
    return request_obj


def receive_submission(request_obj, receiver):
    """The department confirms it has the student's No-Dues; the student is notified."""
    if not request_obj.submitted_at:
        raise ClearanceActionError("The student has not submitted this yet.")
    if request_obj.received_at:
        raise ClearanceActionError("Already received.")
    request_obj.received_by = receiver
    request_obj.received_at = timezone.now()
    request_obj.save(update_fields=["received_by", "received_at"])
    notify_user(
        request_obj.student.user, "Your No-Dues was received by your department",
        body=request_obj.flow.name if request_obj.flow_id else "Clearance",
        category="clearance_received", data={"request_id": request_obj.id},
    )
    return request_obj

"""
Move desk-only clearance data into flows.

Before flows existed, every request got one item per active desk. Each
college's existing set-up becomes college-wide "Periodic No-Dues" and
"Final Exit No-Dues" flows (parallel, one step per active desk), and existing
requests and items are linked to them, so the gates (promotion, exams,
certificates) and in-progress requests behave exactly as before.
"""

from django.db import migrations

NAMES = {"periodic": "Periodic No-Dues", "final_exit": "Final Exit No-Dues"}


def forwards(apps, schema_editor):
    Desk = apps.get_model("campusflow_app", "ClearanceDesk")
    Flow = apps.get_model("campusflow_app", "ClearanceFlow")
    Step = apps.get_model("campusflow_app", "ClearanceFlowStep")
    Request = apps.get_model("campusflow_app", "ClearanceRequest")
    Item = apps.get_model("campusflow_app", "ClearanceItem")

    active_desks = list(Desk.objects.filter(is_active=True).order_by("order", "name"))
    purposes = set(Request.objects.values_list("cycle_type", flat=True))
    if active_desks:
        purposes |= {"periodic", "final_exit"}

    for purpose in sorted(purposes):
        if purpose not in NAMES:
            continue
        flow = Flow.objects.create(
            name=NAMES[purpose], purpose=purpose, approval_mode="parallel",
            # Published only where the old design was actually gating: some desk was active.
            status="published" if active_desks else "closed",
            allow_student_apply=(purpose == "final_exit"),
            description="Created automatically from the clearance desks set up before flows existed.",
        )
        step_by_desk = {}
        for desk in active_desks:
            step_by_desk[desk.id] = Step.objects.create(
                flow=flow, order=1, title=desk.name, approver_type="desk",
                desk=desk, linked_module=desk.linked_module,
            )
        Request.objects.filter(cycle_type=purpose, flow__isnull=True).update(flow=flow)
        for item in Item.objects.filter(request__flow=flow).select_related("desk"):
            item.step = step_by_desk.get(item.desk_id)  # inactive desks keep history without a step
            item.title = item.desk.name if item.desk_id else "Clearance"
            item.approver_group_id = item.desk.responsible_group_id if item.desk_id else None
            item.step_order = 1
            item.save(update_fields=["step", "title", "approver_group", "step_order"])


class Migration(migrations.Migration):
    dependencies = [
        ("campusflow_app", "0053_clearance_flows"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]

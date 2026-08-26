"""
Promote Class (year-end)
=========================
Bulk class->class promotion. A student's "class" is just two plain strings
on StudentProfile (current_semester_year, section_division) — there is no
separate Classroom/Section model — so promotion is a bulk field update,
snapshotted per student so a batch can be reverted within 7 days.

Guardian links, bus subscriptions, and fee invoices all key off the
student's User/StudentProfile id, never off these two fields, so they carry
over automatically without any extra code here.
"""

from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Department, StudentProfile, PromotionBatch, PromotionRecord
from ..permissions import IsSaaSOrCollegeAdmin
from ..services.clearance import is_student_cleared

REVERT_WINDOW = timedelta(days=7)


class PromoteClassView(APIView):
    """
    POST /api/students/promote/
    Payload: {
        department_id, from_semester_year, from_section_division, from_academic_year,
        to_semester_year, to_section_division, to_academic_year,
        decisions: [{student_id, decision: "promote"|"hold"|"exclude", notes?}]
    }
    Students in the from-class not listed in `decisions` default to "promote".
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    @transaction.atomic
    def post(self, request):
        data = request.data
        dept_id = data.get("department_id")
        from_year = data.get("from_semester_year")
        from_section = data.get("from_section_division", "")
        to_year = data.get("to_semester_year")
        to_section = data.get("to_section_division", "")

        if not dept_id or not from_year or not to_year:
            return Response(
                {"error": "department_id, from_semester_year, and to_semester_year are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            department = Department.objects.get(id=dept_id)
        except Department.DoesNotExist:
            return Response({"error": "Invalid department."}, status=status.HTTP_400_BAD_REQUEST)

        roster = StudentProfile.objects.filter(
            department=department, current_semester_year=from_year, section_division=from_section,
        )
        roster_ids = set(roster.values_list("id", flat=True))
        if not roster_ids:
            return Response({"error": "No students found in the from-class for this department."}, status=status.HTTP_400_BAD_REQUEST)

        decisions_payload = data.get("decisions", [])
        decision_map = {}
        for d in decisions_payload:
            student_id = d.get("student_id")
            if student_id not in roster_ids:
                return Response(
                    {"error": f"student_id {student_id} does not belong to the from-class roster."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            decision_map[student_id] = d

        # Clearance gate: a student being promoted must have a fully-cleared
        # periodic ClearanceRequest for the college's current cycle, unless an
        # admin explicitly overrides with a reason. Checked up front, before
        # any writes, since this view is already wrapped in one big
        # transaction.atomic() block and a plain early Response() here would
        # not roll back anything created earlier in this same call.
        override = bool(data.get("override"))
        override_reason = (data.get("override_reason") or "").strip()
        if override and not override_reason:
            return Response({"error": "override_reason is required when override is true."}, status=status.HTTP_400_BAD_REQUEST)

        blocked_student_ids = []
        for student in roster:
            decision_entry = decision_map.get(student.id, {})
            decision = decision_entry.get("decision", PromotionRecord.DECISION_PROMOTE)
            if decision != PromotionRecord.DECISION_PROMOTE:
                continue
            is_cleared, _ = is_student_cleared(student)
            if not is_cleared:
                blocked_student_ids.append(student.id)

        if blocked_student_ids and not override:
            return Response(
                {
                    "error": (
                        f"{len(blocked_student_ids)} student(s) do not have a cleared clearance "
                        "request for the current cycle and cannot be promoted. Resend with "
                        "override=true and an override_reason to promote them anyway."
                    ),
                    "blocked_student_ids": blocked_student_ids,
                },
                status=status.HTTP_409_CONFLICT,
            )

        batch = PromotionBatch.objects.create(
            department=department,
            from_semester_year=from_year, from_section_division=from_section,
            from_academic_year=data.get("from_academic_year", ""),
            to_semester_year=to_year, to_section_division=to_section,
            to_academic_year=data.get("to_academic_year", ""),
            performed_by=request.user,
        )

        counts = {"promote": 0, "hold": 0, "exclude": 0}
        for student in roster:
            decision_entry = decision_map.get(student.id, {})
            decision = decision_entry.get("decision", PromotionRecord.DECISION_PROMOTE)
            if decision not in counts:
                return Response({"error": f"Invalid decision '{decision}' for student {student.id}."}, status=status.HTTP_400_BAD_REQUEST)

            PromotionRecord.objects.create(
                batch=batch, student=student, decision=decision, notes=decision_entry.get("notes", ""),
                previous_semester_year=student.current_semester_year or "",
                previous_section_division=student.section_division or "",
                previous_batch_academic_year=student.batch_academic_year or "",
                previous_status=student.status or "",
                override_reason=override_reason if student.id in blocked_student_ids else "",
            )

            if decision == PromotionRecord.DECISION_PROMOTE:
                student.current_semester_year = to_year
                student.section_division = to_section
                if data.get("to_academic_year"):
                    student.batch_academic_year = data["to_academic_year"]
                student.save(update_fields=["current_semester_year", "section_division", "batch_academic_year"])
            elif decision == PromotionRecord.DECISION_EXCLUDE:
                student.status = "transferred"
                student.save(update_fields=["status"])
            # hold: no field changes

            counts[decision] += 1

        return Response({
            "batch_id": batch.id,
            "promoted_count": counts["promote"],
            "held_count": counts["hold"],
            "excluded_count": counts["exclude"],
        }, status=status.HTTP_201_CREATED)


class PromoteClassRevertView(APIView):
    """
    POST /api/students/promote/<batch_id>/revert/
    Only allowed within 7 days of the original promotion.
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    @transaction.atomic
    def post(self, request, batch_id):
        try:
            batch = PromotionBatch.objects.get(id=batch_id)
        except PromotionBatch.DoesNotExist:
            return Response({"error": "Promotion batch not found."}, status=status.HTTP_404_NOT_FOUND)

        if batch.status == PromotionBatch.STATUS_REVERTED:
            return Response({"error": "This batch has already been reverted."}, status=status.HTTP_400_BAD_REQUEST)

        if timezone.now() - batch.applied_at > REVERT_WINDOW:
            return Response({"error": "The 7-day revert window for this batch has passed."}, status=status.HTTP_400_BAD_REQUEST)

        for record in batch.records.select_related("student"):
            student = record.student
            student.current_semester_year = record.previous_semester_year
            student.section_division = record.previous_section_division
            student.batch_academic_year = record.previous_batch_academic_year
            student.status = record.previous_status or "active"
            student.save(update_fields=["current_semester_year", "section_division", "batch_academic_year", "status"])

        batch.status = PromotionBatch.STATUS_REVERTED
        batch.reverted_by = request.user
        batch.reverted_at = timezone.now()
        batch.save(update_fields=["status", "reverted_by", "reverted_at"])

        return Response({"batch_id": batch.id, "status": batch.status}, status=status.HTTP_200_OK)

"""
Parent Link Manager (Admin)
============================
An admin-reviewed alternative to ParentLinkChildView's instant self-service
linking (views/guardian.py, verified via DOB/admission number). This path
is for requesters who can't supply that shared secret — the admin reviews
each request, with a phone-mismatch fraud signal computed against any
guardian already linked to the student.
"""

import uuid

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import StudentProfile, GuardianProfile, ParentLinkRequest
from ..permissions import IsSaaSOrCollegeAdmin
from ..services.notifications import notify_user


def _serialize(req):
    return {
        "id": req.id,
        "requested_by": req.requested_by.get_full_name() or req.requested_by.username,
        "requested_by_id": req.requested_by_id,
        "student_id": req.student_id,
        "student_name": req.student.user.get_full_name() or req.student.user.username,
        "claimed_relationship": req.claimed_relationship,
        "contact_phone": req.contact_phone,
        "phone_mismatch": req.phone_mismatch,
        "status": req.status,
        "admin_note": req.admin_note,
        "requested_at": req.requested_at.isoformat(),
    }


class ParentLinkRequestCreateView(APIView):
    """
    POST /api/parent-link-requests/
    Payload: {student_id, claimed_relationship, contact_phone}
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        student_id = request.data.get("student_id")
        contact_phone = (request.data.get("contact_phone") or "").strip()

        if not student_id:
            return Response({"error": "student_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            student = StudentProfile.objects.get(id=student_id)
        except StudentProfile.DoesNotExist:
            return Response({"error": "Student not found."}, status=status.HTTP_404_NOT_FOUND)

        existing_phones = set(
            student.guardians.exclude(contact_number="").exclude(contact_number__isnull=True)
            .values_list("contact_number", flat=True)
        )
        phone_mismatch = bool(existing_phones) and contact_phone not in existing_phones

        link_request = ParentLinkRequest.objects.create(
            requested_by=request.user,
            student=student,
            claimed_relationship=request.data.get("claimed_relationship", ""),
            contact_phone=contact_phone,
            phone_mismatch=phone_mismatch,
        )
        return Response(_serialize(link_request), status=status.HTTP_201_CREATED)


class AdminParentLinkRequestListView(APIView):
    """
    GET /api/parent-link-requests/?status=pending
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        status_filter = request.query_params.get("status", ParentLinkRequest.STATUS_PENDING)
        qs = ParentLinkRequest.objects.filter(status=status_filter).select_related("requested_by", "student__user")
        return Response({"results": [_serialize(r) for r in qs]}, status=status.HTTP_200_OK)


class AdminParentLinkRequestActionView(APIView):
    """
    POST /api/parent-link-requests/<id>/action/
    Payload: {action: "approve" | "reject" | "ask_for_id", note?}
    """
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def post(self, request, pk):
        try:
            link_request = ParentLinkRequest.objects.select_related("requested_by", "student__user").get(pk=pk)
        except ParentLinkRequest.DoesNotExist:
            return Response({"error": "Link request not found."}, status=status.HTTP_404_NOT_FOUND)

        action = request.data.get("action")
        if action not in ("approve", "reject", "ask_for_id"):
            return Response({"error": "action must be 'approve', 'reject', or 'ask_for_id'."}, status=status.HTTP_400_BAD_REQUEST)

        if link_request.status in (ParentLinkRequest.STATUS_APPROVED, ParentLinkRequest.STATUS_REJECTED):
            return Response({"error": "This request has already been finalized."}, status=status.HTTP_400_BAD_REQUEST)

        note = request.data.get("note", "")
        student_name = link_request.student.user.get_full_name() or link_request.student.user.username

        if action == "approve":
            guardian, _ = GuardianProfile.objects.get_or_create(
                user=link_request.requested_by,
                defaults={
                    "guardian_id": f"GUA-{uuid.uuid4().hex[:6].upper()}",
                    "contact_number": link_request.contact_phone,
                },
            )
            guardian.students.add(link_request.student)
            link_request.status = ParentLinkRequest.STATUS_APPROVED
            notify_title = f"Link approved for {student_name}"
            notify_body = f"You are now linked to {student_name}'s account."
        elif action == "reject":
            link_request.status = ParentLinkRequest.STATUS_REJECTED
            notify_title = f"Link request rejected for {student_name}"
            notify_body = note or "Your request could not be verified."
        else:
            link_request.status = ParentLinkRequest.STATUS_ID_REQUESTED
            notify_title = f"ID verification needed for {student_name}"
            notify_body = note or "Please visit the school office with a valid ID to complete verification."

        link_request.admin_note = note
        link_request.reviewed_by = request.user
        link_request.reviewed_at = timezone.now()
        link_request.save(update_fields=["status", "admin_note", "reviewed_by", "reviewed_at"])

        notify_user(
            link_request.requested_by,
            title=notify_title,
            body=notify_body,
            category="parent_link_request",
            data={"link_request_id": link_request.id, "status": link_request.status},
        )

        return Response(_serialize(link_request), status=status.HTTP_200_OK)

from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.academics import AcademicYear
from ..models.statutory_committee import (
    StatutoryCommittee, CommitteeMembership, CommitteeComplaint, CommitteeMeeting,
)
from ..permissions import IsCommitteeMember, IsSaaSOrCollegeAdmin, RequiresModule, is_saas_or_college_admin

# Deliberately NOT applied to CommitteeComplaintViewSet or CommitteeMeetingViewSet:
# filing an Anti-Ragging/POSH/Grievance complaint (and a committee member seeing
# their own committee's meetings) must stay reachable regardless of whether a
# College Admin has "compliance-center" toggled on for that role — this is a
# statutory reporting channel (POSH Act Section 16), not a premium feature, and
# should never depend on a SaaS subscription/module-assignment setting. Only the
# purely administrative views below (configuring committees, viewing the
# aggregate annual report) are gated — those genuinely are compliance-center
# admin tooling.
COMPLIANCE_ADMIN_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("compliance-center")]
from ..serializers import (
    StatutoryCommitteeSerializer, CommitteeMembershipSerializer,
    CommitteeComplaintSerializer, CommitteeMeetingSerializer,
)
# Reused rather than duplicated — same multi-sheet xlsx shape AISHE/AICTE/
# NAAC/NIRF reports already use (see views/compliance.py's P5 section).
from .compliance import _accreditation_xlsx_response


class StatutoryCommitteeViewSet(viewsets.ModelViewSet):
    """Admin-managed: which committees exist for which academic year."""
    queryset = StatutoryCommittee.objects.select_related("academic_year").all()
    serializer_class = StatutoryCommitteeSerializer
    permission_classes = COMPLIANCE_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        academic_year = self.request.query_params.get("academic_year")
        committee_type = self.request.query_params.get("committee_type")
        if academic_year:
            qs = qs.filter(academic_year_id=academic_year)
        if committee_type:
            qs = qs.filter(committee_type=committee_type)
        return qs


class CommitteeMembershipViewSet(viewsets.ModelViewSet):
    """Admin-managed: who is appointed to a committee — the table
    IsCommitteeMember checks against."""
    queryset = CommitteeMembership.objects.select_related("committee", "user").all()
    serializer_class = CommitteeMembershipSerializer
    permission_classes = COMPLIANCE_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        committee = self.request.query_params.get("committee")
        if committee:
            qs = qs.filter(committee_id=committee)
        return qs


class CommitteeComplaintViewSet(viewsets.ModelViewSet):
    """
    Confidential to the committee: filing (create) is open to any
    authenticated user — that's the entire point of the mechanism — but
    listing/retrieving/updating is restricted to that committee's appointed
    members (or a College/SaaS Admin), enforced two ways: IsCommitteeMember's
    has_object_permission for detail actions, and get_queryset below so a
    non-member never even sees another committee's complaint show up in a
    list response.
    """
    queryset = CommitteeComplaint.objects.select_related("committee", "complainant").all()
    serializer_class = CommitteeComplaintSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsCommitteeMember()]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not is_saas_or_college_admin(user):
            member_committee_ids = CommitteeMembership.objects.filter(user=user).values_list("committee_id", flat=True)
            qs = qs.filter(committee_id__in=member_committee_ids)
        committee = self.request.query_params.get("committee")
        if committee:
            qs = qs.filter(committee_id=committee)
        return qs

    def perform_create(self, serializer):
        is_anonymous = serializer.validated_data.get("is_anonymous", False)
        serializer.save(complainant=None if is_anonymous else self.request.user)


class CommitteeMeetingViewSet(viewsets.ModelViewSet):
    """Meeting minutes — same committee-member-only bar as complaints (no
    open 'create' exception here; minutes are recorded by the committee,
    not filed by the public)."""
    queryset = CommitteeMeeting.objects.select_related("committee").prefetch_related("attendees").all()
    serializer_class = CommitteeMeetingSerializer
    permission_classes = [IsAuthenticated, IsCommitteeMember, IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if not is_saas_or_college_admin(user):
            member_committee_ids = CommitteeMembership.objects.filter(user=user).values_list("committee_id", flat=True)
            qs = qs.filter(committee_id__in=member_committee_ids)
        committee = self.request.query_params.get("committee")
        if committee:
            qs = qs.filter(committee_id=committee)
        return qs


class CommitteeAnnualReportView(APIView):
    """
    GET /api/compliance-center/reports/statutory-committee-report/?committee_type=icc_posh&academic_year=<id>&export=xlsx
    The POSH Section 21 annual-report shape (aggregate figures reported to
    the District Officer) — deliberately counts only, never a complainant's
    identity or complaint description, mirroring the same don't-leak
    boundary NIRFReportView's PR section uses for don't-fabricate. Admin
    only — even committee members don't get an aggregate cross-committee
    view through this endpoint, only through their own gated complaint list.
    """
    permission_classes = COMPLIANCE_ADMIN_PERMS

    def get(self, request):
        committee_type = request.query_params.get("committee_type")
        academic_year_id = request.query_params.get("academic_year")
        if not committee_type or not academic_year_id:
            return Response(
                {"error": "committee_type and academic_year query params are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        academic_year = AcademicYear.objects.filter(pk=academic_year_id).first()
        if not academic_year:
            return Response({"error": "Academic year not found."}, status=status.HTTP_404_NOT_FOUND)

        committee = StatutoryCommittee.objects.filter(
            committee_type=committee_type, academic_year=academic_year,
        ).first()
        if not committee:
            return Response({"error": "No committee of this type exists for this academic year yet."}, status=status.HTTP_404_NOT_FOUND)

        complaints = CommitteeComplaint.objects.filter(committee=committee)
        total = complaints.count()
        resolved = complaints.filter(status=CommitteeComplaint.STATUS_RESOLVED).count()
        closed = complaints.filter(status=CommitteeComplaint.STATUS_CLOSED).count()
        pending = complaints.exclude(
            status__in=[CommitteeComplaint.STATUS_RESOLVED, CommitteeComplaint.STATUS_CLOSED, CommitteeComplaint.STATUS_WITHDRAWN],
        ).count()
        pending_over_90_days = complaints.filter(
            filed_date__lte=timezone.now().date() - timezone.timedelta(days=90),
        ).exclude(
            status__in=[CommitteeComplaint.STATUS_RESOLVED, CommitteeComplaint.STATUS_CLOSED, CommitteeComplaint.STATUS_WITHDRAWN],
        ).count()

        members = CommitteeMembership.objects.filter(committee=committee)
        member_rows = [
            [m.user.get_full_name() or m.user.username if m.user else m.external_member_name, m.role_in_committee, m.appointed_date]
            for m in members
        ]

        meetings_count = CommitteeMeeting.objects.filter(committee=committee).count()

        sections = [
            ("Summary", ["Metric", "Value"], [
                ["Committee Type", committee.get_committee_type_display()],
                ["Academic Year", academic_year.name],
                ["Formed Date", committee.formed_date],
                ["Total Complaints Received", total],
                ["Resolved", resolved],
                ["Closed", closed],
                ["Pending", pending],
                ["Pending > 90 Days", pending_over_90_days],
                ["Meetings Held", meetings_count],
            ]),
            ("Committee Membership", ["Name", "Role", "Appointed Date"], member_rows),
        ]

        if (request.query_params.get("export") or "").lower() == "xlsx":
            filename = f"{committee_type}_annual_report_{academic_year.name}.xlsx"
            return _accreditation_xlsx_response(filename, sections)

        return Response({"sections": [{"heading": h, "header": header, "rows": rows} for h, header, rows in sections]})

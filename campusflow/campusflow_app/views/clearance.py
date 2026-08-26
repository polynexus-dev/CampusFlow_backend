"""
Clearance (No-Dues) Views
=========================
Admin-configurable desks + cadence, per-student clearance requests made up of
per-desk items, and the eligibility/certificate endpoints other modules
(promotion, exams) gate on. See services/clearance.py for the shared
eligibility rule and reference-data lookups.
"""

from django.contrib.auth.models import Group
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.academics import AcademicYear, Term
from ..models.clearance import ClearanceDesk, ClearanceItem, ClearanceRequest, ClearanceSettings
from ..models.profile import StudentProfile
from ..permissions import (
    IsCollegeAdmin, RequiresModule, get_user_group, is_college_admin, is_hm_or_above,
)
from ..services.clearance import (
    bulk_generate_clearance_requests, create_clearance_request,
    get_clearance_settings, is_student_cleared,
)
from ..services.notifications import notify_user

CLEARANCE_PERMS = [IsAuthenticated, IsNotDemoTenant, RequiresModule("clearance")]
CLEARANCE_ADMIN_PERMS = [IsAuthenticated, IsNotDemoTenant, IsCollegeAdmin, RequiresModule("clearance")]


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────

class ClearanceDeskSerializer(serializers.ModelSerializer):
    # By role name, not Group PK — matches how every other role-facing endpoint
    # in this codebase (CustomRolesView, ROLE_DEFAULT_MODULES keys) identifies
    # a role, so the frontend can reuse its existing "list of role names"
    # dropdown data (GET /tenant/roles/) without a second, PK-based lookup.
    responsible_group = serializers.SlugRelatedField(slug_field="name", queryset=Group.objects.all())

    class Meta:
        model = ClearanceDesk
        fields = [
            "id", "name", "code", "responsible_group",
            "linked_module", "order", "is_active", "created_at",
        ]


class ClearanceSettingsSerializer(serializers.ModelSerializer):
    class Meta:
        model = ClearanceSettings
        fields = ["id", "cadence", "updated_at"]


class ClearanceItemSerializer(serializers.ModelSerializer):
    desk_name = serializers.CharField(source="desk.name", read_only=True)
    desk_code = serializers.CharField(source="desk.code", read_only=True)
    desk_responsible_group = serializers.CharField(source="desk.responsible_group.name", read_only=True)
    cleared_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ClearanceItem
        fields = [
            "id", "request", "desk", "desk_name", "desk_code", "desk_responsible_group", "status",
            "remarks", "reference_snapshot", "cleared_by", "cleared_by_name",
            "cleared_at", "created_at",
        ]
        read_only_fields = ["reference_snapshot", "cleared_by", "cleared_at"]

    def get_cleared_by_name(self, obj):
        return obj.cleared_by.get_full_name() if obj.cleared_by else None


class ClearanceRequestSerializer(serializers.ModelSerializer):
    items = ClearanceItemSerializer(many=True, read_only=True)
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)
    student_display_id = serializers.CharField(source="student.student_id", read_only=True)
    term_name = serializers.SerializerMethodField()
    academic_year_name = serializers.SerializerMethodField()

    class Meta:
        model = ClearanceRequest
        fields = [
            "id", "student", "student_name", "student_display_id", "cycle_type",
            "term", "term_name", "academic_year", "academic_year_name",
            "status", "generated_by", "items", "created_at", "completed_at",
        ]

    def get_term_name(self, obj):
        return obj.term.name if obj.term else None

    def get_academic_year_name(self, obj):
        return obj.academic_year.name if obj.academic_year else None


# ─────────────────────────────────────────────────────────────────────────────
# Desk config & cadence settings (College Admin only)
# ─────────────────────────────────────────────────────────────────────────────

class ClearanceDeskViewSet(viewsets.ModelViewSet):
    """CRUD the per-college list of clearance desks (Library, Hostel, Fees, ...)."""
    queryset = ClearanceDesk.objects.select_related("responsible_group").all()
    serializer_class = ClearanceDeskSerializer
    permission_classes = CLEARANCE_ADMIN_PERMS

    def perform_destroy(self, instance):
        # A hard delete would raise ProtectedError the moment any ClearanceItem
        # already references this desk (on_delete=PROTECT on that FK) — and
        # even where it wouldn't, deleting loses the desk name/config behind
        # historical items. "Remove" a desk by deactivating it instead, same
        # as the model's own is_active docstring describes.
        instance.is_active = False
        instance.save(update_fields=["is_active"])


class ClearanceSettingsView(APIView):
    """
    GET the tenant's clearance cadence (semester_end / year_end) — readable by
    any authenticated user with the module, since an HOD/desk staff also needs
    to know it (e.g. to pick term vs. academic_year when generating clearance).
    PATCH stays College-Admin-only.
    """
    permission_classes = CLEARANCE_PERMS

    def get(self, request):
        return Response(ClearanceSettingsSerializer(get_clearance_settings()).data)

    def patch(self, request):
        if not is_college_admin(request.user):
            return Response({"error": "Only a College Admin can change the clearance cadence."}, status=status.HTTP_403_FORBIDDEN)
        settings_row = get_clearance_settings()
        serializer = ClearanceSettingsSerializer(settings_row, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ─────────────────────────────────────────────────────────────────────────────
# Clearance requests
# ─────────────────────────────────────────────────────────────────────────────

class ClearanceRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """
    GET list/retrieve of clearance requests. A student sees only their own; a
    desk-role user (Librarian, Hostel Warden, Fee Counter, ...) sees requests
    with a pending item at their own desk; College Admin/HOD see everything,
    filterable by department/term/status/cycle_type.
    """
    serializer_class = ClearanceRequestSerializer
    permission_classes = CLEARANCE_PERMS

    def get_queryset(self):
        user = self.request.user
        qs = (
            ClearanceRequest.objects
            .select_related("student__user", "student__department", "term", "academic_year")
            .prefetch_related("items__desk")
            .order_by("-created_at")
        )

        student_profile = getattr(user, "student_profile", None)
        if student_profile is not None:
            return qs.filter(student=student_profile)

        if not (is_college_admin(user) or is_hm_or_above(user)):
            user_group = get_user_group(user)
            qs = qs.filter(
                items__desk__responsible_group__name=user_group,
                items__status=ClearanceItem.STATUS_PENDING,
            ).distinct()

        params = self.request.query_params
        if params.get("department"):
            qs = qs.filter(student__department_id=params["department"])
        if params.get("term"):
            qs = qs.filter(term_id=params["term"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("cycle_type"):
            qs = qs.filter(cycle_type=params["cycle_type"])
        return qs


class ClearanceBulkGenerateView(APIView):
    """
    POST /clearance/requests/bulk-generate/
    Payload: {"term_id": ...} or {"academic_year_id": ...} — whichever matches
    the tenant's cadence — plus an optional "department_id" filter.
    """
    permission_classes = CLEARANCE_PERMS

    def post(self, request):
        if not (is_college_admin(request.user) or is_hm_or_above(request.user)):
            return Response(
                {"error": "Only a College Admin or HOD can generate clearance requests."},
                status=status.HTTP_403_FORBIDDEN,
            )

        settings_row = get_clearance_settings()
        term = academic_year = None
        if settings_row.cadence == ClearanceSettings.CADENCE_SEMESTER_END:
            term_id = request.data.get("term_id")
            if not term_id:
                return Response(
                    {"error": "term_id is required for this college's semester-end cadence."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            term = get_object_or_404(Term, pk=term_id)
        else:
            year_id = request.data.get("academic_year_id")
            if not year_id:
                return Response(
                    {"error": "academic_year_id is required for this college's year-end cadence."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            academic_year = get_object_or_404(AcademicYear, pk=year_id)

        created, skipped = bulk_generate_clearance_requests(
            term=term, academic_year=academic_year,
            department_id=request.data.get("department_id"),
            generated_by=request.user,
        )
        return Response({"created": created, "skipped_existing": skipped}, status=status.HTTP_201_CREATED)


class FinalExitClearanceRequestView(APIView):
    """POST /clearance/requests/final-exit/ — one-off TC/No-Dues request for a single student."""
    permission_classes = CLEARANCE_PERMS

    def post(self, request):
        student_profile = getattr(request.user, "student_profile", None)
        student_id = request.data.get("student_id")

        if student_profile is not None and not student_id:
            student = student_profile
        elif is_college_admin(request.user) or is_hm_or_above(request.user):
            if not student_id:
                return Response({"error": "student_id is required."}, status=status.HTTP_400_BAD_REQUEST)
            student = get_object_or_404(StudentProfile, pk=student_id)
        else:
            return Response(
                {"error": "Only a student (for themself) or a College Admin/HOD can request final-exit clearance."},
                status=status.HTTP_403_FORBIDDEN,
            )

        existing_open = ClearanceRequest.objects.filter(
            student=student, cycle_type=ClearanceRequest.CYCLE_FINAL_EXIT,
        ).exclude(status=ClearanceRequest.STATUS_REJECTED).first()
        if existing_open:
            return Response(
                {
                    "error": "A final-exit clearance request already exists for this student.",
                    "request_id": existing_open.id,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        clearance_request, _ = create_clearance_request(
            student, ClearanceRequest.CYCLE_FINAL_EXIT, generated_by=request.user,
        )
        return Response(ClearanceRequestSerializer(clearance_request).data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# Item actions (clear / reject)
# ─────────────────────────────────────────────────────────────────────────────

def _act_on_clearance_item(request, pk, new_status):
    item = get_object_or_404(
        ClearanceItem.objects.select_related("request__student__user", "desk__responsible_group"),
        pk=pk,
    )

    user_group = get_user_group(request.user)
    is_desk_owner = user_group == item.desk.responsible_group.name
    if not (is_desk_owner or is_college_admin(request.user) or is_hm_or_above(request.user)):
        return Response(
            {"error": "You are not authorized to act on this desk's clearance items."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if item.status != ClearanceItem.STATUS_PENDING:
        return Response({"error": f"This item is already {item.status}."}, status=status.HTTP_400_BAD_REQUEST)

    remarks = request.data.get("remarks", "")
    if new_status == ClearanceItem.STATUS_REJECTED and not remarks:
        return Response({"error": "remarks is required when rejecting."}, status=status.HTTP_400_BAD_REQUEST)

    item.status = new_status
    item.remarks = remarks
    item.cleared_by = request.user
    item.cleared_at = timezone.now()
    item.save(update_fields=["status", "remarks", "cleared_by", "cleared_at"])

    new_request_status = item.request.recompute_status()

    student_user = item.request.student.user
    if new_status == ClearanceItem.STATUS_CLEARED:
        notify_user(
            student_user, f"{item.desk.name} clearance approved", body=remarks,
            category="clearance_cleared", data={"request_id": item.request_id},
        )
    else:
        notify_user(
            student_user, f"{item.desk.name} clearance rejected", body=remarks,
            category="clearance_rejected", data={"request_id": item.request_id},
        )

    if new_request_status == ClearanceRequest.STATUS_CLEARED:
        notify_user(
            student_user, "Clearance completed", body="All desks have cleared your request.",
            category="clearance_completed", data={"request_id": item.request_id},
        )

    return Response(ClearanceItemSerializer(item).data, status=status.HTTP_200_OK)


class ClearanceItemClearView(APIView):
    """POST /clearance/items/<id>/clear/"""
    permission_classes = CLEARANCE_PERMS

    def post(self, request, pk):
        return _act_on_clearance_item(request, pk, ClearanceItem.STATUS_CLEARED)


class ClearanceItemRejectView(APIView):
    """POST /clearance/items/<id>/reject/ — remarks required."""
    permission_classes = CLEARANCE_PERMS

    def post(self, request, pk):
        return _act_on_clearance_item(request, pk, ClearanceItem.STATUS_REJECTED)


# ─────────────────────────────────────────────────────────────────────────────
# Eligibility & certificate
# ─────────────────────────────────────────────────────────────────────────────

def _clearance_status_response(student, request):
    cycle_type = request.query_params.get("cycle", ClearanceRequest.CYCLE_PERIODIC)
    term_id = request.query_params.get("term")
    term = get_object_or_404(Term, pk=term_id) if term_id else None

    is_cleared, clearance_request = is_student_cleared(student, cycle_type=cycle_type, term=term)
    return Response({
        "is_cleared": is_cleared,
        "cycle_type": cycle_type,
        "request": ClearanceRequestSerializer(clearance_request).data if clearance_request else None,
    }, status=status.HTTP_200_OK)


def _clearance_certificate_response(student):
    clearance_request = ClearanceRequest.objects.filter(
        student=student, cycle_type=ClearanceRequest.CYCLE_FINAL_EXIT, status=ClearanceRequest.STATUS_CLEARED,
    ).order_by("-completed_at").first()
    if clearance_request is None:
        return Response(
            {"error": "No fully-cleared final-exit request found for this student."},
            status=status.HTTP_404_NOT_FOUND,
        )

    items = clearance_request.items.select_related("desk", "cleared_by")
    return Response({
        "student_id": student.student_id,
        "student_name": student.user.get_full_name() or student.user.username,
        "department": student.department.name if student.department else None,
        "cleared_on": clearance_request.completed_at,
        "desks": [
            {
                "desk": item.desk.name,
                "cleared_by": item.cleared_by.get_full_name() if item.cleared_by else None,
                "cleared_at": item.cleared_at,
                "remarks": item.remarks,
            }
            for item in items
        ],
    }, status=status.HTTP_200_OK)


class StudentClearanceStatusView(APIView):
    """
    GET /clearance/students/<id>/status/?cycle=periodic&term=<id>
    The eligibility check every gate (promotion, exam list, certificate) uses.
    A student may only view their own status.
    """
    permission_classes = [IsAuthenticated, RequiresModule("clearance")]

    def get(self, request, pk):
        student = get_object_or_404(StudentProfile, pk=pk)
        requester_profile = getattr(request.user, "student_profile", None)
        if requester_profile is not None and requester_profile.pk != student.pk:
            return Response({"error": "You can only view your own clearance status."}, status=status.HTTP_403_FORBIDDEN)
        return _clearance_status_response(student, request)


class ClearanceCertificateView(APIView):
    """GET /clearance/students/<id>/certificate/ — only once a final_exit request is fully cleared."""
    permission_classes = [IsAuthenticated, RequiresModule("clearance")]

    def get(self, request, pk):
        student = get_object_or_404(StudentProfile, pk=pk)
        requester_profile = getattr(request.user, "student_profile", None)
        if requester_profile is not None and requester_profile.pk != student.pk:
            return Response({"error": "You can only view your own certificate."}, status=status.HTTP_403_FORBIDDEN)
        return _clearance_certificate_response(student)


class MyClearanceStatusView(APIView):
    """GET /clearance/me/status/?cycle=periodic&term=<id> — self-service, no id lookup needed."""
    permission_classes = [IsAuthenticated, RequiresModule("clearance")]

    def get(self, request):
        student = getattr(request.user, "student_profile", None)
        if student is None:
            return Response({"error": "Only a student account has a clearance status."}, status=status.HTTP_403_FORBIDDEN)
        return _clearance_status_response(student, request)


class MyClearanceCertificateView(APIView):
    """GET /clearance/me/certificate/ — self-service, no id lookup needed."""
    permission_classes = [IsAuthenticated, RequiresModule("clearance")]

    def get(self, request):
        student = getattr(request.user, "student_profile", None)
        if student is None:
            return Response({"error": "Only a student account has a clearance certificate."}, status=status.HTTP_403_FORBIDDEN)
        return _clearance_certificate_response(student)

"""
Clearance (No-Dues) Views
=========================
- College Admin: offices (desks), cadence, college-wide flows, oversight.
- HOD: their department's flows (subject-wise, mentor, HOD sign-off), launch
  and progress for them, and their department's requests.
- Approvers (Librarian, Fee Counter, subject teacher, mentor, HOD...): an
  inbox of the items routed to them; clear or reject after checking.
- Students: their requests step by step, resubmit a rejected step, apply to
  flows that allow it, the certificate.
Rules live in services/clearance.py.
"""

from django.contrib.auth.models import Group, User
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.academics import AcademicYear, Program, Term
from ..models.clearance import (
    ClearanceDesk, ClearanceFlow, ClearanceFlowStep, ClearanceItem, ClearanceRequest, ClearanceSettings,
)
from ..models.department import Department
from ..models.profile import StudentProfile
from ..permissions import IsCollegeAdmin, RequiresModule, is_college_admin, is_hm_or_above
from ..services.clearance import (
    ClearanceActionError, act_on_item, bulk_generate_clearance_requests, can_act_on_item,
    clearance_status, create_request_for_flow, department_ids_led_by, ensure_default_flow,
    get_clearance_settings, is_clearance_overseer, items_assigned_to, launch_flow,
    refresh_snapshot, resolve_cycle, resubmit_item,
)

CLEARANCE_PERMS = [IsAuthenticated, IsNotDemoTenant, RequiresModule("clearance")]
CLEARANCE_ADMIN_PERMS = [IsAuthenticated, IsNotDemoTenant, IsCollegeAdmin, RequiresModule("clearance")]


def _student_of(user):
    return getattr(user, "student_profile", None)


def _can_manage_flow(user, flow):
    """College Admin: any flow. HOD: their own department's flows only."""
    if is_college_admin(user):
        return True
    return bool(flow.department_id) and flow.department_id in department_ids_led_by(user)


def _name(user):
    return (user.get_full_name() or user.username) if user else None


# ─────────────────────────────────────────────────────────────────────────────
# Serializers
# ─────────────────────────────────────────────────────────────────────────────

class ClearanceDeskSerializer(serializers.ModelSerializer):
    # By role name, not Group PK, so the frontend reuses GET /tenant/roles/.
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


class ClearanceFlowStepSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(required=False)
    desk = serializers.PrimaryKeyRelatedField(queryset=ClearanceDesk.objects.all(), required=False, allow_null=True)
    approver_user = serializers.PrimaryKeyRelatedField(queryset=User.objects.all(), required=False, allow_null=True)
    desk_name = serializers.CharField(source="desk.name", read_only=True, default=None)
    approver_user_name = serializers.SerializerMethodField()

    class Meta:
        model = ClearanceFlowStep
        fields = [
            "id", "order", "title", "instructions", "approver_type",
            "desk", "desk_name", "approver_user", "approver_user_name", "linked_module",
        ]

    def get_approver_user_name(self, obj):
        return _name(obj.approver_user)

    def validate(self, attrs):
        kind = attrs.get("approver_type")
        if kind == ClearanceFlowStep.APPROVER_DESK:
            desk = attrs.get("desk")
            if desk is None:
                raise serializers.ValidationError({"desk": "Pick the office that signs this step."})
            if not desk.is_active:
                raise serializers.ValidationError({"desk": f"The {desk.name} desk is inactive."})
        else:
            attrs["desk"] = None
        if kind == ClearanceFlowStep.APPROVER_SPECIFIC_USER:
            if attrs.get("approver_user") is None:
                raise serializers.ValidationError({"approver_user": "Pick the person who signs this step."})
        else:
            attrs["approver_user"] = None
        return attrs


def _step_signature(steps):
    """Comparable form of a step list, to tell a real change from a re-save."""
    def key(s):
        get = s.get if isinstance(s, dict) else (lambda f: getattr(s, f))
        desk = get("desk")
        user = get("approver_user")
        return (
            int(get("order") or 1), get("title"), get("instructions") or "", get("approver_type"),
            getattr(desk, "pk", desk), getattr(user, "pk", user), get("linked_module") or "none",
        )
    return sorted(key(s) for s in steps)


class ClearanceFlowSerializer(serializers.ModelSerializer):
    steps = ClearanceFlowStepSerializer(many=True)
    department = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(), required=False, allow_null=True)
    applies_to_programs = serializers.PrimaryKeyRelatedField(queryset=Program.objects.all(), many=True, required=False)
    department_name = serializers.CharField(source="department.name", read_only=True, default=None)
    created_by_name = serializers.SerializerMethodField()
    request_count = serializers.SerializerMethodField()
    can_edit = serializers.SerializerMethodField()

    class Meta:
        model = ClearanceFlow
        fields = [
            "id", "name", "description", "department", "department_name", "purpose", "approval_mode",
            "status", "allow_student_apply", "applies_to_programs", "applies_to_semesters",
            "steps", "created_by_name", "request_count", "can_edit", "created_at", "updated_at",
        ]
        read_only_fields = ["created_at", "updated_at"]

    def get_created_by_name(self, obj):
        return _name(obj.created_by)

    def get_request_count(self, obj):
        return obj.num_requests if hasattr(obj, "num_requests") else obj.requests.count()

    def get_can_edit(self, obj):
        request = self.context.get("request")
        return bool(request) and _can_manage_flow(request.user, obj)

    def validate_applies_to_semesters(self, value):
        if not isinstance(value, list) or not all(isinstance(v, int) and 1 <= v <= 20 for v in value):
            raise serializers.ValidationError("Give a list of semester numbers, e.g. [7, 8].")
        return sorted(set(value))

    def validate(self, attrs):
        user = self.context["request"].user
        instance = self.instance
        department = attrs.get("department", instance.department if instance else None)

        if not is_college_admin(user):
            led = department_ids_led_by(user)
            if department is None and len(led) == 1:
                department = Department.objects.get(pk=next(iter(led)))
                attrs["department"] = department
            if department is None or department.pk not in led:
                raise serializers.ValidationError(
                    {"department": "A Department Head can only build flows for their own department."}
                )
            steps = attrs.get("steps") or []
            if any(s["approver_type"] not in ClearanceFlowStep.DEPARTMENT_APPROVER_TYPES for s in steps):
                raise serializers.ValidationError({
                    "steps": "Department flows use department steps (subject teachers, mentor, HOD, a named "
                             "person). College offices like Library and Fees belong in the college-wide flow."
                })

        new_status = attrs.get("status", instance.status if instance else ClearanceFlow.STATUS_DRAFT)
        steps = attrs.get("steps", None)
        step_count = len(steps) if steps is not None else (instance.steps.count() if instance else 0)
        if new_status == ClearanceFlow.STATUS_PUBLISHED and step_count == 0:
            raise serializers.ValidationError({"steps": "Add at least one step before publishing."})

        if instance and steps is not None and instance.requests.exists():
            if _step_signature(steps) != _step_signature(list(instance.steps.all())):
                raise serializers.ValidationError({
                    "steps": "This flow has already been launched, so its steps can't change. "
                             "Close it and create a new flow instead."
                })
            attrs.pop("steps")
        return attrs

    def _write_steps(self, flow, steps):
        flow.steps.all().delete()
        for step in steps:
            step.pop("id", None)
            if step.get("desk") and step.get("linked_module", "none") == "none":
                step["linked_module"] = step["desk"].linked_module
            ClearanceFlowStep.objects.create(flow=flow, **step)

    @transaction.atomic
    def create(self, validated_data):
        steps = validated_data.pop("steps", [])
        programs = validated_data.pop("applies_to_programs", [])
        flow = ClearanceFlow.objects.create(created_by=self.context["request"].user, **validated_data)
        flow.applies_to_programs.set(programs)
        self._write_steps(flow, steps)
        return flow

    @transaction.atomic
    def update(self, instance, validated_data):
        steps = validated_data.pop("steps", None)
        programs = validated_data.pop("applies_to_programs", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if programs is not None:
            instance.applies_to_programs.set(programs)
        if steps is not None:
            self._write_steps(instance, steps)
        return instance


class ClearanceItemSerializer(serializers.ModelSerializer):
    title = serializers.CharField(source="display_title", read_only=True)
    # desk_name is kept (= title) for the mobile app and older screens.
    desk_name = serializers.CharField(source="display_title", read_only=True)
    desk_code = serializers.CharField(source="desk.code", read_only=True, default=None)
    desk_responsible_group = serializers.CharField(source="approver_group.name", read_only=True, default=None)
    approver_name = serializers.SerializerMethodField()
    instructions = serializers.CharField(source="step.instructions", read_only=True, default="")
    approver_type = serializers.CharField(source="step.approver_type", read_only=True, default="desk")
    cleared_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ClearanceItem
        fields = [
            "id", "request", "step", "step_order", "title", "desk", "desk_name", "desk_code",
            "desk_responsible_group", "approver", "approver_name", "approver_type", "offering",
            "instructions", "status", "remarks", "student_note", "resubmit_count", "reference_snapshot",
            "cleared_by", "cleared_by_name", "cleared_at", "created_at",
        ]
        read_only_fields = fields

    def get_approver_name(self, obj):
        if obj.approver_id:
            return _name(obj.approver)
        return obj.approver_group.name if obj.approver_group_id else None

    def get_cleared_by_name(self, obj):
        return _name(obj.cleared_by)


class ClearanceRequestSerializer(serializers.ModelSerializer):
    items = ClearanceItemSerializer(many=True, read_only=True)
    student_name = serializers.CharField(source="student.user.get_full_name", read_only=True)
    student_display_id = serializers.CharField(source="student.student_id", read_only=True)
    department_name = serializers.CharField(source="student.department.name", read_only=True, default=None)
    flow_name = serializers.SerializerMethodField()
    approval_mode = serializers.CharField(source="flow.approval_mode", read_only=True, default="parallel")
    term_name = serializers.CharField(source="term.name", read_only=True, default=None)
    academic_year_name = serializers.CharField(source="academic_year.name", read_only=True, default=None)

    class Meta:
        model = ClearanceRequest
        fields = [
            "id", "student", "student_name", "student_display_id", "department_name",
            "flow", "flow_name", "approval_mode", "cycle_type",
            "term", "term_name", "academic_year", "academic_year_name",
            "status", "generated_by", "items", "created_at", "completed_at",
        ]

    def get_flow_name(self, obj):
        return obj.flow.name if obj.flow_id else obj.get_cycle_type_display()


class InboxItemSerializer(ClearanceItemSerializer):
    student_name = serializers.CharField(source="request.student.user.get_full_name", read_only=True)
    student_display_id = serializers.CharField(source="request.student.student_id", read_only=True)
    department_name = serializers.CharField(source="request.student.department.name", read_only=True, default=None)
    flow_name = serializers.SerializerMethodField()
    cycle_type = serializers.CharField(source="request.cycle_type", read_only=True)
    term_name = serializers.CharField(source="request.term.name", read_only=True, default=None)
    academic_year_name = serializers.CharField(source="request.academic_year.name", read_only=True, default=None)

    class Meta(ClearanceItemSerializer.Meta):
        fields = ClearanceItemSerializer.Meta.fields + [
            "student_name", "student_display_id", "department_name", "flow_name",
            "cycle_type", "term_name", "academic_year_name",
        ]
        read_only_fields = fields

    def get_flow_name(self, obj):
        return obj.request.flow.name if obj.request.flow_id else obj.request.get_cycle_type_display()


ITEM_RELATED = (
    "request__student__user", "request__student__department", "request__flow", "request__term",
    "request__academic_year", "step", "desk", "approver", "approver_group", "cleared_by",
)


# ─────────────────────────────────────────────────────────────────────────────
# Desks & cadence (College Admin)
# ─────────────────────────────────────────────────────────────────────────────

class ClearanceDeskViewSet(viewsets.ModelViewSet):
    """CRUD the per-college list of offices (Library, Hostel, Fees, ...)."""
    queryset = ClearanceDesk.objects.select_related("responsible_group").all()
    serializer_class = ClearanceDeskSerializer
    permission_classes = CLEARANCE_PERMS

    def get_permissions(self):
        # Reading the office list is needed by anyone building a flow; changing it is admin-only.
        perms = CLEARANCE_PERMS if self.request.method in ("GET", "HEAD", "OPTIONS") else CLEARANCE_ADMIN_PERMS
        return [permission() for permission in perms]

    def perform_destroy(self, instance):
        # Items and flow steps reference desks (PROTECT); deactivate instead.
        instance.is_active = False
        instance.save(update_fields=["is_active"])


class ClearanceSettingsView(APIView):
    """GET the cadence (anyone with the module). PATCH: College Admin only."""
    permission_classes = CLEARANCE_PERMS

    def get(self, request):
        return Response(ClearanceSettingsSerializer(get_clearance_settings()).data)

    def patch(self, request):
        if not is_college_admin(request.user):
            return Response({"error": "Only a College Admin can change the clearance cadence."}, status=status.HTTP_403_FORBIDDEN)
        serializer = ClearanceSettingsSerializer(get_clearance_settings(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response(serializer.data)


# ─────────────────────────────────────────────────────────────────────────────
# Flows (College Admin: college-wide + any; HOD: own department)
# ─────────────────────────────────────────────────────────────────────────────

class ClearanceFlowViewSet(viewsets.ModelViewSet):
    serializer_class = ClearanceFlowSerializer
    permission_classes = CLEARANCE_PERMS

    def get_queryset(self):
        user = self.request.user
        qs = (
            ClearanceFlow.objects.select_related("department", "created_by")
            .prefetch_related("steps__desk", "steps__approver_user", "applies_to_programs")
            .annotate(num_requests=Count("requests", distinct=True))
        )
        if is_clearance_overseer(user):
            pass
        elif department_ids_led_by(user):
            qs = qs.filter(Q(department__isnull=True) | Q(department_id__in=department_ids_led_by(user)))
        else:
            # Everyone else (approvers) may read published flows for context.
            qs = qs.filter(status=ClearanceFlow.STATUS_PUBLISHED)
        params = self.request.query_params
        if params.get("department"):
            qs = qs.filter(department_id=params["department"])
        if params.get("scope") == "college":
            qs = qs.filter(department__isnull=True)
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("purpose"):
            qs = qs.filter(purpose=params["purpose"])
        return qs.order_by("department__name", "name")

    def _require_builder(self):
        user = self.request.user
        if not (is_college_admin(user) or department_ids_led_by(user)):
            return Response(
                {"error": "Only a College Admin or a Department Head can build clearance flows."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return None

    def create(self, request, *args, **kwargs):
        if _student_of(request.user) is not None:
            return Response({"error": "Students can't build clearance flows."}, status=status.HTTP_403_FORBIDDEN)
        denied = self._require_builder()
        if denied:
            return denied
        response = super().create(request, *args, **kwargs)
        return self._send_on_publish(response, was_published=False)

    def update(self, request, *args, **kwargs):
        flow = self.get_object()
        if not _can_manage_flow(request.user, flow):
            return Response({"error": "You can't edit this flow."}, status=status.HTTP_403_FORBIDDEN)
        was_published = flow.status == ClearanceFlow.STATUS_PUBLISHED
        response = super().update(request, *args, **kwargs)
        return self._send_on_publish(response, was_published)

    def _send_on_publish(self, response, was_published):
        """
        Publishing sends the flow: every eligible student gets a request at
        once, so it shows under their Clearance without a separate Launch.
        Flows students apply for themselves (TC, final exit) are not pushed
        to everyone. Launch stays for late joiners or a narrower send.
        """
        if response.status_code >= 300 or was_published or response.data.get("status") != ClearanceFlow.STATUS_PUBLISHED:
            return response
        flow = ClearanceFlow.objects.get(pk=response.data["id"])
        if flow.allow_student_apply:
            return response
        term, academic_year, error = _cycle_from_payload(flow, {})
        if error:
            response.data["launched"] = {"created": 0, "skipped_existing": 0, "error": error.data["error"]}
            return response
        created, skipped = launch_flow(flow, term=term, academic_year=academic_year, generated_by=self.request.user)
        response.data["launched"] = {"created": created, "skipped_existing": skipped}
        response.data["request_count"] = created + skipped
        return response

    def destroy(self, request, *args, **kwargs):
        flow = self.get_object()
        if not _can_manage_flow(request.user, flow):
            return Response({"error": "You can't delete this flow."}, status=status.HTTP_403_FORBIDDEN)
        if flow.requests.exists():
            return Response(
                {"error": "This flow has requests. Close it instead, so their history is kept."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        flow.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ClearanceApproverCandidatesView(APIView):
    """GET /clearance/approver-candidates/?q= — staff to pick for a "specific person" step."""
    permission_classes = CLEARANCE_PERMS

    def get(self, request):
        if not (is_college_admin(request.user) or department_ids_led_by(request.user)):
            return Response({"error": "Only flow builders can search staff."}, status=status.HTTP_403_FORBIDDEN)
        q = (request.query_params.get("q") or "").strip()
        users = User.objects.filter(is_active=True, student_profile__isnull=True).exclude(groups__name="student")
        if q:
            users = users.filter(Q(first_name__icontains=q) | Q(last_name__icontains=q) | Q(username__icontains=q))
        users = users.prefetch_related("groups").order_by("first_name", "username")[:25]
        return Response([
            {"id": u.id, "name": _name(u), "role": next((g.name for g in u.groups.all()), None)}
            for u in users
        ])


def _cycle_from_payload(flow, data):
    """(term, academic_year, error_response) for a launch/apply payload."""
    if flow.purpose != ClearanceFlow.PURPOSE_PERIODIC:
        return None, None, None
    term = academic_year = None
    if data.get("term_id"):
        term = get_object_or_404(Term, pk=data["term_id"])
    if data.get("academic_year_id"):
        academic_year = get_object_or_404(AcademicYear, pk=data["academic_year_id"])
    term, academic_year = resolve_cycle(flow.purpose, term, academic_year)
    if term is None and academic_year is None:
        cadence = get_clearance_settings().cadence
        need = "term_id" if cadence == ClearanceSettings.CADENCE_SEMESTER_END else "academic_year_id"
        return None, None, Response(
            {"error": f"{need} is required: no current {'term' if need == 'term_id' else 'academic year'} is set."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    return term, academic_year, None


class ClearanceFlowLaunchView(APIView):
    """
    POST /clearance/flows/<id>/launch/
    {term_id | academic_year_id (periodic only; defaults to current),
     department_id?, program_id?, semester?, student_ids?}
    Creates a request for every eligible student; existing ones are skipped.
    """
    permission_classes = CLEARANCE_PERMS

    def post(self, request, pk):
        flow = get_object_or_404(ClearanceFlow, pk=pk)
        if not _can_manage_flow(request.user, flow):
            return Response({"error": "You can't launch this flow."}, status=status.HTTP_403_FORBIDDEN)
        if flow.status != ClearanceFlow.STATUS_PUBLISHED:
            return Response({"error": "Publish the flow before launching it."}, status=status.HTTP_400_BAD_REQUEST)

        term, academic_year, error = _cycle_from_payload(flow, request.data)
        if error:
            return error
        student_ids = request.data.get("student_ids") or None
        if student_ids is not None and not isinstance(student_ids, list):
            return Response({"error": "student_ids must be a list."}, status=status.HTTP_400_BAD_REQUEST)

        created, skipped = launch_flow(
            flow, term=term, academic_year=academic_year, generated_by=request.user,
            department_id=request.data.get("department_id") or None,
            program_id=request.data.get("program_id") or None,
            semester=request.data.get("semester") or None,
            student_ids=student_ids,
        )
        return Response({"created": created, "skipped_existing": skipped}, status=status.HTTP_201_CREATED)


class ClearanceFlowProgressView(APIView):
    """GET /clearance/flows/<id>/progress/?term=&academic_year= — where students are stuck."""
    permission_classes = CLEARANCE_PERMS

    def get(self, request, pk):
        flow = get_object_or_404(ClearanceFlow, pk=pk)
        if not (_can_manage_flow(request.user, flow) or is_clearance_overseer(request.user)):
            return Response({"error": "You can't view this flow's progress."}, status=status.HTTP_403_FORBIDDEN)

        requests_qs = ClearanceRequest.objects.filter(flow=flow)
        if request.query_params.get("term"):
            requests_qs = requests_qs.filter(term_id=request.query_params["term"])
        if request.query_params.get("academic_year"):
            requests_qs = requests_qs.filter(academic_year_id=request.query_params["academic_year"])
        by_status = dict(requests_qs.values_list("status").annotate(n=Count("id")))

        items = ClearanceItem.objects.filter(request__in=requests_qs)
        steps = []
        for step in flow.steps.all():
            counts = dict(items.filter(step=step).values_list("status").annotate(n=Count("id")))
            steps.append({
                "step_id": step.id, "order": step.order, "title": step.title,
                "approver_type": step.approver_type,
                "waiting": counts.get("waiting", 0), "pending": counts.get("pending", 0),
                "rejected": counts.get("rejected", 0), "cleared": counts.get("cleared", 0),
            })
        approvers = (
            items.filter(status=ClearanceItem.STATUS_PENDING)
            .values("approver__first_name", "approver__last_name", "approver__username", "approver_group__name")
            .annotate(pending=Count("id")).order_by("-pending")[:15]
        )
        return Response({
            "flow": flow.id,
            "total": sum(by_status.values()),
            "cleared": by_status.get("cleared", 0),
            "pending": by_status.get("pending", 0),
            "rejected": by_status.get("rejected", 0),
            "steps": steps,
            "pending_by_approver": [
                {
                    "approver": (f"{a['approver__first_name']} {a['approver__last_name']}".strip()
                                 or a["approver__username"] or a["approver_group__name"] or "Unassigned"),
                    "pending": a["pending"],
                }
                for a in approvers
            ],
        })


class ClearanceFlowApplyView(APIView):
    """POST /clearance/flows/<id>/apply/ — a student starts a flow that allows it."""
    permission_classes = CLEARANCE_PERMS

    def post(self, request, pk):
        student = _student_of(request.user)
        if student is None:
            return Response({"error": "Only a student can apply."}, status=status.HTTP_403_FORBIDDEN)
        flow = get_object_or_404(ClearanceFlow, pk=pk)
        if flow.status != ClearanceFlow.STATUS_PUBLISHED or not flow.allow_student_apply or not flow.applies_to(student):
            return Response({"error": "This clearance isn't open for you to apply."}, status=status.HTTP_400_BAD_REQUEST)
        term, academic_year, error = _cycle_from_payload(flow, {})
        if error:
            return error
        request_obj, created = create_request_for_flow(
            flow, student, term=term, academic_year=academic_year, generated_by=request.user,
        )
        if not created:
            return Response(
                {"error": "You have already applied for this clearance.", "request_id": request_obj.id},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ClearanceRequestSerializer(request_obj).data, status=status.HTTP_201_CREATED)


class MyClearanceFlowsView(APIView):
    """GET /clearance/me/flows/ — flows a student may apply to themselves."""
    permission_classes = CLEARANCE_PERMS

    def get(self, request):
        student = _student_of(request.user)
        if student is None:
            return Response({"error": "Only a student account has clearance flows."}, status=status.HTTP_403_FORBIDDEN)
        flows = ClearanceFlow.objects.filter(
            status=ClearanceFlow.STATUS_PUBLISHED, allow_student_apply=True,
        ).filter(Q(department__isnull=True) | Q(department_id=student.department_id)).prefetch_related("applies_to_programs")
        applied = set(ClearanceRequest.objects.filter(student=student).values_list("flow_id", flat=True))
        return Response([
            {
                "id": f.id, "name": f.name, "description": f.description, "purpose": f.purpose,
                "department_name": f.department.name if f.department_id else None,
                "already_applied": f.id in applied,
            }
            for f in flows if f.applies_to(student)
        ])


# ─────────────────────────────────────────────────────────────────────────────
# Requests
# ─────────────────────────────────────────────────────────────────────────────

class ClearanceRequestViewSet(viewsets.ReadOnlyModelViewSet):
    """
    A student sees their own; an overseer (Admin/Principal) everything; an HOD
    their department's; any other approver the requests that have an item
    routed to them. Filters: department, term, status, cycle_type, flow, q.
    """
    serializer_class = ClearanceRequestSerializer
    permission_classes = CLEARANCE_PERMS

    def get_queryset(self):
        user = self.request.user
        qs = (
            ClearanceRequest.objects
            .select_related("student__user", "student__department", "term", "academic_year", "flow")
            .prefetch_related("items__desk", "items__step", "items__approver", "items__approver_group", "items__cleared_by")
            .order_by("-created_at")
        )
        student = _student_of(user)
        if student is not None:
            return qs.filter(student=student)

        if not is_clearance_overseer(user):
            led = department_ids_led_by(user)
            mine = Q(items__in=items_assigned_to(user))
            qs = qs.filter(Q(student__department_id__in=led) | mine if led else mine).distinct()

        params = self.request.query_params
        if params.get("department"):
            qs = qs.filter(student__department_id=params["department"])
        if params.get("term"):
            qs = qs.filter(term_id=params["term"])
        if params.get("status"):
            qs = qs.filter(status=params["status"])
        if params.get("cycle_type"):
            qs = qs.filter(cycle_type=params["cycle_type"])
        if params.get("flow"):
            qs = qs.filter(flow_id=params["flow"])
        if params.get("q"):
            q = params["q"].strip()
            qs = qs.filter(
                Q(student__student_id__icontains=q) | Q(student__user__first_name__icontains=q)
                | Q(student__user__last_name__icontains=q)
            )
        return qs


class ClearanceBulkGenerateView(APIView):
    """Legacy: launch the college-wide default periodic flow. Prefer flows/<id>/launch/."""
    permission_classes = CLEARANCE_PERMS

    def post(self, request):
        if not (is_college_admin(request.user) or is_hm_or_above(request.user)):
            return Response(
                {"error": "Only a College Admin or HOD can generate clearance requests."},
                status=status.HTTP_403_FORBIDDEN,
            )
        flow = ensure_default_flow(ClearanceFlow.PURPOSE_PERIODIC)
        term, academic_year, error = _cycle_from_payload(flow, request.data)
        if error:
            return error
        created, skipped = bulk_generate_clearance_requests(
            term=term, academic_year=academic_year,
            department_id=request.data.get("department_id"), generated_by=request.user,
        )
        return Response({"created": created, "skipped_existing": skipped}, status=status.HTTP_201_CREATED)


class FinalExitClearanceRequestView(APIView):
    """Legacy: start the college-wide final-exit flow for one student (or yourself)."""
    permission_classes = CLEARANCE_PERMS

    def post(self, request):
        student_profile = _student_of(request.user)
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
        flow = ensure_default_flow(ClearanceFlow.PURPOSE_FINAL_EXIT)
        if student_profile is not None and not flow.allow_student_apply:
            return Response({"error": "Final-exit clearance is started by the college office."}, status=status.HTTP_403_FORBIDDEN)
        request_obj, created = create_request_for_flow(flow, student, generated_by=request.user)
        if not created:
            return Response(
                {"error": "A final-exit clearance request already exists for this student.", "request_id": request_obj.id},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(ClearanceRequestSerializer(request_obj).data, status=status.HTTP_201_CREATED)


# ─────────────────────────────────────────────────────────────────────────────
# Approver inbox & item actions
# ─────────────────────────────────────────────────────────────────────────────

class ClearanceInboxView(APIView):
    """
    GET /clearance/inbox/?status=pending|rejected|cleared|all&flow=&q=
    The items routed to me (my role's desk, my subjects, my mentees, my HOD steps).
    """
    permission_classes = CLEARANCE_PERMS

    def get(self, request):
        qs = items_assigned_to(request.user).select_related(*ITEM_RELATED).order_by("created_at")
        wanted = request.query_params.get("status", ClearanceItem.STATUS_PENDING)
        if wanted != "all":
            qs = qs.filter(status=wanted)
        if request.query_params.get("flow"):
            qs = qs.filter(request__flow_id=request.query_params["flow"])
        if request.query_params.get("q"):
            q = request.query_params["q"].strip()
            qs = qs.filter(
                Q(request__student__student_id__icontains=q) | Q(request__student__user__first_name__icontains=q)
                | Q(request__student__user__last_name__icontains=q)
            )
        return Response(InboxItemSerializer(qs[:500], many=True).data)


class ClearanceInboxSummaryView(APIView):
    """GET /clearance/inbox/summary/ — counts for the dashboard card."""
    permission_classes = [IsAuthenticated, RequiresModule("clearance")]

    def get(self, request):
        if _student_of(request.user) is not None:
            return Response({"pending": 0, "rejected": 0})
        counts = dict(items_assigned_to(request.user).values_list("status").annotate(n=Count("id")))
        return Response({"pending": counts.get("pending", 0), "rejected": counts.get("rejected", 0)})


def _can_view_item(user, item):
    student = _student_of(user)
    if student is not None:
        return item.request.student_id == student.pk
    return can_act_on_item(user, item)


class ClearanceItemDetailView(APIView):
    """GET /clearance/items/<id>/ — the item, its history, the rest of the request; dues refreshed."""
    permission_classes = CLEARANCE_PERMS

    def get(self, request, pk):
        item = get_object_or_404(ClearanceItem.objects.select_related(*ITEM_RELATED), pk=pk)
        if not _can_view_item(request.user, item):
            return Response({"error": "You can't view this item."}, status=status.HTTP_403_FORBIDDEN)
        if _student_of(request.user) is None and item.status == ClearanceItem.STATUS_PENDING:
            refresh_snapshot(item)
        data = InboxItemSerializer(item).data
        data["can_act"] = item.status == ClearanceItem.STATUS_PENDING and can_act_on_item(request.user, item)
        data["history"] = [
            {"action": log.action, "by": _name(log.actor), "remarks": log.remarks, "at": log.created_at}
            for log in item.logs.select_related("actor")
        ]
        data["request_items"] = [
            {"id": i.id, "title": i.display_title, "status": i.status, "step_order": i.step_order}
            for i in item.request.items.select_related("desk")
        ]
        return Response(data)


def _act(request, pk, decision):
    item = get_object_or_404(ClearanceItem.objects.select_related(*ITEM_RELATED), pk=pk)
    if not can_act_on_item(request.user, item):
        return Response(
            {"error": "You are not authorized to act on this clearance item."},
            status=status.HTTP_403_FORBIDDEN,
        )
    try:
        item = act_on_item(item, request.user, decision, (request.data.get("remarks") or "").strip())
    except ClearanceActionError as exc:
        return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
    return Response(ClearanceItemSerializer(item).data, status=status.HTTP_200_OK)


class ClearanceItemClearView(APIView):
    """POST /clearance/items/<id>/clear/"""
    permission_classes = CLEARANCE_PERMS

    def post(self, request, pk):
        return _act(request, pk, ClearanceItem.STATUS_CLEARED)


class ClearanceItemRejectView(APIView):
    """POST /clearance/items/<id>/reject/ — remarks required."""
    permission_classes = CLEARANCE_PERMS

    def post(self, request, pk):
        return _act(request, pk, ClearanceItem.STATUS_REJECTED)


class ClearanceItemResubmitView(APIView):
    """POST /clearance/items/<id>/resubmit/ {note} — the student, after fixing a rejected step."""
    permission_classes = CLEARANCE_PERMS

    def post(self, request, pk):
        item = get_object_or_404(ClearanceItem.objects.select_related(*ITEM_RELATED), pk=pk)
        student = _student_of(request.user)
        if student is None or item.request.student_id != student.pk:
            return Response({"error": "Only the student can resubmit their own item."}, status=status.HTTP_403_FORBIDDEN)
        try:
            item = resubmit_item(item, request.user, (request.data.get("note") or "").strip())
        except ClearanceActionError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ClearanceItemSerializer(item).data)


# ─────────────────────────────────────────────────────────────────────────────
# Eligibility & certificate
# ─────────────────────────────────────────────────────────────────────────────

def _clearance_status_response(student, request):
    cycle_type = request.query_params.get("cycle", ClearanceFlow.PURPOSE_PERIODIC)
    term_id = request.query_params.get("term")
    term = get_object_or_404(Term, pk=term_id) if term_id else None

    is_cleared, requests, missing = clearance_status(student, cycle_type, term=term)
    blocking = [r for r in requests if r.status != ClearanceRequest.STATUS_CLEARED]
    primary = blocking[0] if blocking else (max(requests, key=lambda r: r.created_at) if requests else None)
    return Response({
        "is_cleared": is_cleared,
        "cycle_type": cycle_type,
        "request": ClearanceRequestSerializer(primary).data if primary else None,
        "requests": ClearanceRequestSerializer(requests, many=True).data,
        "not_started_flows": [{"id": f.id, "name": f.name} for f in missing],
    }, status=status.HTTP_200_OK)


def _clearance_certificate_response(student):
    is_cleared, requests, _ = clearance_status(student, ClearanceFlow.PURPOSE_FINAL_EXIT)
    if not is_cleared or not requests:
        return Response(
            {"error": "No fully-cleared final-exit clearance found for this student."},
            status=status.HTTP_404_NOT_FOUND,
        )
    items = ClearanceItem.objects.filter(request__in=requests).select_related("desk", "cleared_by").order_by("request_id", "step_order", "id")
    return Response({
        "student_id": student.student_id,
        "student_name": student.user.get_full_name() or student.user.username,
        "department": student.department.name if student.department else None,
        "cleared_on": max(r.completed_at for r in requests if r.completed_at) if any(r.completed_at for r in requests) else None,
        "desks": [
            {
                "desk": item.display_title,
                "cleared_by": _name(item.cleared_by),
                "cleared_at": item.cleared_at,
                "remarks": item.remarks,
            }
            for item in items
        ],
    }, status=status.HTTP_200_OK)


class StudentClearanceStatusView(APIView):
    """GET /clearance/students/<id>/status/?cycle=periodic&term=<id> — a student may only view their own."""
    permission_classes = [IsAuthenticated, RequiresModule("clearance")]

    def get(self, request, pk):
        student = get_object_or_404(StudentProfile, pk=pk)
        requester_profile = _student_of(request.user)
        if requester_profile is not None and requester_profile.pk != student.pk:
            return Response({"error": "You can only view your own clearance status."}, status=status.HTTP_403_FORBIDDEN)
        return _clearance_status_response(student, request)


class ClearanceCertificateView(APIView):
    """GET /clearance/students/<id>/certificate/ — once final-exit clearance is complete."""
    permission_classes = [IsAuthenticated, RequiresModule("clearance")]

    def get(self, request, pk):
        student = get_object_or_404(StudentProfile, pk=pk)
        requester_profile = _student_of(request.user)
        if requester_profile is not None and requester_profile.pk != student.pk:
            return Response({"error": "You can only view your own certificate."}, status=status.HTTP_403_FORBIDDEN)
        return _clearance_certificate_response(student)


class MyClearanceStatusView(APIView):
    """GET /clearance/me/status/?cycle=periodic&term=<id>"""
    permission_classes = [IsAuthenticated, RequiresModule("clearance")]

    def get(self, request):
        student = _student_of(request.user)
        if student is None:
            return Response({"error": "Only a student account has a clearance status."}, status=status.HTTP_403_FORBIDDEN)
        return _clearance_status_response(student, request)


class MyClearanceCertificateView(APIView):
    """GET /clearance/me/certificate/"""
    permission_classes = [IsAuthenticated, RequiresModule("clearance")]

    def get(self, request):
        student = _student_of(request.user)
        if student is None:
            return Response({"error": "Only a student account has a clearance certificate."}, status=status.HTTP_403_FORBIDDEN)
        return _clearance_certificate_response(student)

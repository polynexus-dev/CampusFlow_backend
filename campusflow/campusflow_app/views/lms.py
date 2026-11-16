"""
LMS content library. Docs/college_gap_closure_plan.md §1.3.

  lms/my-offerings/        offerings the user teaches (faculty) or is registered in (student)
  lms/modules/             per-offering units; faculty of the offering or HOD+ manage them
  lms/resources/           files, video links, web links and notes inside a module
  lms/resources/<id>/view/ student records a view (engagement signal)
  lms/resources/<id>/engagement/   faculty: who has / hasn't opened it
"""
from django.db.models import Count, F, Q
from django.utils import timezone
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.lms import CourseModule, LearningResource, ResourceView
from ..models.offerings import CourseOffering, StudentCourseRegistration
from ..permissions import RequiresModule, is_faculty_or_above, is_hm_or_above
from ..utils.file_validation import validate_attachment

LMS_PERMS = [IsAuthenticated, RequiresModule("lms")]


def _student_profile(user):
    return getattr(user, "student_profile", None)


def _registered_offering_ids(student):
    return StudentCourseRegistration.objects.filter(
        student=student, status=StudentCourseRegistration.STATUS_REGISTERED,
    ).values_list("offering_id", flat=True)


def _visible_offerings(user):
    """Offerings whose content `user` may read."""
    student = _student_profile(user)
    if student is not None:
        return CourseOffering.objects.filter(id__in=_registered_offering_ids(student))
    if is_hm_or_above(user):
        return CourseOffering.objects.all()
    if is_faculty_or_above(user):
        return CourseOffering.objects.filter(faculty=user)
    return CourseOffering.objects.none()


def _can_manage(user, offering):
    if _student_profile(user) is not None:
        return False
    return is_hm_or_above(user) or (is_faculty_or_above(user) and offering.faculty_id == user.id)


def _released_q(prefix=""):
    now = timezone.now()
    return Q(**{f"{prefix}is_published": True}) & (
        Q(**{f"{prefix}release_at__isnull": True}) | Q(**{f"{prefix}release_at__lte": now})
    )


class MyOfferingsView(APIView):
    permission_classes = LMS_PERMS

    def get(self, request):
        offerings = (
            _visible_offerings(request.user)
            .filter(is_active=True)
            .select_related("course", "term", "batch", "section", "faculty")
            .annotate(module_count=Count("lms_modules", distinct=True))
            .order_by("course__course_code")
        )
        if request.query_params.get("term"):
            offerings = offerings.filter(term_id=request.query_params["term"])
        return Response([
            {
                "id": o.id,
                "course_id": o.course_id,
                "course_code": o.course.course_code,
                "course_name": o.course.course_name,
                "term": str(o.term),
                "batch": o.batch.name,
                "section": o.section.name if o.section_id else None,
                "faculty": (o.faculty.get_full_name() or o.faculty.username) if o.faculty_id else None,
                "module_count": o.module_count,
            }
            for o in offerings
        ])


# ── Modules ─────────────────────────────────────────────────────────────────

class LearningResourceSerializer(serializers.ModelSerializer):
    # Explicit default: on multipart uploads DRF reads an absent boolean as
    # False (HTML checkbox semantics), which would silently hide every
    # uploaded file from students.
    is_published = serializers.BooleanField(required=False, default=True)
    file_url = serializers.SerializerMethodField()
    viewed = serializers.SerializerMethodField()

    class Meta:
        model = LearningResource
        fields = [
            "id", "module", "title", "resource_type", "file", "file_url", "url", "body",
            "is_published", "release_at", "order", "uploaded_by", "created_at", "updated_at", "viewed",
        ]
        read_only_fields = ["uploaded_by"]
        extra_kwargs = {"file": {"write_only": True, "required": False}}

    def get_file_url(self, obj):
        return obj.file.url if obj.file else None

    def get_viewed(self, obj):
        viewed_ids = self.context.get("viewed_ids")
        return None if viewed_ids is None else obj.id in viewed_ids

    def validate(self, attrs):
        resource_type = attrs.get("resource_type", getattr(self.instance, "resource_type", None))
        file = attrs.get("file", getattr(self.instance, "file", None))
        url = attrs.get("url", getattr(self.instance, "url", ""))
        body = attrs.get("body", getattr(self.instance, "body", ""))
        if resource_type == LearningResource.TYPE_FILE:
            if not file:
                raise serializers.ValidationError({"file": "Upload a file for a file resource."})
            if "file" in attrs:
                error = validate_attachment(attrs["file"])
                if error:
                    raise serializers.ValidationError({"file": error})
        elif resource_type in (LearningResource.TYPE_VIDEO, LearningResource.TYPE_LINK):
            if not url:
                raise serializers.ValidationError({"url": "A link is required for this resource type."})
            if not url.lower().startswith(("https://", "http://")):
                raise serializers.ValidationError({"url": "Links must start with http:// or https://."})
        elif resource_type == LearningResource.TYPE_NOTE and not (body or "").strip():
            raise serializers.ValidationError({"body": "A note needs some text."})
        return attrs


class CourseModuleSerializer(serializers.ModelSerializer):
    resources = serializers.SerializerMethodField()
    syllabus_topic_name = serializers.CharField(source="syllabus_topic.name", read_only=True, default=None)

    class Meta:
        model = CourseModule
        fields = [
            "id", "offering", "title", "description", "syllabus_topic", "syllabus_topic_name",
            "order", "created_by", "created_at", "resources",
        ]
        read_only_fields = ["created_by"]

    def get_resources(self, obj):
        resources = obj.resources.all()
        if self.context.get("students_only_released"):
            now = timezone.now()
            resources = [
                r for r in resources if r.is_published and (r.release_at is None or r.release_at <= now)
            ]
        return LearningResourceSerializer(resources, many=True, context=self.context).data

    def validate(self, attrs):
        offering = attrs.get("offering", getattr(self.instance, "offering", None))
        topic = attrs.get("syllabus_topic")
        if topic is not None and offering is not None and topic.course_id != offering.course_id:
            raise serializers.ValidationError({"syllabus_topic": "That syllabus topic belongs to a different course."})
        return attrs


class CourseModuleViewSet(viewsets.ModelViewSet):
    serializer_class = CourseModuleSerializer
    permission_classes = LMS_PERMS

    def get_queryset(self):
        qs = (
            CourseModule.objects
            .filter(offering__in=_visible_offerings(self.request.user))
            .select_related("syllabus_topic")
            .prefetch_related("resources")
        )
        if self.request.query_params.get("offering"):
            qs = qs.filter(offering_id=self.request.query_params["offering"])
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        student = _student_profile(self.request.user)
        if student is not None:
            context["students_only_released"] = True
            context["viewed_ids"] = set(
                ResourceView.objects.filter(student=student).values_list("resource_id", flat=True)
            )
        return context

    def _require_manage(self, offering):
        if not _can_manage(self.request.user, offering):
            raise PermissionDenied("Only the offering's faculty or an HOD/Admin can change its content.")

    def perform_create(self, serializer):
        self._require_manage(serializer.validated_data["offering"])
        serializer.save(created_by=self.request.user)

    def perform_update(self, serializer):
        self._require_manage(serializer.instance.offering)
        if "offering" in serializer.validated_data:
            self._require_manage(serializer.validated_data["offering"])
        serializer.save()

    def perform_destroy(self, instance):
        self._require_manage(instance.offering)
        instance.delete()


# ── Resources ───────────────────────────────────────────────────────────────

class LearningResourceViewSet(viewsets.ModelViewSet):
    serializer_class = LearningResourceSerializer
    permission_classes = LMS_PERMS
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_queryset(self):
        user = self.request.user
        qs = LearningResource.objects.filter(module__offering__in=_visible_offerings(user)).select_related("module")
        if _student_profile(user) is not None:
            qs = qs.filter(_released_q())
        if self.request.query_params.get("module"):
            qs = qs.filter(module_id=self.request.query_params["module"])
        return qs

    def get_serializer_context(self):
        context = super().get_serializer_context()
        student = _student_profile(self.request.user)
        if student is not None:
            context["viewed_ids"] = set(
                ResourceView.objects.filter(student=student).values_list("resource_id", flat=True)
            )
        return context

    def _require_manage(self, module):
        if not _can_manage(self.request.user, module.offering):
            raise PermissionDenied("Only the offering's faculty or an HOD/Admin can change its content.")

    def perform_create(self, serializer):
        self._require_manage(serializer.validated_data["module"])
        serializer.save(uploaded_by=self.request.user)

    def perform_update(self, serializer):
        self._require_manage(serializer.instance.module)
        if "module" in serializer.validated_data:
            self._require_manage(serializer.validated_data["module"])
        serializer.save()

    def perform_destroy(self, instance):
        self._require_manage(instance.module)
        instance.delete()

    @action(detail=True, methods=["post"], url_path="view")
    def record_view(self, request, pk=None):
        """Students call this when they open a resource. Read-only for everyone else."""
        resource = self.get_object()
        student = _student_profile(request.user)
        if student is None:
            return Response({"recorded": False})
        view, created = ResourceView.objects.get_or_create(resource=resource, student=student)
        if not created:
            ResourceView.objects.filter(pk=view.pk).update(view_count=F("view_count") + 1, last_viewed_at=timezone.now())
        return Response({"recorded": True}, status=status.HTTP_200_OK)

    @action(detail=True, methods=["get"])
    def engagement(self, request, pk=None):
        resource = self.get_object()
        if not _can_manage(request.user, resource.module.offering):
            raise PermissionDenied("Only the offering's faculty or an HOD/Admin can see engagement.")
        registrations = (
            StudentCourseRegistration.objects
            .filter(offering=resource.module.offering, status=StudentCourseRegistration.STATUS_REGISTERED)
            .select_related("student__user")
        )
        views = {v.student_id: v for v in ResourceView.objects.filter(resource=resource)}
        rows = []
        for registration in registrations:
            student = registration.student
            view = views.get(student.id)
            rows.append({
                "student": student.id,
                "student_id": student.student_id,
                "student_name": student.user.get_full_name() or student.user.username,
                "viewed": view is not None,
                "view_count": view.view_count if view else 0,
                "last_viewed_at": view.last_viewed_at if view else None,
            })
        viewed = sum(1 for row in rows if row["viewed"])
        return Response({"registered": len(rows), "viewed": viewed, "students": rows})

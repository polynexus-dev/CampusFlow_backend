"""
Certificates & ID cards. Docs/college_gap_closure_plan.md §1.1.

  certificate-templates/          list (students: requestable only) / CRUD (College Admin)
  certificate-requests/           student requests; office approves (issues) or rejects
  issued-certificates/            office issues directly; anyone sees their own; /pdf/, /revoke/
  id-cards/                       bulk ID card PDF by section / batch / department / student_ids
  certificates/verify/<schema>/<token>/   public, unauthenticated verification
"""
import datetime

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django_tenants.utils import get_tenant_model, schema_context
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.certificates import CertificateRequest, CertificateTemplate, IssuedCertificate
from ..models.profile import StudentProfile
from ..permissions import IsCollegeAdmin, RequiresModule, get_user_group, is_college_admin
from ..services.certificates import (
    CertificateError, approve_request, certificate_pdf, ensure_default_templates,
    id_cards_pdf, issue_certificate, verification_path,
)
from ..services.notifications import notify_user
from ..services.rbac import can_perform, scope_students

CERT_PERMS = [IsAuthenticated, RequiresModule("certificates")]


def _student_profile(user):
    return getattr(user, "student_profile", None)


def _is_office_user(user):
    """Anyone holding the module who isn't a student/guardian and may change records."""
    if is_college_admin(user):
        return True
    if _student_profile(user) is not None or get_user_group(user) in ("student", "guardian"):
        return False
    return can_perform(user, "certificates", "change")


def _require_office(user):
    if not _is_office_user(user):
        raise PermissionDenied("Only the college office can do this.")


def _scoped_students(user):
    return scope_students(StudentProfile.objects.all(), user)


# ── Serializers ─────────────────────────────────────────────────────────────

class CertificateTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = CertificateTemplate
        fields = [
            "id", "name", "cert_type", "title", "body_text", "requires_approval",
            "requires_final_clearance", "student_can_request", "is_active", "created_at", "updated_at",
        ]


class IssuedCertificateSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source="template.name", read_only=True)
    cert_type = serializers.CharField(source="template.cert_type", read_only=True)
    student_name = serializers.SerializerMethodField()
    student_display_id = serializers.CharField(source="student.student_id", read_only=True)
    issued_by_name = serializers.SerializerMethodField()
    verify_path = serializers.SerializerMethodField()

    class Meta:
        model = IssuedCertificate
        fields = [
            "id", "template", "template_name", "cert_type", "student", "student_name", "student_display_id",
            "certificate_number", "purpose", "extra_context", "rendered_title", "rendered_body",
            "issued_by", "issued_by_name", "issued_at", "is_revoked", "revoked_reason", "revoked_at",
            "verify_path",
        ]
        read_only_fields = [
            "certificate_number", "rendered_title", "rendered_body", "issued_by", "issued_at",
            "is_revoked", "revoked_reason", "revoked_at",
        ]

    def get_student_name(self, obj):
        return obj.student.user.get_full_name() or obj.student.user.username

    def get_issued_by_name(self, obj):
        return obj.issued_by.get_full_name() if obj.issued_by else None

    def get_verify_path(self, obj):
        return verification_path(obj)


class CertificateRequestSerializer(serializers.ModelSerializer):
    template_name = serializers.CharField(source="template.name", read_only=True)
    student_name = serializers.SerializerMethodField()
    student_display_id = serializers.CharField(source="student.student_id", read_only=True)
    issued_certificate_number = serializers.CharField(
        source="issued_certificate.certificate_number", read_only=True, default=None,
    )

    class Meta:
        model = CertificateRequest
        fields = [
            "id", "template", "template_name", "student", "student_name", "student_display_id",
            "purpose", "status", "remarks", "reviewed_by", "reviewed_at",
            "issued_certificate", "issued_certificate_number", "created_at",
        ]
        read_only_fields = ["status", "remarks", "reviewed_by", "reviewed_at", "issued_certificate"]
        extra_kwargs = {"student": {"required": False}}

    def get_student_name(self, obj):
        return obj.student.user.get_full_name() or obj.student.user.username


# ── Templates ───────────────────────────────────────────────────────────────

class CertificateTemplateViewSet(viewsets.ModelViewSet):
    serializer_class = CertificateTemplateSerializer
    permission_classes = CERT_PERMS

    def get_permissions(self):
        if self.action in ("list", "retrieve"):
            return [permission() for permission in CERT_PERMS]
        return [IsAuthenticated(), IsCollegeAdmin(), RequiresModule("certificates")()]

    def get_queryset(self):
        ensure_default_templates()
        qs = CertificateTemplate.objects.all()
        if not _is_office_user(self.request.user):
            qs = qs.filter(is_active=True, student_can_request=True)
        return qs

    def perform_destroy(self, instance):
        # Issued certificates PROTECT their template; retire it instead.
        instance.is_active = False
        instance.save(update_fields=["is_active"])


# ── Requests ────────────────────────────────────────────────────────────────

class CertificateRequestViewSet(viewsets.ModelViewSet):
    serializer_class = CertificateRequestSerializer
    permission_classes = CERT_PERMS
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = CertificateRequest.objects.select_related(
            "template", "student__user", "issued_certificate",
        )
        student = _student_profile(user)
        if student is not None:
            return qs.filter(student=student)
        _require_office(user)
        qs = qs.filter(student__in=_scoped_students(user))
        if self.request.query_params.get("status"):
            qs = qs.filter(status=self.request.query_params["status"])
        return qs

    def perform_create(self, serializer):
        user = self.request.user
        template = serializer.validated_data["template"]
        student = _student_profile(user)
        if student is None:
            raise PermissionDenied("Only students raise certificate requests; the office issues directly.")
        if not (template.is_active and template.student_can_request):
            raise serializers.ValidationError({"template": "This certificate can't be requested online."})
        if CertificateRequest.objects.filter(
            student=student, template=template, status=CertificateRequest.STATUS_PENDING,
        ).exists():
            raise serializers.ValidationError({"template": "You already have a pending request for this certificate."})
        cert_request = serializer.save(student=student)

        if not template.requires_approval:
            try:
                approve_request(cert_request, reviewer=None)
            except CertificateError:
                # e.g. clearance pending: leave it for the office to handle.
                pass

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        _require_office(request.user)
        cert_request = self.get_object()
        try:
            certificate = approve_request(
                cert_request, reviewer=request.user,
                extra_context=request.data.get("extra_context") or {},
                remarks=request.data.get("remarks", ""),
            )
        except CertificateError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        notify_user(
            cert_request.student.user, f"{cert_request.template.name} issued",
            body=f"Certificate {certificate.certificate_number} is ready to download.",
            category="certificate_issued", data={"certificate_id": certificate.id},
        )
        return Response(IssuedCertificateSerializer(certificate).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        _require_office(request.user)
        cert_request = self.get_object()
        if cert_request.status != CertificateRequest.STATUS_PENDING:
            return Response({"error": f"This request is already {cert_request.status}."}, status=status.HTTP_400_BAD_REQUEST)
        remarks = (request.data.get("remarks") or "").strip()
        if not remarks:
            return Response({"error": "remarks is required when rejecting."}, status=status.HTTP_400_BAD_REQUEST)
        cert_request.status = CertificateRequest.STATUS_REJECTED
        cert_request.remarks = remarks
        cert_request.reviewed_by = request.user
        cert_request.reviewed_at = timezone.now()
        cert_request.save(update_fields=["status", "remarks", "reviewed_by", "reviewed_at"])
        notify_user(
            cert_request.student.user, f"{cert_request.template.name} request rejected", body=remarks,
            category="certificate_rejected", data={"request_id": cert_request.id},
        )
        return Response(CertificateRequestSerializer(cert_request).data)


# ── Issued certificates ─────────────────────────────────────────────────────

class IssuedCertificateViewSet(viewsets.ModelViewSet):
    serializer_class = IssuedCertificateSerializer
    permission_classes = CERT_PERMS
    http_method_names = ["get", "post", "head", "options"]

    def get_queryset(self):
        user = self.request.user
        qs = IssuedCertificate.objects.select_related("template", "student__user", "issued_by")
        student = _student_profile(user)
        if student is not None:
            return qs.filter(student=student)
        _require_office(user)
        qs = qs.filter(student__in=_scoped_students(user))
        params = self.request.query_params
        if params.get("student"):
            qs = qs.filter(student_id=params["student"])
        if params.get("template"):
            qs = qs.filter(template_id=params["template"])
        return qs

    def create(self, request, *args, **kwargs):
        """Direct issue by the office: {template, student, purpose?, extra_context?}."""
        _require_office(request.user)
        template = get_object_or_404(CertificateTemplate, pk=request.data.get("template"))
        student = get_object_or_404(_scoped_students(request.user), pk=request.data.get("student"))
        extra_context = request.data.get("extra_context") or {}
        if not isinstance(extra_context, dict):
            return Response({"error": "extra_context must be an object."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            certificate = issue_certificate(
                template, student, issued_by=request.user,
                purpose=request.data.get("purpose", ""), extra_context=extra_context,
            )
        except CertificateError as exc:
            return Response({"error": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(self.get_serializer(certificate).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"])
    def pdf(self, request, pk=None):
        certificate = self.get_object()
        verify_url = request.build_absolute_uri(verification_path(certificate))
        response = HttpResponse(certificate_pdf(certificate, verify_url), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{certificate.certificate_number}.pdf"'
        return response

    @action(detail=True, methods=["post"])
    def revoke(self, request, pk=None):
        if not is_college_admin(request.user):
            return Response({"error": "Only a College Admin can revoke a certificate."}, status=status.HTTP_403_FORBIDDEN)
        certificate = self.get_object()
        reason = (request.data.get("reason") or "").strip()
        if not reason:
            return Response({"error": "reason is required."}, status=status.HTTP_400_BAD_REQUEST)
        certificate.is_revoked = True
        certificate.revoked_reason = reason
        certificate.revoked_at = timezone.now()
        certificate.save(update_fields=["is_revoked", "revoked_reason", "revoked_at"])
        return Response(self.get_serializer(certificate).data)


# ── ID cards ────────────────────────────────────────────────────────────────

class StudentIDCardsView(APIView):
    """
    GET /id-cards/?section=<id>|batch=<id>|department=<id>|students=1,2,3[&valid_until=YYYY-MM-DD]
    A student calling it with no filter gets their own card.
    """
    permission_classes = [IsAuthenticated, IsNotDemoTenant, RequiresModule("certificates")]

    def get(self, request):
        params = request.query_params
        own = _student_profile(request.user)
        if own is not None:
            students = [own]
        else:
            _require_office(request.user)
            qs = _scoped_students(request.user).select_related("user", "department")
            filtered = False
            for param, lookup in (("section", "section_id"), ("batch", "batch_id"), ("department", "department_id")):
                if params.get(param):
                    qs = qs.filter(**{lookup: params[param]})
                    filtered = True
            if params.get("students"):
                ids = [value for value in params["students"].split(",") if value.strip().isdigit()]
                qs = qs.filter(pk__in=ids)
                filtered = True
            if not filtered:
                return Response(
                    {"error": "Pass section, batch, department or students to choose whose cards to print."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            students = list(qs.order_by("student_id")[:500])

        valid_until = None
        if params.get("valid_until"):
            try:
                valid_until = datetime.date.fromisoformat(params["valid_until"])
            except ValueError:
                return Response({"error": "valid_until must be YYYY-MM-DD."}, status=status.HTTP_400_BAD_REQUEST)

        response = HttpResponse(id_cards_pdf(students, valid_until=valid_until), content_type="application/pdf")
        response["Content-Disposition"] = 'inline; filename="id-cards.pdf"'
        return response


# ── Public verification ─────────────────────────────────────────────────────

class CertificateVerifyThrottle(ScopedRateThrottle):
    scope = "certificate_verify"


class CertificateVerifyView(APIView):
    """
    GET /certificates/verify/<schema>/<token>/ — no login. What a bank or
    employer sees after scanning the QR: enough to confirm the certificate is
    genuine, and nothing more (no DOB, no contact details).
    """
    permission_classes = [AllowAny]
    authentication_classes = []
    throttle_classes = [CertificateVerifyThrottle]

    def get(self, request, schema, token):
        tenant = get_tenant_model().objects.filter(schema_name=schema, is_active=True).first()
        if tenant is None or schema == "public":
            return Response({"valid": False, "error": "Certificate not found."}, status=status.HTTP_404_NOT_FOUND)
        with schema_context(schema):
            certificate = (
                IssuedCertificate.objects.select_related("template", "student__user", "student__department")
                .filter(verification_token=token).first()
            )
            if certificate is None:
                return Response({"valid": False, "error": "Certificate not found."}, status=status.HTTP_404_NOT_FOUND)
            student = certificate.student
            return Response({
                "valid": not certificate.is_revoked,
                "status": "revoked" if certificate.is_revoked else "valid",
                "institution": tenant.name,
                "certificate_number": certificate.certificate_number,
                "certificate_type": certificate.template.get_cert_type_display(),
                "title": certificate.rendered_title,
                "student_name": student.user.get_full_name() or student.user.username,
                "student_id": student.student_id,
                "department": student.department.name if student.department else None,
                "issued_at": certificate.issued_at,
                "revoked_at": certificate.revoked_at,
            })

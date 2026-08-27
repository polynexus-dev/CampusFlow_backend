"""
AQAR/SSR content completeness — CRUD + reporting for the four new models in
models/aqar_ssr.py, plus the 5-year audited-financials coverage report that
needs no new model at all (see AuditedFinancialsCoverageView below).
"""
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.aqar_ssr import (
    AccreditationSubmission, FacultyResearchOutput, InstitutionalEvent, StudentFeedback,
)
from ..models.compliance import ComplianceCertificate, ComplianceCertificateType
from ..models.finance import FinancialYear
from ..permissions import IsFacultyOrAbove, IsHMOrAbove, IsSaaSOrCollegeAdmin, RequiresModule
from ..serializers import (
    AccreditationSubmissionSerializer, FacultyResearchOutputSerializer,
    InstitutionalEventSerializer, StudentFeedbackSerializer,
)
from .compliance import _accreditation_xlsx_response

COMPLIANCE_ADMIN_PERMS = [IsAuthenticated, IsSaaSOrCollegeAdmin, RequiresModule("compliance-center")]

AUDITED_FINANCIAL_STATEMENT_TYPE_NAME = "Audited Financial Statement"
TRAILING_FINANCIAL_YEARS = 5


class FacultyResearchOutputViewSet(viewsets.ModelViewSet):
    """Real per-record publications/grants/patents, replacing the old
    single generic 'faculty publication link' evidence pointer."""
    queryset = FacultyResearchOutput.objects.select_related("faculty__user", "financial_year").all()
    serializer_class = FacultyResearchOutputSerializer
    permission_classes = [IsAuthenticated, IsFacultyOrAbove, IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        faculty = self.request.query_params.get("faculty")
        financial_year = self.request.query_params.get("financial_year")
        output_type = self.request.query_params.get("output_type")
        if faculty:
            qs = qs.filter(faculty_id=faculty)
        if financial_year:
            qs = qs.filter(financial_year_id=financial_year)
        if output_type:
            qs = qs.filter(output_type=output_type)
        return qs


class StudentFeedbackViewSet(viewsets.ModelViewSet):
    """
    Filing is open to any authenticated user (a student submitting their own
    feedback) — the same "create is open, everything else is gated" split
    CommitteeComplaintViewSet uses, including that split's consequence: a
    student who files feedback cannot browse it back afterward (the same is
    true of a CommitteeComplaint complainant who isn't a committee member).
    Reviewing and recording action is Faculty+ only via
    RecordStudentFeedbackActionView below (status/action_taken/
    action_taken_date are read-only on this serializer).
    """
    queryset = StudentFeedback.objects.select_related(
        "student__user", "department", "course", "financial_year",
    ).all()
    serializer_class = StudentFeedbackSerializer

    def get_permissions(self):
        if self.action == "create":
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsFacultyOrAbove()]

    def get_queryset(self):
        qs = super().get_queryset()
        financial_year = self.request.query_params.get("financial_year")
        department = self.request.query_params.get("department")
        status_filter = self.request.query_params.get("status")
        if financial_year:
            qs = qs.filter(financial_year_id=financial_year)
        if department:
            qs = qs.filter(department_id=department)
        if status_filter:
            qs = qs.filter(status=status_filter)
        return qs

    def perform_create(self, serializer):
        is_anonymous = serializer.validated_data.get("is_anonymous", False)
        student_profile = getattr(self.request.user, "student_profile", None)
        serializer.save(student=None if is_anonymous else student_profile)


class RecordStudentFeedbackActionView(APIView):
    """POST /api/student-feedback/<pk>/record-action/ — {action_taken}
    Faculty+ only, mirroring CommitteeComplaint's action_taken field being
    the committee's to fill in, not the complainant's."""
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def post(self, request, pk):
        feedback = StudentFeedback.objects.filter(pk=pk).first()
        if not feedback:
            return Response({"error": "Feedback not found."}, status=status.HTTP_404_NOT_FOUND)
        action_text = (request.data.get("action_taken") or "").strip()
        if not action_text:
            return Response({"error": "action_taken is required."}, status=status.HTTP_400_BAD_REQUEST)
        feedback.record_action(action_text)
        return Response(StudentFeedbackSerializer(feedback).data, status=status.HTTP_200_OK)


class StudentFeedbackActionTakenReportView(APIView):
    """
    GET /api/compliance-center/reports/student-feedback-action-taken/?financial_year=<id>
    Status counts + the action-taken table itself — the report half of
    "Student feedback + action-taken report".
    """
    permission_classes = COMPLIANCE_ADMIN_PERMS

    def get(self, request):
        financial_year_id = request.query_params.get("financial_year")
        feedback_qs = StudentFeedback.objects.select_related("department", "course", "financial_year")
        if financial_year_id:
            feedback_qs = feedback_qs.filter(financial_year_id=financial_year_id)

        counts = {choice: feedback_qs.filter(status=choice).count() for choice, _ in StudentFeedback.STATUS_CHOICES}
        rows = [
            [
                f.financial_year.label, f.department.name if f.department else "Institution-wide",
                f.category, f.get_status_display(), f.action_taken or "—",
            ]
            for f in feedback_qs.order_by("-filed_date")
        ]

        if (request.query_params.get("export") or "").lower() == "xlsx":
            return _accreditation_xlsx_response(
                "student_feedback_action_taken.xlsx",
                [
                    ("Status Summary", ["Status", "Count"],
                     [[dict(StudentFeedback.STATUS_CHOICES)[k], v] for k, v in counts.items()]),
                    ("Feedback & Action Taken", ["Year", "Department", "Category", "Status", "Action Taken"], rows),
                ],
            )

        return Response({
            "total": feedback_qs.count(),
            "status_counts": counts,
            "feedback": [
                {
                    "id": f.id, "financial_year": f.financial_year.label,
                    "department": f.department.name if f.department else None,
                    "category": f.category, "status": f.status,
                    "action_taken": f.action_taken, "action_taken_date": f.action_taken_date,
                }
                for f in feedback_qs.order_by("-filed_date")
            ],
        })


class InstitutionalEventViewSet(viewsets.ModelViewSet):
    """Logged as they happen — see models/aqar_ssr.py's InstitutionalEvent
    docstring for why this has no evidence field of its own (EvidenceItem's
    generic linked_object pointer covers that)."""
    queryset = InstitutionalEvent.objects.select_related("department", "financial_year", "created_by").all()
    serializer_class = InstitutionalEventSerializer
    permission_classes = [IsAuthenticated, IsFacultyOrAbove, IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        financial_year = self.request.query_params.get("financial_year")
        department = self.request.query_params.get("department")
        if financial_year:
            qs = qs.filter(financial_year_id=financial_year)
        if department:
            qs = qs.filter(department_id=department)
        return qs

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)


class AccreditationSubmissionViewSet(viewsets.ModelViewSet):
    """IIQA + DVV clarification tracking — IQAC/Admin tooling, same bar as
    AccreditationCriterionViewSet."""
    queryset = AccreditationSubmission.objects.select_related(
        "financial_year", "prepared_by", "signed_off_by",
    ).all()
    serializer_class = AccreditationSubmissionSerializer
    permission_classes = COMPLIANCE_ADMIN_PERMS + [IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        financial_year = self.request.query_params.get("financial_year")
        submission_type = self.request.query_params.get("submission_type")
        if financial_year:
            qs = qs.filter(financial_year_id=financial_year)
        if submission_type:
            qs = qs.filter(submission_type=submission_type)
        return qs

    def perform_create(self, serializer):
        serializer.save(prepared_by=self.request.user)


class SubmitAccreditationSubmissionView(APIView):
    """POST /api/accreditation-submissions/<pk>/submit/ — Draft -> Submitted."""
    permission_classes = COMPLIANCE_ADMIN_PERMS

    def post(self, request, pk):
        submission = AccreditationSubmission.objects.filter(pk=pk).first()
        if not submission:
            return Response({"error": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)
        if submission.status != AccreditationSubmission.STATUS_DRAFT:
            return Response(
                {"error": f"Cannot submit an item that is already {submission.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        submission.submit()
        return Response(AccreditationSubmissionSerializer(submission).data)


class SignOffAccreditationSubmissionView(APIView):
    """POST /api/accreditation-submissions/<pk>/sign-off/ — Submitted -> Signed Off.
    Same HM-or-above bar as SignOffEvidenceItemView."""
    permission_classes = [IsAuthenticated, IsHMOrAbove, IsNotDemoTenant, RequiresModule("compliance-center")]

    def post(self, request, pk):
        submission = AccreditationSubmission.objects.filter(pk=pk).first()
        if not submission:
            return Response({"error": "Submission not found."}, status=status.HTTP_404_NOT_FOUND)
        if submission.status != AccreditationSubmission.STATUS_SUBMITTED:
            return Response({"error": "Only submitted items can be signed off."}, status=status.HTTP_400_BAD_REQUEST)
        submission.sign_off(request.user)
        return Response(AccreditationSubmissionSerializer(submission).data)


class AuditedFinancialsCoverageView(APIView):
    """
    GET /api/compliance-center/reports/audited-financials-coverage/
    No new model: matches the trailing 5 FinancialYear rows against
    ComplianceCertificate rows of type "Audited Financial Statement" scoped
    to that year, and flags whichever years have none on file — the exact
    "one certificate-vault upload per financial year, flag missing years
    automatically" the roadmap asks for.
    """
    permission_classes = COMPLIANCE_ADMIN_PERMS

    def get(self, request):
        cert_type = ComplianceCertificateType.objects.filter(name=AUDITED_FINANCIAL_STATEMENT_TYPE_NAME).first()
        trailing_years = list(FinancialYear.objects.order_by("-start_date")[:TRAILING_FINANCIAL_YEARS])

        rows = []
        for fy in trailing_years:
            certificate = None
            if cert_type:
                certificate = ComplianceCertificate.objects.filter(
                    certificate_type=cert_type, financial_year=fy,
                ).order_by("-uploaded_at").first()
            rows.append({
                "financial_year_id": fy.id,
                "financial_year_label": fy.label,
                "has_audited_statement": certificate is not None,
                "certificate_id": certificate.id if certificate else None,
                "uploaded_at": certificate.uploaded_at if certificate else None,
            })

        missing_years = [r["financial_year_label"] for r in rows if not r["has_audited_statement"]]

        if (request.query_params.get("export") or "").lower() == "xlsx":
            return _accreditation_xlsx_response(
                "audited_financials_coverage.xlsx",
                [
                    ("5-Year Audited Financials Coverage",
                     ["Financial Year", "Audited Statement on File?", "Uploaded At"],
                     [[r["financial_year_label"], "Yes" if r["has_audited_statement"] else "No", r["uploaded_at"]]
                      for r in rows]),
                ],
            )

        return Response({
            "certificate_type_exists": cert_type is not None,
            "years": rows,
            "missing_years": missing_years,
            "fully_covered": not missing_years and len(rows) == TRAILING_FINANCIAL_YEARS,
        })

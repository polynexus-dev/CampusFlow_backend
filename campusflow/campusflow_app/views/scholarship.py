from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated

from ..demo_guard import IsNotDemoTenant
from ..models.scholarship import StateScholarshipScheme, StudentScholarshipRecord
from ..serializers import StateScholarshipSchemeSerializer, StudentScholarshipRecordSerializer
from ..permissions import IsSaaSOrCollegeAdmin


class StateScholarshipSchemeViewSet(viewsets.ModelViewSet):
    """Catalog of state/central scholarship schemes the college's students draw on."""
    queryset = StateScholarshipScheme.objects.all()
    serializer_class = StateScholarshipSchemeSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]


class StudentScholarshipRecordViewSet(viewsets.ModelViewSet):
    """
    Reconciliation of state scholarships: sanctioned vs. disbursed vs. actually
    applied as a fee waiver, replacing the free-text
    StudentProfile.scholarship_fee_concession_details field with something
    the Fees module and a CA can actually total up.
    """
    queryset = StudentScholarshipRecord.objects.select_related("student", "scheme", "financial_year", "recorded_by").all()
    serializer_class = StudentScholarshipRecordSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin, IsNotDemoTenant]

    def get_queryset(self):
        qs = super().get_queryset()
        student = self.request.query_params.get("student")
        financial_year = self.request.query_params.get("financial_year")
        scheme = self.request.query_params.get("scheme")
        if student:
            qs = qs.filter(student_id=student)
        if financial_year:
            qs = qs.filter(financial_year_id=financial_year)
        if scheme:
            qs = qs.filter(scheme_id=scheme)
        return qs

    def perform_create(self, serializer):
        serializer.save(recorded_by=self.request.user)

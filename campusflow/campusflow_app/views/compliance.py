from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models.compliance import ComplianceCertificateType, ComplianceCertificate
from ..serializers import ComplianceCertificateTypeSerializer, ComplianceCertificateSerializer
from ..permissions import IsSaaSOrCollegeAdmin


class ComplianceCertificateTypeViewSet(viewsets.ModelViewSet):
    """
    Catalog of certificate categories (UGC Recognition, Fire NOC, AICTE EOA Letter, etc.)
    that populates the upload form's category dropdown. Admin-managed.
    """
    queryset = ComplianceCertificateType.objects.all().order_by('name')
    serializer_class = ComplianceCertificateTypeSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]


class ComplianceCertificateViewSet(viewsets.ModelViewSet):
    """
    The certificate vault itself — the manual "upload document" surface for
    certificates/licenses that can only ever be supplied by the college, never
    generated from system data (UGC recognition, Trust registration, AICTE EOA
    letter, Fire Safety NOC, previous NAAC certificate, etc.).
    """
    queryset = ComplianceCertificate.objects.select_related('certificate_type', 'uploaded_by').all()
    serializer_class = ComplianceCertificateSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def perform_create(self, serializer):
        serializer.save(uploaded_by=self.request.user)

from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models.valuation import ValuationSession, ScannedPaper
from ..serializers import ValuationSessionSerializer, ScannedPaperSerializer


class ValuationSessionViewSet(viewsets.ModelViewSet):
    queryset = ValuationSession.objects.all().order_by('-started_at')
    serializer_class = ValuationSessionSerializer
    permission_classes = [IsAuthenticated]


class ScannedPaperViewSet(viewsets.ModelViewSet):
    queryset = ScannedPaper.objects.all().order_by('-evaluated_at')
    serializer_class = ScannedPaperSerializer
    permission_classes = [IsAuthenticated]

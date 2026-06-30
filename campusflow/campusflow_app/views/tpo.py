from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models.tpo import RecruitmentDrive, PlacementApplication
from ..serializers import RecruitmentDriveSerializer, PlacementApplicationSerializer


class RecruitmentDriveViewSet(viewsets.ModelViewSet):
    queryset = RecruitmentDrive.objects.all().order_by('-drive_date')
    serializer_class = RecruitmentDriveSerializer
    permission_classes = [IsAuthenticated]


class PlacementApplicationViewSet(viewsets.ModelViewSet):
    queryset = PlacementApplication.objects.all().order_by('-applied_date')
    serializer_class = PlacementApplicationSerializer
    permission_classes = [IsAuthenticated]

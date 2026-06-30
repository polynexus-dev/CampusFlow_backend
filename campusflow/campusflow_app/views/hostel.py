from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models.hostel import Hostel, HostelRoom, HostelAllocation
from ..serializers import HostelSerializer, HostelRoomSerializer, HostelAllocationSerializer


class HostelViewSet(viewsets.ModelViewSet):
    queryset = Hostel.objects.all().order_by('-created_at')
    serializer_class = HostelSerializer
    permission_classes = [IsAuthenticated]


class HostelRoomViewSet(viewsets.ModelViewSet):
    queryset = HostelRoom.objects.all().order_by('room_number')
    serializer_class = HostelRoomSerializer
    permission_classes = [IsAuthenticated]


class HostelAllocationViewSet(viewsets.ModelViewSet):
    queryset = HostelAllocation.objects.all().order_by('-allocated_date')
    serializer_class = HostelAllocationSerializer
    permission_classes = [IsAuthenticated]

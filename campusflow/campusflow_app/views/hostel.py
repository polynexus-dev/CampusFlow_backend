from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models.hostel import Hostel, HostelRoom, HostelAllocation
from ..serializers import HostelSerializer, HostelRoomSerializer, HostelAllocationSerializer
from ..permissions import ManagedBy, RequiresModule

# Students hold 'hostel' to see their own room; only the Warden/Admins change records.
HOSTEL_PERMS = [IsAuthenticated, RequiresModule("hostel"), ManagedBy("Hostel Warden")]


class HostelViewSet(viewsets.ModelViewSet):
    queryset = Hostel.objects.all().order_by('-created_at')
    serializer_class = HostelSerializer
    permission_classes = HOSTEL_PERMS


class HostelRoomViewSet(viewsets.ModelViewSet):
    queryset = HostelRoom.objects.select_related('hostel').all().order_by('room_number')
    serializer_class = HostelRoomSerializer
    permission_classes = HOSTEL_PERMS


class HostelAllocationViewSet(viewsets.ModelViewSet):
    queryset = HostelAllocation.objects.select_related('student__user', 'room__hostel').all().order_by('-allocated_date')
    serializer_class = HostelAllocationSerializer
    permission_classes = HOSTEL_PERMS

    def get_queryset(self):
        qs = super().get_queryset()
        # A student sees only their own allocation, not every resident's room.
        student_profile = getattr(self.request.user, 'student_profile', None)
        if student_profile is not None:
            qs = qs.filter(student=student_profile)
        return qs


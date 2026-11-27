from rest_framework import viewsets, status
from rest_framework.response import Response
from rest_framework.permissions import BasePermission, IsAuthenticated, SAFE_METHODS
from django.db import transaction
from django.db.models import Count, F, Q
from django.utils import timezone

from ..models.hostel import Hostel, HostelRoom, HostelAllocation
from ..serializers import HostelSerializer, HostelRoomSerializer, HostelAllocationSerializer
from ..permissions import ManagedBy, RequiresModule, is_saas_or_college_admin, get_user_group

# Students hold 'hostel' to see their own room; Warden, Accounts Officer, Fee Counter, Admins can manage.
def can_manage_hostel(user):
    return (
        is_saas_or_college_admin(user) or
        get_user_group(user) in ('Hostel Warden', 'Accounts Officer', 'Fee Counter')
    )


class IsHostelManagerOrReadOnly(BasePermission):
    """
    Allows read permissions to any authenticated user with hostel module access (including students),
    but restricts writes (POST, PUT, PATCH, DELETE) to Hostel Warden, Accounts, Fee Counter, or Admins.
    """
    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return can_manage_hostel(request.user)


HOSTEL_PERMS = [IsAuthenticated, RequiresModule("hostel"), IsHostelManagerOrReadOnly]


class HostelViewSet(viewsets.ModelViewSet):
    """
    GET /api/hostels/
    POST /api/hostels/ (Single create, or bulk create hostel with rooms directly!)
    Query params:
      ?gender_type=Boys|Girls|Co-ed
      ?vacant_only=true (only hostels with vacant beds)
    """
    queryset = Hostel.objects.prefetch_related('rooms__allocations').all().order_by('-created_at')
    serializer_class = HostelSerializer
    permission_classes = HOSTEL_PERMS

    def get_queryset(self):
        qs = super().get_queryset()
        gender = self.request.query_params.get('gender_type')
        if gender:
            qs = qs.filter(gender_type__iexact=gender)

        vacant_only = self.request.query_params.get('vacant_only')
        if vacant_only and vacant_only.lower() in ('true', '1'):
            # Only hostels where total active allocations < total room capacity
            qs = qs.annotate(
                active_allocations_count=Count('rooms__allocations', filter=Q(rooms__allocations__status='Allocated'))
            )
            # Python filter on queryset to ensure exact bed headroom
            vacant_ids = [h.id for h in qs if h.vacant_beds > 0]
            qs = qs.filter(id__in=vacant_ids)
        return qs

    @transaction.atomic
    def perform_create(self, serializer):
        hostel = serializer.save()
        # If "rooms" list is provided inside payload, create them in bulk!
        rooms_data = self.request.data.get('rooms', [])
        if isinstance(rooms_data, list) and rooms_data:
            from decimal import Decimal
            for r in rooms_data:
                if isinstance(r, dict) and r.get('room_number'):
                    HostelRoom.objects.update_or_create(
                        hostel=hostel,
                        room_number=str(r['room_number']).strip(),
                        defaults={
                            'capacity': int(r.get('capacity', 4)),
                            'rent_per_semester': Decimal(str(r.get('rent_per_semester') or r.get('rent') or 25000.00)),
                        }
                    )


class HostelRoomViewSet(viewsets.ModelViewSet):
    """
    GET /api/hostel-rooms/
    Returns ALL rooms by default (both full and vacant).
    
    POST /api/hostel-rooms/
    Supports:
    1. Single room creation:
       {"hostel": 1, "room_number": "101", "capacity": 3, "rent_per_semester": "25000.00"}
    2. Bulk room creation:
       {
         "hostel": 1,
         "rooms": [
           {"room_number": "101", "capacity": 3, "rent_per_semester": "25000.00"},
           {"room_number": "102", "capacity": 3, "rent_per_semester": "25000.00"},
           {"room_number": "103", "capacity": 2, "rent_per_semester": "30000.00"}
         ]
       }
    """
    queryset = HostelRoom.objects.select_related('hostel').prefetch_related('allocations__student__user').all().order_by('hostel__name', 'room_number')
    serializer_class = HostelRoomSerializer
    permission_classes = HOSTEL_PERMS

    def get_queryset(self):
        qs = super().get_queryset()
        params = self.request.query_params

        hostel_id = params.get('hostel')
        if hostel_id:
            qs = qs.filter(hostel_id=hostel_id)

        gender = params.get('gender_type')
        if gender:
            qs = qs.filter(hostel__gender_type__iexact=gender)

        search = params.get('search')
        if search:
            qs = qs.filter(room_number__icontains=search.strip())

        # If vacant_only=true is explicitly requested (e.g. from the allocation screen):
        vacant_only = params.get('vacant_only')
        if vacant_only and vacant_only.lower() in ('true', '1'):
            # Only rooms where active allocations count is less than capacity
            qs = qs.annotate(
                active_count=Count('allocations', filter=Q(allocations__status='Allocated'))
            ).filter(active_count__lt=F('capacity'))

        return qs

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        # Check if bulk payload with "rooms" list is passed
        if "rooms" in request.data:
            hostel_id = request.data.get("hostel") or request.data.get("hostel_id")
            rooms_list = request.data.get("rooms", [])

            if not hostel_id:
                return Response({"hostel": ["Hostel ID is required for bulk room assignment."]}, status=status.HTTP_400_BAD_REQUEST)

            try:
                hostel = Hostel.objects.get(pk=hostel_id)
            except Hostel.DoesNotExist:
                return Response({"hostel": ["Hostel not found."]}, status=status.HTTP_404_NOT_FOUND)

            if not isinstance(rooms_list, list) or not rooms_list:
                return Response({"rooms": ["A non-empty list of rooms is required."]}, status=status.HTTP_400_BAD_REQUEST)

            from decimal import Decimal
            created_rooms = []
            for r in rooms_list:
                room_num = str(r.get("room_number") or r.get("number") or "").strip()
                if not room_num:
                    continue
                cap = int(r.get("capacity", 4))
                rent = Decimal(str(r.get("rent_per_semester") or r.get("rent") or 25000.00))

                room_obj, _ = HostelRoom.objects.update_or_create(
                    hostel=hostel,
                    room_number=room_num,
                    defaults={
                        "capacity": cap,
                        "rent_per_semester": rent
                    }
                )
                created_rooms.append(room_obj)

            serializer = self.get_serializer(created_rooms, many=True)
            return Response({
                "message": f"Successfully created/updated {len(created_rooms)} rooms in {hostel.name}.",
                "hostel_id": hostel.id,
                "hostel_name": hostel.name,
                "rooms": serializer.data
            }, status=status.HTTP_201_CREATED)

        # Standard single create
        return super().create(request, *args, **kwargs)


class HostelAllocationViewSet(viewsets.ModelViewSet):
    """
    CRUD for Hostel Allocations.
    - Validates room capacity strictly (e.g. 4th student into capacity 3 returns 400 Bad Request).
    - Prevents double allocation for the same student.
    - Synchronizes room.occupied_beds atomically on allocate, vacate, and delete.
    """
    queryset = HostelAllocation.objects.select_related('student__user', 'room__hostel').all().order_by('-allocated_date')
    serializer_class = HostelAllocationSerializer
    permission_classes = HOSTEL_PERMS

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        student_profile = getattr(user, 'student_profile', None)

        # Students see only their own allocations
        if student_profile is not None and not can_manage_hostel(user):
            return qs.filter(student=student_profile)

        # Admin / Warden / Accountant filters
        params = self.request.query_params
        hostel_id = params.get('hostel')
        room_id = params.get('room')
        alloc_status = params.get('status')
        student_search = params.get('search')

        if hostel_id:
            qs = qs.filter(room__hostel_id=hostel_id)
        if room_id:
            qs = qs.filter(room_id=room_id)
        if alloc_status:
            qs = qs.filter(status=alloc_status)
        if student_search:
            s = student_search.strip()
            qs = qs.filter(
                Q(student__student_id__icontains=s) |
                Q(student__user__first_name__icontains=s) |
                Q(student__user__last_name__icontains=s) |
                Q(student__user__username__icontains=s) |
                Q(room__room_number__icontains=s)
            )
        return qs

    def _sync_room_occupancy(self, room):
        """Atomically counts active allocations and updates room.occupied_beds"""
        if room:
            active_count = room.allocations.filter(status='Allocated').count()
            room.occupied_beds = active_count
            room.save(update_fields=['occupied_beds'])

    @transaction.atomic
    def perform_create(self, serializer):
        allocation = serializer.save()
        self._sync_room_occupancy(allocation.room)

    @transaction.atomic
    def perform_update(self, serializer):
        previous_room = self.get_object().room
        allocation = serializer.save()

        # If status updated to 'Vacated', set vacated_date automatically
        if allocation.status == 'Vacated' and not allocation.vacated_date:
            allocation.vacated_date = timezone.localdate()
            allocation.save(update_fields=['vacated_date'])

        # Sync occupancy of current room
        self._sync_room_occupancy(allocation.room)
        # If room was changed during update, sync previous room too
        if previous_room and previous_room.id != allocation.room.id:
            self._sync_room_occupancy(previous_room)

    @transaction.atomic
    def perform_destroy(self, instance):
        room = instance.room
        instance.delete()
        self._sync_room_occupancy(room)


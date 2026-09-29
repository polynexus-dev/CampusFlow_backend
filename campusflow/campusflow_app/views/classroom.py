from django.conf import settings
from rest_framework import generics
from ..models.classroom import Classroom
from ..serializers import ClassroomSerializer, LocationValidationSerializer
from ..utils.geofence import point_in_boundary
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSaaSOrCollegeAdmin


def _check_location(classroom_id, latitude, longitude):
    """Shared by both endpoints below. Returns (payload, http_status)."""
    try:
        classroom = Classroom.objects.get(pk=classroom_id)
    except Classroom.DoesNotExist:
        return {"error": "Classroom not found"}, status.HTTP_404_NOT_FOUND
    if not classroom.boundary:
        return {"error": "This classroom has no boundary set yet."}, status.HTTP_400_BAD_REQUEST

    is_within, distance_m = point_in_boundary(
        float(latitude), float(longitude), classroom.boundary,
        buffer_m=getattr(settings, "GEOFENCE_BUFFER_METERS", 10),
    )
    return {
        "is_within": is_within,
        "distance_to_edge_m": distance_m,
        "message": "Present in classroom" if is_within else "Away from classroom",
    }, status.HTTP_200_OK


class ClassroomCreateView(generics.CreateAPIView):
    """Create a classroom. Only SaaS Admin or College Admins (Management/Administrator)."""
    queryset = Classroom.objects.all()
    serializer_class = ClassroomSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]


class ClassroomDetailView(generics.RetrieveUpdateAPIView):
    """GET any authenticated user; PATCH/PUT (e.g. to set the boundary) College Admins only."""
    queryset = Classroom.objects.all()
    serializer_class = ClassroomSerializer

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [IsAuthenticated(), IsSaaSOrCollegeAdmin()]


class CheckAttendanceView(APIView):
    """POST {latitude, longitude, classroom_id} -> is the point inside the room?"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        classroom_id = request.data.get('classroom_id')

        if latitude is None or longitude is None or classroom_id is None:
            return Response({'error': 'latitude, longitude and classroom_id are required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            float(latitude), float(longitude)
        except (TypeError, ValueError):
            return Response({'error': 'latitude and longitude must be numbers.'}, status=status.HTTP_400_BAD_REQUEST)

        payload, http_status = _check_location(classroom_id, latitude, longitude)
        return Response(payload, status=http_status)

    def get(self, request, *args, **kwargs):
        return Response({'detail': 'Method \"GET\" not allowed.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


class ClassroomListView(generics.ListCreateAPIView):
    queryset = Classroom.objects.all()
    serializer_class = ClassroomSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method == 'POST':
            return [IsAuthenticated(), IsSaaSOrCollegeAdmin()]
        return [IsAuthenticated()]


class ClassroomLocationValidationView(APIView):
    """POST {classroom_id, latitude, longitude} -> {is_within, distance_to_edge_m}"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = LocationValidationSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        data = serializer.validated_data
        payload, http_status = _check_location(data['classroom_id'], data['latitude'], data['longitude'])
        return Response(payload, status=http_status)

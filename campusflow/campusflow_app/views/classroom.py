from rest_framework import generics
from ..models.classroom import Classroom
from ..serializers import ClassroomSerializer, LocationValidationSerializer
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
# from django.contrib.gis.geos import Point  # Commented out - requires GDAL

from rest_framework.permissions import IsAuthenticated
from ..permissions import IsSaaSOrCollegeAdmin


class ClassroomCreateView(generics.CreateAPIView):
    """Create a classroom. Only SaaS Admin or College Admins (Management/Administrator)."""
    queryset = Classroom.objects.all()
    serializer_class = ClassroomSerializer
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]


class CheckAttendanceView(APIView):

    def post(self, request, *args, **kwargs):
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        classroom_id = request.data.get('classroom_id')

        if latitude is None or longitude is None or classroom_id is None:
            return Response({'error': 'latitude, longitude and classroom_id are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            classroom = Classroom.objects.get(pk=classroom_id)
        except Classroom.DoesNotExist:
            return Response({'error': 'Classroom not found'}, status=status.HTTP_404_NOT_FOUND)
        
        # Commented out - requires GDAL
        # user_location = Point(float(longitude), float(latitude), srid=4326)
        # if classroom.polygon.contains(user_location):
        #     return Response({'message': 'Present in classroom'})
        # else:
        #     return Response({'message': 'Away from classroom'})
        return Response({'message': 'Polygon check disabled (GDAL not available)'}, status=status.HTTP_501_NOT_IMPLEMENTED)

    def get(self, request, *args, **kwargs):
        return Response({'detail': 'Method \"GET\" not allowed.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


class ClassroomListView(APIView):
    def get(self, request, *args, **kwargs):
        classrooms = Classroom.objects.all()
        classroomData = []
        for classroom in classrooms:
            classroomData.append({
                'id': classroom.id,
                'name': classroom.name,
                # 'polygon': classroom.polygon.json,  # Commented out - requires GDAL
                'created_at': classroom.created_at,
            })
        return Response(classroomData)
    
class ClassroomLocationValidationView(APIView):
    def post(self, request, *args, **kwargs):
        serializer = LocationValidationSerializer(data=request.data)
        if serializer.is_valid():
            # Commented out - requires GDAL
            # classroom_id = serializer.validated_data['classroom_id']
            # latitude = serializer.validated_data['latitude']
            # longitude = serializer.validated_data['longitude']
            # point = Point(float(longitude), float(latitude), srid=4326)
            #
            # try:
            #     classroom = Classroom.objects.get(id=classroom_id)
            # except Classroom.DoesNotExist:
            #     return Response({'detail': 'Classroom not found.'}, status=status.HTTP_404_NOT_FOUND)
            #
            # # Perform point-in-polygon check
            # is_within = classroom.polygon.contains(point)
            # return Response({'is_within': is_within}, status=status.HTTP_200_OK)
            return Response({'detail': 'Location validation disabled (GDAL not available)'}, status=status.HTTP_501_NOT_IMPLEMENTED)
        
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
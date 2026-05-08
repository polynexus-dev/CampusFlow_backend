"""
Lecture Views
=============
Auth rules:
  - GET  (list/detail/by-classroom): Any authenticated user
  - POST (create):   Faculty, Department Head, Administrator, Management, SaaS Admin
                     → Students and Support Staff CANNOT create lectures
  - PUT  (update):   Same as create, plus Faculty can only update their OWN lectures
  - DELETE:          Faculty can delete their OWN lectures; College Admins can delete any
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

import random
import string
from ..models.lecture import Lecture
from ..serializers import LectureSerializer
from ..permissions import CanCreateLecture, get_user_group, is_saas_or_college_admin, is_saas_admin
from django.shortcuts import get_object_or_404

class LectureListCreateView(APIView):
    permission_classes = [IsAuthenticated, CanCreateLecture]

    def get(self, request):
        """List all lectures. Any authenticated user can view."""
        lectures = Lecture.objects.all().select_related('classroom')
        serializer = LectureSerializer(lectures, many=True)
        return Response(serializer.data)

    def post(self, request):
        """
        Create a lecture.
        Faculty, Department Head, Administrator, Management, SaaS Admin only.
        Students and Support Staff are blocked by CanCreateLecture.
        """
        serializer = LectureSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LectureDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_lecture(self, pk):
        try:
            return Lecture.objects.get(pk=pk)
        except Lecture.DoesNotExist:
            return None

    def _can_write(self, user, lecture=None):
        """
        College Admins and SaaS Admin can edit any lecture.
        Faculty and Department Heads can only edit lectures they created (if lecture has created_by).
        """
        if is_saas_admin(user):
            return True
        group = get_user_group(user)
        if group in ('Management', 'Administrator'):
            return True
        # Faculty / HOD can write only to lectures they own
        if group in ('Faculty', 'Department Head'):
            if lecture is None:
                return True  # creation check — lecture not yet existing
            # If lecture tracks creator, check ownership
            created_by = getattr(lecture, 'created_by', None)
            if created_by is None:
                return True  # no ownership tracking — allow
            return created_by == user
        return False

    def get(self, request, pk):
        """Get a single lecture. Any authenticated user."""
        lecture = self._get_lecture(pk)
        if not lecture:
            return Response({"error": "Lecture not found."}, status=status.HTTP_404_NOT_FOUND)
        serializer = LectureSerializer(lecture)
        return Response(serializer.data)

    def put(self, request, pk):
        """
        Update a lecture.
        Faculty/HOD: own lectures only.
        College Admins: any lecture.
        Students/Support Staff: blocked.
        """
        group = get_user_group(request.user)
        if not is_saas_admin(request.user) and group not in ('Management', 'Administrator', 'Department Head', 'Faculty'):
            return Response(
                {"error": "Students and Support Staff cannot modify lectures."},
                status=status.HTTP_403_FORBIDDEN
            )
        lecture = self._get_lecture(pk)
        if not lecture:
            return Response({"error": "Lecture not found."}, status=status.HTTP_404_NOT_FOUND)
        if not self._can_write(request.user, lecture):
            return Response(
                {"error": "You can only edit lectures you created."},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer = LectureSerializer(lecture, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def patch(self, request, pk):
        """Partial update — same rules as PUT."""
        group = get_user_group(request.user)
        if not is_saas_admin(request.user) and group not in ('Management', 'Administrator', 'Department Head', 'Faculty'):
            return Response(
                {"error": "Students and Support Staff cannot modify lectures."},
                status=status.HTTP_403_FORBIDDEN
            )
        lecture = self._get_lecture(pk)
        if not lecture:
            return Response({"error": "Lecture not found."}, status=status.HTTP_404_NOT_FOUND)
        if not self._can_write(request.user, lecture):
            return Response(
                {"error": "You can only edit lectures you created."},
                status=status.HTTP_403_FORBIDDEN
            )
        serializer = LectureSerializer(lecture, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, pk):
        """
        Delete a lecture.
        Faculty/HOD: own lectures only.
        College Admins: any lecture.
        Students/Support Staff: blocked.
        """
        group = get_user_group(request.user)
        if not is_saas_admin(request.user) and group not in ('Management', 'Administrator', 'Department Head', 'Faculty'):
            return Response(
                {"error": "Students and Support Staff cannot delete lectures."},
                status=status.HTTP_403_FORBIDDEN
            )
        lecture = self._get_lecture(pk)
        if not lecture:
            return Response({"error": "Lecture not found."}, status=status.HTTP_404_NOT_FOUND)
        if not self._can_write(request.user, lecture):
            return Response(
                {"error": "You can only delete lectures you created."},
                status=status.HTTP_403_FORBIDDEN
            )
        lecture.delete()
        return Response({"message": "Lecture deleted successfully."}, status=status.HTTP_204_NO_CONTENT)


class LectureByClassroomView(APIView):
    """List lectures for a specific classroom. Any authenticated user can view."""
    permission_classes = [IsAuthenticated]

    def get(self, request, classroom_id):
        lectures = Lecture.objects.filter(classroom_id=classroom_id).select_related('classroom')
        serializer = LectureSerializer(lectures, many=True)
        return Response(serializer.data)


class GenerateLectureCodeView(APIView):
    """
    Generate a random attendance code for a specific lecture.
    Only the assigned faculty or college admins can generate the code.
    """
    permission_classes = [IsAuthenticated]
    
    def _get_lecture(self, pk):
        return get_object_or_404(Lecture, pk=pk)


    def post(self, request, pk):
        lecture = self._get_lecture(pk)
        if not lecture:
            return Response({"error": "Lecture not found."}, status=status.HTTP_404_NOT_FOUND)

        # Permission check: Only the assigned faculty or admins
        user = request.user
        group = get_user_group(user)
        is_admin = is_saas_admin(user) or group in ('Management', 'Administrator')
        
        if not is_admin and lecture.faculty != user:
            return Response(
                {"error": "You are not authorized to generate a code for this lecture."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Faculty provides their current coordinates to set the geofence center
        lat = request.data.get('latitude')
        lon = request.data.get('longitude')

        if not lat or not lon:
            return Response(
                {"error": "Latitude and Longitude are required to generate an attendance geofence."},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Generate a random 6-character code
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        # Save code and geofence center to the lecture
        lecture.code = code
        lecture.latitude = lat
        lecture.longitude = lon
        lecture.save()

        # --- NEW: Sync location back to the Classroom ---
        classroom = lecture.classroom
        if classroom:
            if not classroom.main_entry_location:
                # Create a new Location record for this classroom
                from ..models.location import Location
                loc_id = f"auto_{classroom.name.replace(' ', '_')}_{lat}_{lon}"
                new_loc = Location.objects.create(
                    location_id=loc_id,
                    name=f"{classroom.name} (Auto-Registered)",
                    latitude=lat,
                    longitude=lon,
                    geofence_radius_meters=50,
                    is_classroom_entry=True
                )
                classroom.main_entry_location = new_loc
                classroom.save()
            else:
                # Update the existing location
                loc = classroom.main_entry_location
                loc.latitude = lat
                loc.longitude = lon
                loc.save()

        return Response({
            "message": "Attendance code generated successfully.",
            "code": code,
            "geofence_center": {"lat": lat, "lon": lon}
        }, status=status.HTTP_200_OK)

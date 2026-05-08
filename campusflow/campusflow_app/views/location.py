"""
Location Views
==============
Auth rules:
  - GET  (list all):  Any authenticated user (needed for QR scan context)
  - POST (create):    Only SaaS Admin or College Admins (Management/Administrator)
                      → Faculty, Students, Support Staff CANNOT create locations
  - DELETE:           Only SaaS Admin or College Admins
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from ..models.location import Location
from ..models.department import Department
from django.http import JsonResponse
from ..permissions import IsSaaSOrCollegeAdmin

class LocationDetailView(APIView):
    """
    GET  → Any authenticated user (read locations for QR scanning context).
    POST → SaaS Admin or College Admins only (create new check-in points).
    """
    permission_classes = [permissions.IsAuthenticated]

    def _can_write(self, user):
        from ..permissions import is_saas_or_college_admin
        return is_saas_or_college_admin(user)

    def post(self, request):
        """Create a new location/QR check-in point. College Admins and SaaS Admin only."""
        if not self._can_write(request.user):
            return Response(
                {"error": "Only College Admins (Management/Administrator) or SaaS Admin can create locations."},
                status=status.HTTP_403_FORBIDDEN
            )

        name = request.data.get('name')
        latitude = request.data.get('latitude')
        longitude = request.data.get('longitude')
        geofence_radius_meters = request.data.get('geofence_radius_meters', 50)
        is_premises_entry = request.data.get('is_premises_entry', False)
        is_classroom_entry = request.data.get('is_classroom_entry', False)
        department_owner_id = request.data.get('department_owner_id', None)

        if not name or not latitude or not longitude:
            return Response(
                {"error": "Missing required fields: name, latitude, longitude"},
                status=status.HTTP_400_BAD_REQUEST
            )

        location_id_parts = [
            str(department_owner_id) if department_owner_id else "none",
            name.replace(" ", "_"),
            str(latitude),
            str(longitude)
        ]
        location_id = "_".join(location_id_parts)

        try:
            department_owner = None
            if department_owner_id:
                department_owner = Department.objects.get(id=department_owner_id)

            location = Location.objects.create(
                location_id=location_id,
                name=name,
                latitude=latitude,
                longitude=longitude,
                geofence_radius_meters=geofence_radius_meters,
                is_premises_entry=is_premises_entry,
                is_classroom_entry=is_classroom_entry,
                department_owner=department_owner
            )
            return Response(
                {
                    "message": "Location created successfully.",
                    "id": location.id,
                    "location_id": location.location_id
                },
                status=status.HTTP_201_CREATED
            )
        except Department.DoesNotExist:
            return Response({"error": "Department not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self, request):
        """List all locations. Any authenticated user can view."""
        locations = Location.objects.all()
        if not locations.exists():
            return Response({"error": "No locations found."}, status=status.HTTP_404_NOT_FOUND)

        data = [{
            "id": loc.id,
            "location_id": loc.location_id,
            "name": loc.name,
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "geofence_radius_meters": loc.geofence_radius_meters,
            "is_premises_entry": loc.is_premises_entry,
            "is_classroom_entry": loc.is_classroom_entry,
            "department_owner_id": loc.department_owner.id if loc.department_owner else None,
            "department_owner_name": loc.department_owner.name if loc.department_owner else None,
        } for loc in locations]

        return JsonResponse(data, safe=False, status=200)

    def delete(self, request):
        """Delete a location by location_id. College Admins and SaaS Admin only."""
        if not self._can_write(request.user):
            return Response(
                {"error": "Only College Admins or SaaS Admin can delete locations."},
                status=status.HTTP_403_FORBIDDEN
            )
        location_id = request.data.get('location_id')
        if not location_id:
            return Response({"error": "location_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            loc = Location.objects.get(location_id=location_id)
            loc.delete()
            return Response({"message": "Location deleted."}, status=status.HTTP_204_NO_CONTENT)
        except Location.DoesNotExist:
            return Response({"error": "Location not found."}, status=status.HTTP_404_NOT_FOUND)

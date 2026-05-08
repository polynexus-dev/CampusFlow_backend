"""
Department Views
================
Auth rules:
  - GET  (list/detail): Any authenticated user (all roles can see departments)
  - POST (create):      SaaS Admin OR College Admin (Management/Administrator)
  - PUT/PATCH (update): SaaS Admin OR College Admin (Management/Administrator)
  - DELETE:             SaaS Admin OR College Admin (Management/Administrator)

The department is the gatekeeper for all user creation:
  → No departments = no Faculty/Student/HOD can be created.
"""

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.contrib.auth.models import User

from ..models.department import Department
from ..permissions import IsSaaSOrCollegeAdmin, is_saas_or_college_admin


class DepartmentView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _can_write(self, user):
        """Only SaaS Admin or College Admin (Management/Administrator) may write."""
        return is_saas_or_college_admin(user)

    def post(self, request):
        """Create a new department. Requires SaaS Admin or College Admin."""
        if not self._can_write(request.user):
            return Response(
                {"error": "Only SaaS Admin or College Admins (Management/Administrator) can create departments."},
                status=status.HTTP_403_FORBIDDEN
            )

        name = request.data.get('name')
        code = request.data.get('code')
        email = request.data.get('email')
        phone_number = request.data.get('phone_number')
        description = request.data.get('description')
        department_status = request.data.get('status', 'Active')
        remarks = request.data.get('remarks')
        accreditation_status = request.data.get('accreditation_status')
        date_established = request.data.get('date_established')

        if not name or not code:
            return Response({"error": "Name and code are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            department = Department.objects.create(
                name=name,
                code=code,
                email=email,
                phone_number=phone_number,
                description=description,
                status=department_status,
                remarks=remarks,
                accreditation_status=accreditation_status,
                date_established=date_established,
                created_by=request.user,
            )
            return Response({
                "id": department.id,
                "name": department.name,
                "code": department.code,
                "hod_id": department.hod.id if department.hod else None,
                "email": department.email,
                "phone_number": department.phone_number,
                "description": department.description,
                "status": department.status,
                "remarks": department.remarks,
                "accreditation_status": department.accreditation_status,
                "date_established": department.date_established,
                "created_by": request.user.username,
            }, status=status.HTTP_201_CREATED)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def get(self, request):
        """List all departments. Any authenticated user can view."""
        try:
            departments = Department.objects.all()
            data = [{
                "id": dept.id,
                "name": dept.name,
                "code": dept.code,
                "hod_id": dept.hod.id if getattr(dept, 'hod', None) else None,
                "hod_name": (
                    f"{dept.hod.first_name} {dept.hod.last_name}".strip()
                    if getattr(dept, 'hod', None) else None
                ),
                "email": dept.email,
                "phone_number": dept.phone_number,
                "description": dept.description,
                "status": dept.status,
                "remarks": dept.remarks,
                "accreditation_status": dept.accreditation_status,
                "date_established": dept.date_established,
            } for dept in departments]
            return Response(data, status=status.HTTP_200_OK)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request):
        """Delete ALL departments. Requires SaaS Admin or College Admin."""
        if not self._can_write(request.user):
            return Response(
                {"error": "Only SaaS Admin or College Admins can delete departments."},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            Department.objects.all().delete()
            return Response({"message": "All departments deleted successfully."}, status=status.HTTP_204_NO_CONTENT)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class DepartmentDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def _can_write(self, user):
        return is_saas_or_college_admin(user)

    def get(self, request, pk):
        """Retrieve a specific department. Any authenticated user."""
        try:
            department = Department.objects.get(pk=pk)
            return Response({
                "id": department.id,
                "name": department.name,
                "code": department.code,
                "hod_id": department.hod.id if getattr(department, 'hod', None) else None,
                "hod_name": (
                    f"{department.hod.first_name} {department.hod.last_name}".strip()
                    if getattr(department, 'hod', None) else None
                ),
                "email": department.email,
                "phone_number": department.phone_number,
                "description": department.description,
                "status": department.status,
                "remarks": department.remarks,
                "accreditation_status": department.accreditation_status,
                "date_established": department.date_established,
            }, status=status.HTTP_200_OK)
        except Department.DoesNotExist:
            return Response({"error": "Department not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def post(self, request, pk):
        """Update a specific department. Requires SaaS Admin or College Admin."""
        if not self._can_write(request.user):
            return Response(
                {"error": "Only SaaS Admin or College Admins can update departments."},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            department = Department.objects.get(pk=pk)
            department.name = request.data.get('name', department.name)
            department.code = request.data.get('code', department.code)
            hod_id = request.data.get('hod_id', department.hod.id if getattr(department, 'hod', None) else None)
            department.email = request.data.get('email', department.email)
            department.phone_number = request.data.get('phone_number', department.phone_number)
            department.description = request.data.get('description', department.description)
            department.status = request.data.get('status', department.status)
            department.remarks = request.data.get('remarks', department.remarks)
            department.accreditation_status = request.data.get('accreditation_status', department.accreditation_status)
            department.date_established = request.data.get('date_established', department.date_established)
            department.updated_by = request.user

            if hod_id is not None:
                try:
                    hod = User.objects.get(pk=hod_id)
                    # Validate that the HOD user is actually Faculty or Department Head
                    hod_group = hod.groups.first().name if hod.groups.exists() else None
                    if hod_group not in ('Faculty', 'Department Head'):
                        return Response(
                            {"error": "HOD must be a Faculty or Department Head user."},
                            status=status.HTTP_400_BAD_REQUEST
                        )
                    department.hod = hod
                except User.DoesNotExist:
                    return Response({"error": "HOD (User) not found."}, status=status.HTTP_404_NOT_FOUND)

            department.save()
            return Response({
                "id": department.id,
                "name": department.name,
                "code": department.code,
                "hod_id": department.hod.id if getattr(department, 'hod', None) else None,
                "email": department.email,
                "phone_number": department.phone_number,
                "description": department.description,
                "status": department.status,
                "remarks": department.remarks,
                "accreditation_status": department.accreditation_status,
                "date_established": department.date_established,
                "updated_by": request.user.username,
            }, status=status.HTTP_200_OK)
        except Department.DoesNotExist:
            return Response({"error": "Department not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def delete(self, request, pk):
        """Delete a specific department. Requires SaaS Admin or College Admin."""
        if not self._can_write(request.user):
            return Response(
                {"error": "Only SaaS Admin or College Admins can delete departments."},
                status=status.HTTP_403_FORBIDDEN
            )
        try:
            department = Department.objects.get(pk=pk)
            department.delete()
            return Response({"message": "Department deleted successfully."}, status=status.HTTP_204_NO_CONTENT)
        except Department.DoesNotExist:
            return Response({"error": "Department not found."}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

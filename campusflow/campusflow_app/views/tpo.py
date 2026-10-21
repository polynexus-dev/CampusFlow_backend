from rest_framework import status, viewsets
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from ..models.tpo import RecruitmentDrive, PlacementApplication
from ..serializers import RecruitmentDriveSerializer, PlacementApplicationSerializer
from ..permissions import ManagedBy, RequiresModule

# Students hold 'tpo' to browse drives and apply; only the Placement Officer/Admins manage records.
TPO_PERMS = [IsAuthenticated, RequiresModule("tpo"), ManagedBy("Placement Officer")]


class RecruitmentDriveViewSet(viewsets.ModelViewSet):
    queryset = RecruitmentDrive.objects.all().order_by('-drive_date')
    serializer_class = RecruitmentDriveSerializer
    permission_classes = TPO_PERMS


class PlacementApplicationViewSet(viewsets.ModelViewSet):
    serializer_class = PlacementApplicationSerializer
    # Students may apply (POST) but not edit/withdraw others' or their own outcome.
    permission_classes = [IsAuthenticated, RequiresModule("tpo"), ManagedBy("Placement Officer", create_roles=("student",))]

    def get_queryset(self):
        qs = PlacementApplication.objects.select_related('student__user', 'drive').all().order_by('-applied_date')
        # A student sees only their own applications (other students' offers/CTC are private).
        student_profile = getattr(self.request.user, 'student_profile', None)
        if student_profile is not None:
            qs = qs.filter(student=student_profile)
        student_id = self.request.query_params.get('student_id')
        if student_id:
            qs = qs.filter(student_id=student_id)
        return qs

    def create(self, request, *args, **kwargs):
        # Pin a student's application to themselves before validation, so the
        # duplicate check and everything else runs against their own record.
        student_profile = getattr(request.user, 'student_profile', None)
        if student_profile is not None:
            data = request.data.copy()
            data['student'] = student_profile.id
            serializer = self.get_serializer(data=data)
            serializer.is_valid(raise_exception=True)
            self.perform_create(serializer)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        student = serializer.validated_data.get('student')
        # A student can only ever apply for themselves, whatever the payload says.
        if hasattr(self.request.user, 'student_profile'):
            student = self.request.user.student_profile
        if not student:
            if hasattr(self.request.user, 'student_profile'):
                student = self.request.user.student_profile
            else:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"student": "Student profile is required."})
        serializer.save(student=student)

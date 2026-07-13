from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models.tpo import RecruitmentDrive, PlacementApplication
from ..serializers import RecruitmentDriveSerializer, PlacementApplicationSerializer


class RecruitmentDriveViewSet(viewsets.ModelViewSet):
    queryset = RecruitmentDrive.objects.all().order_by('-drive_date')
    serializer_class = RecruitmentDriveSerializer
    permission_classes = [IsAuthenticated]


class PlacementApplicationViewSet(viewsets.ModelViewSet):
    serializer_class = PlacementApplicationSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = PlacementApplication.objects.select_related('student__user', 'drive').all().order_by('-applied_date')
        student_id = self.request.query_params.get('student_id')
        if student_id:
            qs = qs.filter(student_id=student_id)
        return qs

    def perform_create(self, serializer):
        student = serializer.validated_data.get('student')
        if not student:
            if hasattr(self.request.user, 'student_profile'):
                student = self.request.user.student_profile
            else:
                from rest_framework.exceptions import ValidationError
                raise ValidationError({"student": "Student profile is required."})
        serializer.save(student=student)

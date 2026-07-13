from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from ..models.result import StudentExamResult
from ..serializers import StudentExamResultSerializer
from ..permissions import IsFacultyOrAbove, get_user_group


class StudentExamResultViewSet(viewsets.ModelViewSet):
    """
    CRUD for per-student exam marks.
    Faculty/Admin can create/update/delete. Students can only read their own results.
    """
    serializer_class = StudentExamResultSerializer
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        if self.request.method not in ('GET', 'HEAD', 'OPTIONS'):
            return [IsAuthenticated(), IsFacultyOrAbove()]
        return [IsAuthenticated()]

    def get_queryset(self):
        qs = StudentExamResult.objects.select_related(
            'exam', 'exam__course', 'student__user'
        ).all()
        user = self.request.user
        if get_user_group(user) == 'student':
            qs = qs.filter(student__user=user)
        return qs

    def perform_create(self, serializer):
        serializer.save(entered_by=self.request.user)

    def perform_update(self, serializer):
        serializer.save(entered_by=self.request.user)

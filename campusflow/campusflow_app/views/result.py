from django.utils import timezone
from rest_framework import viewsets, serializers as drf_serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models.result import StudentExamResult
from ..models.exam import Exam
from ..models.profile import StudentProfile
from ..serializers import StudentExamResultSerializer
from ..permissions import IsFacultyOrAbove, get_user_group
from ..services.notifications import notify_guardians_of_student


class StudentExamResultViewSet(viewsets.ModelViewSet):
    """
    CRUD for per-student exam marks.
    Faculty/Admin can create/update/delete. Students can only read their own results.
    Once the parent exam's results are published, direct edits are locked — use
    ResultCorrectionRequestCreateView (views/result_correction.py) instead.
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
        if serializer.instance.exam.results_published:
            raise drf_serializers.ValidationError(
                "This exam's results are published and locked. Submit a ResultCorrectionRequest instead."
            )
        serializer.save(entered_by=self.request.user)


class ExamClassStatsView(APIView):
    """
    GET /api/exams/<id>/class-stats/
    Live entered-count / class-average / below-40% stats for the marks
    entry screen — computed from whatever's entered so far, published or not.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request, pk):
        try:
            exam = Exam.objects.get(pk=pk)
        except Exam.DoesNotExist:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)

        results = StudentExamResult.objects.filter(exam=exam).select_related("student__user")
        total_students = StudentProfile.objects.filter(department=exam.department).count()
        entered_count = results.count()

        marks = [float(r.marks_obtained) for r in results]
        class_average = round(sum(marks) / len(marks), 2) if marks else 0.0

        below_40_threshold = exam.total_marks * 0.4
        below_40 = [r for r in results if float(r.marks_obtained) < below_40_threshold]

        return Response({
            "exam_id": exam.id,
            "entered_count": entered_count,
            "total_students_in_department": total_students,
            "class_average": class_average,
            "below_40_count": len(below_40),
            "below_40_students": [
                {
                    "student_id": r.student_id,
                    "name": r.student.user.get_full_name() or r.student.user.username,
                    "marks_obtained": float(r.marks_obtained),
                }
                for r in below_40
            ],
            "results_published": exam.results_published,
        }, status=status.HTTP_200_OK)


class ExamPublishResultsView(APIView):
    """
    POST /api/exams/<id>/publish-results/
    Publishes all entered marks for this exam: locks direct edits and
    notifies the guardians of every student who has a result.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def post(self, request, pk):
        try:
            exam = Exam.objects.get(pk=pk)
        except Exam.DoesNotExist:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)

        if exam.results_published:
            return Response({"error": "Results for this exam are already published."}, status=status.HTTP_400_BAD_REQUEST)

        exam.results_published = True
        exam.results_published_at = timezone.now()
        exam.save(update_fields=["results_published", "results_published_at"])

        results = StudentExamResult.objects.filter(exam=exam).select_related("student")
        for result in results:
            notify_guardians_of_student(
                result.student,
                title=f"Results published: {exam.name}",
                body=f"{exam.course.course_name} · {result.marks_obtained}/{exam.total_marks} · Grade {result.grade}",
                category="marks_published",
                data={"exam_id": exam.id, "result_id": result.id},
            )

        return Response({
            "exam_id": exam.id,
            "results_published": True,
            "results_published_at": exam.results_published_at.isoformat(),
            "notified_count": results.count(),
        }, status=status.HTTP_200_OK)

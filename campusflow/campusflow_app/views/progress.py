from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from ..models.result import StudentExamResult
from ..models.profile import StudentProfile
from ..permissions import get_user_group, is_faculty_or_above


class StudentProgressView(APIView):
    """
    GET: Aggregated exam-score progress for a single student.
    Students see their own data. Faculty/Admin can pass ?student_id=<StudentProfile id>.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        student_id = request.query_params.get('student_id')

        if get_user_group(user) == 'student':
            profile = getattr(user, 'student_profile', None)
            if not profile:
                return Response({"error": "No student profile found for this user."}, status=status.HTTP_404_NOT_FOUND)
        else:
            if not is_faculty_or_above(user):
                return Response({"error": "You do not have permission to view this data."}, status=status.HTTP_403_FORBIDDEN)
            if not student_id:
                return Response({"error": "student_id query parameter is required."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                profile = StudentProfile.objects.get(pk=student_id)
            except StudentProfile.DoesNotExist:
                return Response({"error": "Student not found."}, status=status.HTTP_404_NOT_FOUND)

        qs = StudentExamResult.objects.filter(student=profile).select_related('exam', 'exam__course')

        # percentage isn't a stored DB column, so aggregate in Python over the
        # (typically small) per-student result set rather than in SQL.
        results = list(qs)
        total_exams = len(results)
        passed = sum(1 for r in results if r.is_pass)
        failed = total_exams - passed
        avg_percentage = (
            round(sum(r.percentage or 0 for r in results) / total_exams, 2)
            if total_exams else None
        )

        trend = [
            {
                "exam_id": r.exam_id,
                "exam_name": r.exam.name,
                "date": str(r.exam.date),
                "course": r.exam.course.course_name if r.exam.course else None,
                "marks_obtained": r.marks_obtained,
                "total_marks": r.exam.total_marks,
                "percentage": r.percentage,
                "grade": r.grade,
                "is_pass": r.is_pass,
            }
            for r in sorted(results, key=lambda r: r.exam.date)
        ]

        by_course = {}
        for r in results:
            key = r.exam.course.course_name if r.exam.course else "Unknown"
            entry = by_course.setdefault(key, {"course_name": key, "total_percentage": 0, "exam_count": 0})
            entry["total_percentage"] += r.percentage or 0
            entry["exam_count"] += 1
        by_course_list = [
            {
                "course_name": v["course_name"],
                "average_percentage": round(v["total_percentage"] / v["exam_count"], 2),
                "exam_count": v["exam_count"],
            }
            for v in by_course.values()
        ]

        by_semester = {}
        for r in results:
            key = (r.exam.semester, r.exam.academic_year)
            entry = by_semester.setdefault(key, {"semester": r.exam.semester, "academic_year": r.exam.academic_year, "total_percentage": 0, "exam_count": 0})
            entry["total_percentage"] += r.percentage or 0
            entry["exam_count"] += 1
        by_semester_list = [
            {
                "semester": v["semester"],
                "academic_year": v["academic_year"],
                "average_percentage": round(v["total_percentage"] / v["exam_count"], 2),
                "exam_count": v["exam_count"],
            }
            for v in by_semester.values()
        ]

        return Response({
            "student_id": profile.student_id,
            "student_name": profile.user.get_full_name() or profile.user.username,
            "overall": {
                "average_percentage": avg_percentage,
                "total_exams": total_exams,
                "passed": passed,
                "failed": failed,
            },
            "trend": trend,
            "by_course": by_course_list,
            "by_semester": by_semester_list,
        }, status=status.HTTP_200_OK)

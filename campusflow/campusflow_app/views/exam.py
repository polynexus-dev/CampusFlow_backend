"""
Exam / Timetable Views
========================
CRUD for exam types and exams, plus timetable views for students and staff.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from ..models.exam import ExamType, Exam
from ..permissions import (
    IsCollegeAdmin, IsFacultyOrAbove, IsNotStudent,
    get_user_group, is_college_admin, is_saas_admin
)


def validate_question_structure(value):
    """
    Validates the optional per-question breakdown attached to an exam.

    Each entry must be either a plain number (legacy shape, e.g. {"Q1": 10})
    or an object {"marks": <number>, "topic": <string, optional>,
    "course_outcome": <string, optional>}. Returns an error string, or None
    if valid.
    """
    if not isinstance(value, dict):
        return "question_structure must be an object mapping question keys to marks."
    for key, spec in value.items():
        if isinstance(spec, dict):
            if 'marks' not in spec:
                return f"question_structure['{key}'] must include 'marks'."
            try:
                float(spec['marks'])
            except (TypeError, ValueError):
                return f"question_structure['{key}'].marks must be a number."
            if 'topic' in spec and spec['topic'] is not None and not isinstance(spec['topic'], str):
                return f"question_structure['{key}'].topic must be a string."
            if 'course_outcome' in spec and spec['course_outcome'] is not None \
                    and not isinstance(spec['course_outcome'], str):
                return f"question_structure['{key}'].course_outcome must be a string."
        else:
            try:
                float(spec)
            except (TypeError, ValueError):
                return f"question_structure['{key}'] must be a number or an object with 'marks'."
    return None


class ExamTypeListCreateView(APIView):
    """GET: List exam types. POST: Create (Admin only)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        types = ExamType.objects.all()
        data = [{"id": t.id, "name": t.name, "code": t.code} for t in types]
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        if not is_college_admin(request.user):
            return Response({"error": "Only College Admin can create exam types."}, status=status.HTTP_403_FORBIDDEN)

        name = request.data.get('name', '').strip()
        code = request.data.get('code', '').strip().upper()
        if not name or not code:
            return Response({"error": "Name and code are required."}, status=status.HTTP_400_BAD_REQUEST)

        if ExamType.objects.filter(code=code).exists():
            return Response({"error": f"Exam type '{code}' already exists."}, status=status.HTTP_400_BAD_REQUEST)

        t = ExamType.objects.create(name=name, code=code)
        return Response({"message": "Exam type created.", "id": t.id}, status=status.HTTP_201_CREATED)


class ExamListCreateView(APIView):
    """GET: List exams. POST: Create exam (Admin/HOD/Faculty)."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        user_group = get_user_group(user)
        qs = Exam.objects.all().select_related('exam_type', 'department', 'course', 'classroom', 'invigilator')

        # Filters
        dept_id = request.query_params.get('department')
        status_filter = request.query_params.get('status')
        exam_type_id = request.query_params.get('exam_type')

        if dept_id:
            qs = qs.filter(department_id=dept_id)
        if status_filter:
            qs = qs.filter(status=status_filter)
        if exam_type_id:
            qs = qs.filter(exam_type_id=exam_type_id)

        # Students: only see exams from their department
        if user_group == 'student':
            profile = getattr(user, 'student_profile', None)
            if profile and profile.department:
                qs = qs.filter(department=profile.department)
            else:
                qs = qs.none()

        data = []
        for exam in qs:
            data.append({
                "id": exam.id,
                "name": exam.name,
                "exam_type": exam.exam_type.name,
                "exam_type_code": exam.exam_type.code,
                "department": exam.department.name if exam.department else None,
                "department_id": exam.department_id,
                "course": exam.course.course_name if exam.course else None,
                "course_code": exam.course.course_code if exam.course else None,
                "date": str(exam.date),
                "start_time": str(exam.start_time),
                "end_time": str(exam.end_time),
                "classroom": exam.classroom.name if exam.classroom else None,
                "total_marks": exam.total_marks,
                "passing_marks": exam.passing_marks,
                "semester": exam.semester,
                "academic_year": exam.academic_year,
                "invigilator": exam.invigilator.get_full_name() if exam.invigilator else None,
                "status": exam.status,
                "instructions": exam.instructions,
                "created_at": exam.created_at.isoformat(),
            })
        return Response(data, status=status.HTTP_200_OK)

    def post(self, request):
        if not IsFacultyOrAbove().has_permission(request, self):
            return Response({"error": "Only Faculty and above can create exams."}, status=status.HTTP_403_FORBIDDEN)

        from ..models.department import Department
        from ..models.course import Course
        from ..models.classroom import Classroom
        from django.contrib.auth.models import User

        required = ['name', 'exam_type_id', 'department_id', 'course_id', 'date', 'start_time', 'end_time']
        for field in required:
            if not request.data.get(field):
                return Response({"error": f"{field} is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            exam_type = ExamType.objects.get(id=request.data['exam_type_id'])
            department = Department.objects.get(id=request.data['department_id'])
            course = Course.objects.get(id=request.data['course_id'])
        except (ExamType.DoesNotExist, Department.DoesNotExist, Course.DoesNotExist) as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        classroom = None
        if request.data.get('classroom_id'):
            try:
                classroom = Classroom.objects.get(id=request.data['classroom_id'])
            except Classroom.DoesNotExist:
                pass

        invigilator = None
        if request.data.get('invigilator_id'):
            try:
                invigilator = User.objects.get(id=request.data['invigilator_id'])
            except User.DoesNotExist:
                pass

        question_structure = request.data.get('question_structure') or {}
        if question_structure:
            error = validate_question_structure(question_structure)
            if error:
                return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        exam = Exam.objects.create(
            name=request.data['name'],
            exam_type=exam_type,
            department=department,
            course=course,
            date=request.data['date'],
            start_time=request.data['start_time'],
            end_time=request.data['end_time'],
            classroom=classroom,
            total_marks=request.data.get('total_marks', 100),
            passing_marks=request.data.get('passing_marks', 35),
            semester=request.data.get('semester', ''),
            academic_year=request.data.get('academic_year', ''),
            question_structure=question_structure,
            invigilator=invigilator,
            created_by=request.user,
            instructions=request.data.get('instructions', ''),
        )
        return Response({"message": "Exam created.", "id": exam.id}, status=status.HTTP_201_CREATED)


class ExamDetailView(APIView):
    """GET/PUT/DELETE a single exam."""
    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        try:
            exam = Exam.objects.select_related('exam_type', 'department', 'course', 'classroom', 'invigilator').get(id=pk)
        except Exam.DoesNotExist:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)

        data = {
            "id": exam.id,
            "name": exam.name,
            "exam_type": {"id": exam.exam_type.id, "name": exam.exam_type.name},
            "department": {"id": exam.department.id, "name": exam.department.name} if exam.department else None,
            "course": {"id": exam.course.id, "name": exam.course.course_name, "code": exam.course.course_code} if exam.course else None,
            "date": str(exam.date),
            "start_time": str(exam.start_time),
            "end_time": str(exam.end_time),
            "classroom": {"id": exam.classroom.id, "name": exam.classroom.name} if exam.classroom else None,
            "total_marks": exam.total_marks,
            "passing_marks": exam.passing_marks,
            "semester": exam.semester,
            "academic_year": exam.academic_year,
            "question_structure": exam.question_structure,
            "invigilator": {"id": exam.invigilator.id, "name": exam.invigilator.get_full_name()} if exam.invigilator else None,
            "status": exam.status,
            "instructions": exam.instructions,
        }
        return Response(data, status=status.HTTP_200_OK)

    def put(self, request, pk):
        if not IsFacultyOrAbove().has_permission(request, self):
            return Response({"error": "Insufficient permissions."}, status=status.HTTP_403_FORBIDDEN)

        try:
            exam = Exam.objects.get(id=pk)
        except Exam.DoesNotExist:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)

        if 'question_structure' in request.data:
            error = validate_question_structure(request.data['question_structure'] or {})
            if error:
                return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        simple_fields = ['name', 'date', 'start_time', 'end_time', 'total_marks',
                         'passing_marks', 'semester', 'academic_year', 'status', 'instructions',
                         'question_structure']
        for field in simple_fields:
            if field in request.data:
                setattr(exam, field, request.data[field])
        exam.save()
        return Response({"message": "Exam updated."}, status=status.HTTP_200_OK)

    def delete(self, request, pk):
        if not is_college_admin(request.user):
            return Response({"error": "Only College Admin can delete exams."}, status=status.HTTP_403_FORBIDDEN)
        try:
            exam = Exam.objects.get(id=pk)
        except Exam.DoesNotExist:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)
        exam.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

"""
Syllabus & Question Bank
=========================
Per-course syllabus topics and a topic/difficulty-tagged question bank —
the building blocks views/paper_setting.py draws from to compose an exam's
paper.
"""

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Course, SyllabusTopic, Question
from ..models.outcomes import CourseOutcome
from ..permissions import IsFacultyOrAbove, RequiresModule

QUESTION_BANK_PERMS = [IsAuthenticated, IsFacultyOrAbove, RequiresModule("exams")]


def _serialize_topic(t):
    return {
        "id": t.id, "course_id": t.course_id, "name": t.name, "order": t.order,
        "description": t.description,
        "course_outcome_id": t.course_outcome_id,
        "course_outcome_code": t.course_outcome.code if t.course_outcome_id else None,
    }


def _serialize_question(q):
    return {
        "id": q.id,
        "course_id": q.course_id,
        "topic_id": q.topic_id,
        "topic_name": q.topic.name if q.topic_id else None,
        "text": q.text,
        "marks": float(q.marks),
        "difficulty": q.difficulty,
        "course_outcome_id": q.course_outcome_id,
        "course_outcome_code": q.course_outcome.code if q.course_outcome_id else None,
        "is_active": q.is_active,
        "ai_generated": q.ai_generated,
        "created_at": q.created_at.isoformat(),
    }


def _resolve_course_outcome(course, co_id):
    """Returns (course_outcome_or_None, error_or_None). A CO must belong to
    the same course it's being attached to — mirroring how topic_id is
    already validated below."""
    if not co_id:
        return None, None
    co = CourseOutcome.objects.filter(id=co_id, course=course).first()
    if not co:
        return None, "Invalid course_outcome_id for this course."
    return co, None


class SyllabusTopicListCreateView(APIView):
    """
    GET/POST /api/courses/<course_id>/syllabus-topics/
    """
    permission_classes = QUESTION_BANK_PERMS

    def get(self, request, course_id):
        topics = SyllabusTopic.objects.filter(course_id=course_id)
        return Response({"results": [_serialize_topic(t) for t in topics]}, status=status.HTTP_200_OK)

    def post(self, request, course_id):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        name = (request.data.get("name") or "").strip()
        if not name:
            return Response({"error": "name is required."}, status=status.HTTP_400_BAD_REQUEST)

        if SyllabusTopic.objects.filter(course=course, name=name).exists():
            return Response({"error": "This topic already exists for this course."}, status=status.HTTP_400_BAD_REQUEST)

        course_outcome, error = _resolve_course_outcome(course, request.data.get("course_outcome_id"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        topic = SyllabusTopic.objects.create(
            course=course, name=name,
            order=request.data.get("order", 0),
            description=request.data.get("description", ""),
            course_outcome=course_outcome,
        )
        return Response(_serialize_topic(topic), status=status.HTTP_201_CREATED)


class SyllabusTopicDetailView(APIView):
    """
    PUT/DELETE /api/syllabus-topics/<id>/
    """
    permission_classes = QUESTION_BANK_PERMS

    def put(self, request, pk):
        try:
            topic = SyllabusTopic.objects.get(pk=pk)
        except SyllabusTopic.DoesNotExist:
            return Response({"error": "Topic not found."}, status=status.HTTP_404_NOT_FOUND)

        topic.name = request.data.get("name", topic.name)
        topic.order = request.data.get("order", topic.order)
        topic.description = request.data.get("description", topic.description)
        if "course_outcome_id" in request.data:
            course_outcome, error = _resolve_course_outcome(topic.course, request.data.get("course_outcome_id"))
            if error:
                return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
            topic.course_outcome = course_outcome
        topic.save()
        return Response(_serialize_topic(topic), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        try:
            topic = SyllabusTopic.objects.get(pk=pk)
        except SyllabusTopic.DoesNotExist:
            return Response({"error": "Topic not found."}, status=status.HTTP_404_NOT_FOUND)
        topic.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class QuestionBankListCreateView(APIView):
    """
    GET/POST /api/courses/<course_id>/questions/?topic_id=&difficulty=
    """
    permission_classes = QUESTION_BANK_PERMS

    def get(self, request, course_id):
        qs = Question.objects.filter(course_id=course_id, is_active=True).select_related("topic")
        topic_id = request.query_params.get("topic_id")
        difficulty = request.query_params.get("difficulty")
        if topic_id:
            qs = qs.filter(topic_id=topic_id)
        if difficulty:
            qs = qs.filter(difficulty=difficulty)
        return Response({"results": [_serialize_question(q) for q in qs]}, status=status.HTTP_200_OK)

    def post(self, request, course_id):
        try:
            course = Course.objects.get(id=course_id)
        except Course.DoesNotExist:
            return Response({"error": "Course not found."}, status=status.HTTP_404_NOT_FOUND)

        text = (request.data.get("text") or "").strip()
        marks = request.data.get("marks")
        if not text or marks is None:
            return Response({"error": "text and marks are required."}, status=status.HTTP_400_BAD_REQUEST)

        topic = None
        topic_id = request.data.get("topic_id")
        if topic_id:
            try:
                topic = SyllabusTopic.objects.get(id=topic_id, course=course)
            except SyllabusTopic.DoesNotExist:
                return Response({"error": "Invalid topic for this course."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            marks = float(marks)
        except (TypeError, ValueError):
            return Response({"error": "marks must be a number."}, status=status.HTTP_400_BAD_REQUEST)

        course_outcome, error = _resolve_course_outcome(course, request.data.get("course_outcome_id"))
        if error:
            return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)

        question = Question.objects.create(
            course=course, topic=topic, text=text, marks=marks,
            difficulty=request.data.get("difficulty", Question.DIFFICULTY_MEDIUM),
            course_outcome=course_outcome,
            created_by=request.user,
        )
        return Response(_serialize_question(question), status=status.HTTP_201_CREATED)


class QuestionDetailView(APIView):
    """
    PUT/DELETE /api/questions/<id>/  (DELETE soft-disables, doesn't remove)
    """
    permission_classes = QUESTION_BANK_PERMS

    def put(self, request, pk):
        try:
            question = Question.objects.get(pk=pk)
        except Question.DoesNotExist:
            return Response({"error": "Question not found."}, status=status.HTTP_404_NOT_FOUND)

        if "text" in request.data:
            question.text = request.data["text"]
        if "marks" in request.data:
            try:
                question.marks = float(request.data["marks"])
            except (TypeError, ValueError):
                return Response({"error": "marks must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        if "difficulty" in request.data:
            question.difficulty = request.data["difficulty"]
        if "topic_id" in request.data:
            topic_id = request.data["topic_id"]
            question.topic = SyllabusTopic.objects.filter(id=topic_id, course=question.course).first() if topic_id else None
        if "course_outcome_id" in request.data:
            course_outcome, error = _resolve_course_outcome(question.course, request.data.get("course_outcome_id"))
            if error:
                return Response({"error": error}, status=status.HTTP_400_BAD_REQUEST)
            question.course_outcome = course_outcome
        question.save()
        return Response(_serialize_question(question), status=status.HTTP_200_OK)

    def delete(self, request, pk):
        try:
            question = Question.objects.get(pk=pk)
        except Question.DoesNotExist:
            return Response({"error": "Question not found."}, status=status.HTTP_404_NOT_FOUND)
        question.is_active = False
        question.save(update_fields=["is_active"])
        return Response(status=status.HTTP_204_NO_CONTENT)

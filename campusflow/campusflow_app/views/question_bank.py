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
from ..permissions import IsFacultyOrAbove


def _serialize_topic(t):
    return {"id": t.id, "course_id": t.course_id, "name": t.name, "order": t.order, "description": t.description}


def _serialize_question(q):
    return {
        "id": q.id,
        "course_id": q.course_id,
        "topic_id": q.topic_id,
        "topic_name": q.topic.name if q.topic_id else None,
        "text": q.text,
        "marks": float(q.marks),
        "difficulty": q.difficulty,
        "is_active": q.is_active,
        "created_at": q.created_at.isoformat(),
    }


class SyllabusTopicListCreateView(APIView):
    """
    GET/POST /api/courses/<course_id>/syllabus-topics/
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

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

        topic = SyllabusTopic.objects.create(
            course=course, name=name,
            order=request.data.get("order", 0),
            description=request.data.get("description", ""),
        )
        return Response(_serialize_topic(topic), status=status.HTTP_201_CREATED)


class SyllabusTopicDetailView(APIView):
    """
    PUT/DELETE /api/syllabus-topics/<id>/
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def put(self, request, pk):
        try:
            topic = SyllabusTopic.objects.get(pk=pk)
        except SyllabusTopic.DoesNotExist:
            return Response({"error": "Topic not found."}, status=status.HTTP_404_NOT_FOUND)

        topic.name = request.data.get("name", topic.name)
        topic.order = request.data.get("order", topic.order)
        topic.description = request.data.get("description", topic.description)
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
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

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

        question = Question.objects.create(
            course=course, topic=topic, text=text, marks=marks,
            difficulty=request.data.get("difficulty", Question.DIFFICULTY_MEDIUM),
            created_by=request.user,
        )
        return Response(_serialize_question(question), status=status.HTTP_201_CREATED)


class QuestionDetailView(APIView):
    """
    PUT/DELETE /api/questions/<id>/  (DELETE soft-disables, doesn't remove)
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

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

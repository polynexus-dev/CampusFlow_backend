"""
Paper Setting from Syllabus
=============================
Set a per-topic marks blueprint for an exam, auto-generate a draft paper
from the question bank against that blueprint, then let a teacher
replace/update/add/remove individual questions from the resulting panel.

Every mutation re-syncs Exam.question_structure (services/paper_sync.py)
so the already-working valuation/topic-performance analytics
(views/progress.py: StudentTopicPerformanceView) keep working unmodified.
"""

import random
from decimal import Decimal

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import Exam, SyllabusTopic, Question, PaperBlueprintTopic, ExamQuestion
from ..permissions import IsFacultyOrAbove
from ..services.paper_sync import sync_question_structure


def _get_exam(pk):
    try:
        return Exam.objects.get(pk=pk)
    except Exam.DoesNotExist:
        return None


def _serialize_exam_question(eq):
    return {
        "id": eq.id,
        "question_label": eq.question_label,
        "question_id": eq.question_id,
        "text": eq.question_text_snapshot,
        "marks": float(eq.marks),
        "topic_id": eq.topic_id,
        "topic_name": eq.topic.name if eq.topic_id else None,
        "order": eq.order,
    }


class PaperBlueprintView(APIView):
    """
    GET/PUT /api/exams/<id>/blueprint/
    PUT payload: {topics: [{topic_id, target_marks}, ...]}
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request, pk):
        exam = _get_exam(pk)
        if not exam:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)
        entries = exam.blueprint_topics.select_related("topic")
        return Response({
            "exam_id": exam.id,
            "total_marks": exam.total_marks,
            "topics": [
                {"topic_id": e.topic_id, "topic_name": e.topic.name, "target_marks": float(e.target_marks)}
                for e in entries
            ],
        }, status=status.HTTP_200_OK)

    def put(self, request, pk):
        exam = _get_exam(pk)
        if not exam:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)
        if exam.paper_finalized:
            return Response({"error": "This exam's paper is finalized and locked."}, status=status.HTTP_400_BAD_REQUEST)

        topics_payload = request.data.get("topics", [])
        if not topics_payload:
            return Response({"error": "topics is required and must be non-empty."}, status=status.HTTP_400_BAD_REQUEST)

        total_target = Decimal("0")
        resolved = []
        for entry in topics_payload:
            topic_id = entry.get("topic_id")
            target_marks = entry.get("target_marks")
            try:
                topic = SyllabusTopic.objects.get(id=topic_id, course=exam.course)
            except SyllabusTopic.DoesNotExist:
                return Response({"error": f"Invalid topic_id {topic_id} for this exam's course."}, status=status.HTTP_400_BAD_REQUEST)
            try:
                target_marks = Decimal(str(target_marks))
            except Exception:
                return Response({"error": f"target_marks for topic {topic_id} must be a number."}, status=status.HTTP_400_BAD_REQUEST)
            total_target += target_marks
            resolved.append((topic, target_marks))

        if total_target != Decimal(str(exam.total_marks)):
            return Response(
                {"error": f"Blueprint targets sum to {total_target}, but the exam's total_marks is {exam.total_marks}."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        exam.blueprint_topics.all().delete()
        PaperBlueprintTopic.objects.bulk_create([
            PaperBlueprintTopic(exam=exam, topic=topic, target_marks=target_marks)
            for topic, target_marks in resolved
        ])

        return Response({
            "exam_id": exam.id,
            "topics": [{"topic_id": t.id, "topic_name": t.name, "target_marks": float(m)} for t, m in resolved],
        }, status=status.HTTP_200_OK)


class GeneratePaperView(APIView):
    """
    POST /api/exams/<id>/paper/generate/
    Clears any existing ExamQuestion rows and draws a fresh set from the
    question bank against the blueprint, greedy-random per topic.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def post(self, request, pk):
        exam = _get_exam(pk)
        if not exam:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)
        if exam.paper_finalized:
            return Response({"error": "This exam's paper is finalized and locked."}, status=status.HTTP_400_BAD_REQUEST)

        blueprint = list(exam.blueprint_topics.select_related("topic"))
        if not blueprint:
            return Response({"error": "Set a paper blueprint before generating."}, status=status.HTTP_400_BAD_REQUEST)

        exam.exam_questions.all().delete()

        warnings = []
        order = 0
        label_index = 1
        new_rows = []

        for entry in blueprint:
            target = entry.target_marks
            candidates = list(Question.objects.filter(topic=entry.topic, is_active=True))
            random.shuffle(candidates)

            picked_total = Decimal("0")
            picked = []
            for q in candidates:
                if picked_total >= target:
                    break
                picked.append(q)
                picked_total += q.marks

            if picked_total < target:
                warnings.append(
                    f"Topic '{entry.topic.name}': only found {picked_total} of {target} target marks in the question bank."
                )

            for q in picked:
                new_rows.append(ExamQuestion(
                    exam=exam,
                    question=q,
                    question_label=f"Q{label_index}",
                    question_text_snapshot=q.text,
                    marks=q.marks,
                    topic=entry.topic,
                    order=order,
                ))
                order += 1
                label_index += 1

        ExamQuestion.objects.bulk_create(new_rows)
        sync_question_structure(exam)

        total_marks_composed = sum((r.marks for r in new_rows), Decimal("0"))
        return Response({
            "exam_id": exam.id,
            "question_count": len(new_rows),
            "total_marks_composed": float(total_marks_composed),
            "total_marks_target": float(exam.total_marks),
            "warnings": warnings,
        }, status=status.HTTP_201_CREATED)


class ExamPaperView(APIView):
    """
    GET /api/exams/<id>/paper/
    The question panel: ordered ExamQuestion list + per-topic actual vs
    target marks, so the frontend can flag an unbalanced paper.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request, pk):
        exam = _get_exam(pk)
        if not exam:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)

        questions = list(exam.exam_questions.select_related("topic", "question").order_by("order"))
        total_composed = sum((q.marks for q in questions), Decimal("0"))

        by_topic = {}
        for q in questions:
            key = q.topic_id
            entry = by_topic.setdefault(key, {"topic_id": key, "topic_name": q.topic.name if q.topic_id else None, "actual_marks": Decimal("0")})
            entry["actual_marks"] += q.marks

        blueprint = {b.topic_id: b.target_marks for b in exam.blueprint_topics.all()}
        for topic_id, entry in by_topic.items():
            entry["target_marks"] = float(blueprint.get(topic_id, 0))
            entry["actual_marks"] = float(entry["actual_marks"])

        return Response({
            "exam_id": exam.id,
            "paper_finalized": exam.paper_finalized,
            "total_marks_target": float(exam.total_marks),
            "total_marks_composed": float(total_composed),
            "is_balanced": total_composed == Decimal(str(exam.total_marks)),
            "by_topic": list(by_topic.values()),
            "questions": [_serialize_exam_question(q) for q in questions],
        }, status=status.HTTP_200_OK)


class ExamQuestionAddView(APIView):
    """
    POST /api/exams/<id>/paper/questions/
    Payload: {question_id, question_label?}
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def post(self, request, pk):
        exam = _get_exam(pk)
        if not exam:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)
        if exam.paper_finalized:
            return Response({"error": "This exam's paper is finalized and locked."}, status=status.HTTP_400_BAD_REQUEST)

        question_id = request.data.get("question_id")
        try:
            bank_question = Question.objects.get(id=question_id, course=exam.course)
        except Question.DoesNotExist:
            return Response({"error": "Invalid question_id for this exam's course."}, status=status.HTTP_400_BAD_REQUEST)

        label = request.data.get("question_label")
        if not label:
            existing_count = exam.exam_questions.count()
            label = f"Q{existing_count + 1}"
            while exam.exam_questions.filter(question_label=label).exists():
                existing_count += 1
                label = f"Q{existing_count + 1}"
        elif exam.exam_questions.filter(question_label=label).exists():
            return Response({"error": f"Label '{label}' is already used in this paper."}, status=status.HTTP_400_BAD_REQUEST)

        max_order = exam.exam_questions.count()
        eq = ExamQuestion.objects.create(
            exam=exam, question=bank_question, question_label=label,
            question_text_snapshot=bank_question.text, marks=bank_question.marks,
            topic=bank_question.topic, order=max_order,
        )
        sync_question_structure(exam)
        return Response(_serialize_exam_question(eq), status=status.HTTP_201_CREATED)


class ExamQuestionReplaceView(APIView):
    """
    POST /api/exams/<id>/paper/questions/<exam_question_id>/replace/
    Payload: {question_id}
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def post(self, request, pk, exam_question_id):
        exam = _get_exam(pk)
        if not exam:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)
        if exam.paper_finalized:
            return Response({"error": "This exam's paper is finalized and locked."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            eq = exam.exam_questions.get(id=exam_question_id)
        except ExamQuestion.DoesNotExist:
            return Response({"error": "Exam question not found."}, status=status.HTTP_404_NOT_FOUND)

        question_id = request.data.get("question_id")
        try:
            bank_question = Question.objects.get(id=question_id, course=exam.course)
        except Question.DoesNotExist:
            return Response({"error": "Invalid question_id for this exam's course."}, status=status.HTTP_400_BAD_REQUEST)

        eq.question = bank_question
        eq.question_text_snapshot = bank_question.text
        eq.marks = bank_question.marks
        eq.topic = bank_question.topic
        eq.save()
        sync_question_structure(exam)
        return Response(_serialize_exam_question(eq), status=status.HTTP_200_OK)


class ExamQuestionDetailView(APIView):
    """
    PATCH  /api/exams/<id>/paper/questions/<exam_question_id>/   payload: {marks?, order?}
    DELETE /api/exams/<id>/paper/questions/<exam_question_id>/
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def _get_locked_exam_and_question(self, pk, exam_question_id):
        exam = _get_exam(pk)
        if not exam:
            return None, None, Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)
        if exam.paper_finalized:
            return None, None, Response({"error": "This exam's paper is finalized and locked."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            eq = exam.exam_questions.get(id=exam_question_id)
        except ExamQuestion.DoesNotExist:
            return None, None, Response({"error": "Exam question not found."}, status=status.HTTP_404_NOT_FOUND)
        return exam, eq, None

    def patch(self, request, pk, exam_question_id):
        exam, eq, error = self._get_locked_exam_and_question(pk, exam_question_id)
        if error:
            return error

        if "marks" in request.data:
            try:
                eq.marks = Decimal(str(request.data["marks"]))
            except Exception:
                return Response({"error": "marks must be a number."}, status=status.HTTP_400_BAD_REQUEST)
        if "order" in request.data:
            eq.order = request.data["order"]
        eq.save()
        sync_question_structure(exam)
        return Response(_serialize_exam_question(eq), status=status.HTTP_200_OK)

    def delete(self, request, pk, exam_question_id):
        exam, eq, error = self._get_locked_exam_and_question(pk, exam_question_id)
        if error:
            return error

        eq.delete()
        sync_question_structure(exam)
        return Response(status=status.HTTP_204_NO_CONTENT)


class FinalizePaperView(APIView):
    """
    POST /api/exams/<id>/paper/finalize/
    Locks the paper — blocked unless the composed marks exactly match
    exam.total_marks.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def post(self, request, pk):
        from django.utils import timezone

        exam = _get_exam(pk)
        if not exam:
            return Response({"error": "Exam not found."}, status=status.HTTP_404_NOT_FOUND)
        if exam.paper_finalized:
            return Response({"error": "This exam's paper is already finalized."}, status=status.HTTP_400_BAD_REQUEST)

        total_composed = sum((q.marks for q in exam.exam_questions.all()), Decimal("0"))
        if total_composed != Decimal(str(exam.total_marks)):
            return Response(
                {"error": f"Paper totals {total_composed}, but the exam's total_marks is {exam.total_marks}. Balance it before finalizing."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        exam.paper_finalized = True
        exam.paper_finalized_at = timezone.now()
        exam.save(update_fields=["paper_finalized", "paper_finalized_at"])
        return Response({"exam_id": exam.id, "paper_finalized": True}, status=status.HTTP_200_OK)

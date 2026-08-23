from decimal import Decimal

from django.db import connection
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..demo_guard import IsNotDemoTenant
from ..models.ai_grading import AIGradingSuggestion
from ..models.valuation import ValuationSession, ScannedPaper
from ..permissions import IsFacultyOrAbove, RequiresModule, get_user_group, is_hm_or_above
from ..serializers import AIGradingSuggestionSerializer, ValuationSessionSerializer, ScannedPaperSerializer
from ..tasks import run_ai_grading_suggestion

VALUATION_PERMS = [IsAuthenticated, RequiresModule("valuation")]
AI_VALUATION_PERMS = [IsAuthenticated, IsFacultyOrAbove, RequiresModule("ai-valuation")]


class ValuationSessionViewSet(viewsets.ModelViewSet):
    """
    Plain Faculty (evaluators) only ever see the sessions actually assigned
    to them — this was previously unscoped, meaning any authenticated
    Faculty account could list every valuation session in the tenant
    regardless of who it was assigned to, undermining the blind-evaluation
    design the serializer's student-name masking exists for. HOD-or-above
    keeps the broader view they already have everywhere else in the app.
    """
    queryset = ValuationSession.objects.select_related('exam', 'evaluator__user').all().order_by('-started_at')
    serializer_class = ValuationSessionSerializer
    permission_classes = VALUATION_PERMS

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if get_user_group(user) == 'Faculty' and not is_hm_or_above(user):
            qs = qs.filter(evaluator__user=user)
        return qs


class ScannedPaperViewSet(viewsets.ModelViewSet):
    """Same 'assigned to me' scoping as ValuationSessionViewSet, via the
    parent session's evaluator — see that class's docstring."""
    queryset = ScannedPaper.objects.select_related('student__user', 'session__exam').all().order_by('-evaluated_at')
    serializer_class = ScannedPaperSerializer
    permission_classes = VALUATION_PERMS

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        if get_user_group(user) == 'Faculty' and not is_hm_or_above(user):
            qs = qs.filter(session__evaluator__user=user)
        session_id = self.request.query_params.get('session')
        if session_id:
            qs = qs.filter(session_id=session_id)
        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)
        return qs


class ScannedPaperAISuggestView(APIView):
    """
    POST /scanned-papers/<pk>/ai-suggest/
    Queues an AI-assisted first-pass grading suggestion for one scanned
    paper (see campusflow_app/ai_grading.py and the run_ai_grading_suggestion
    task). Requires the paper's exam to have an answer_key rubric set.
    Fires the task with .delay() (not .get()) since LLM latency is far less
    bounded than the local ONNX inference other tasks in this app block on —
    the frontend polls ScannedPaperAISuggestionListView for the result.
    """
    permission_classes = AI_VALUATION_PERMS + [IsNotDemoTenant]

    def post(self, request, pk):
        paper = get_object_or_404(ScannedPaper, pk=pk)
        exam = paper.session.exam
        if not exam.answer_key:
            return Response(
                {"error": "This exam has no answer key / rubric set yet. "
                          "Add one to the exam's answer_key before requesting AI grading."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # A fresh request supersedes any suggestion still awaiting review.
        paper.ai_suggestions.filter(status="pending").update(status="rejected")

        suggestion = AIGradingSuggestion.objects.create(
            scanned_paper=paper,
            requested_by=request.user,
        )
        run_ai_grading_suggestion.delay(connection.schema_name, suggestion.id)

        return Response(
            AIGradingSuggestionSerializer(suggestion).data,
            status=status.HTTP_202_ACCEPTED,
        )


class ScannedPaperAISuggestionListView(APIView):
    """
    GET /scanned-papers/<pk>/ai-suggestions/
    Lists AI grading suggestions for one paper, latest first — for polling
    a pending suggestion until it resolves to applied/rejected/failed.
    """
    permission_classes = AI_VALUATION_PERMS

    def get(self, request, pk):
        paper = get_object_or_404(ScannedPaper, pk=pk)
        suggestions = paper.ai_suggestions.all()
        return Response(AIGradingSuggestionSerializer(suggestions, many=True).data)


class AIGradingSuggestionApplyView(APIView):
    """
    POST /ai-suggestions/<pk>/apply/
    Copies a suggestion's per-question scores into the paper and marks it
    Evaluated. Refuses to overwrite an already-Evaluated paper unless
    ?force=true — never silently overwrite a hand-graded paper.
    """
    permission_classes = AI_VALUATION_PERMS + [IsNotDemoTenant]

    def post(self, request, pk):
        suggestion = get_object_or_404(AIGradingSuggestion, pk=pk)
        if suggestion.status != "pending":
            return Response(
                {"error": f"This suggestion is already {suggestion.status} and cannot be applied."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        paper = suggestion.scanned_paper
        force = str(request.query_params.get("force", "")).lower() == "true"
        if paper.status == "Evaluated" and not force:
            return Response(
                {"error": "This paper is already evaluated. Pass ?force=true to overwrite it with the AI suggestion."},
                status=status.HTTP_409_CONFLICT,
            )

        question_scores = {
            key: entry.get("score")
            for key, entry in suggestion.question_scores_suggested.items()
        }
        total_marks = sum(
            Decimal(str(entry.get("score", 0))) for entry in suggestion.question_scores_suggested.values()
        )

        paper.question_scores = question_scores
        paper.allocated_marks = total_marks
        paper.status = "Evaluated"
        paper.evaluated_at = timezone.now()
        paper.evaluated_by = request.user
        paper.save(update_fields=["question_scores", "allocated_marks", "status", "evaluated_at", "evaluated_by"])

        suggestion.status = "applied"
        suggestion.applied_at = timezone.now()
        suggestion.applied_by = request.user
        suggestion.save(update_fields=["status", "applied_at", "applied_by"])

        return Response(ScannedPaperSerializer(paper, context={"request": request}).data)


class AIGradingSuggestionRejectView(APIView):
    """POST /ai-suggestions/<pk>/reject/"""
    permission_classes = AI_VALUATION_PERMS + [IsNotDemoTenant]

    def post(self, request, pk):
        suggestion = get_object_or_404(AIGradingSuggestion, pk=pk)
        if suggestion.status != "pending":
            return Response(
                {"error": f"This suggestion is already {suggestion.status}."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        suggestion.status = "rejected"
        suggestion.save(update_fields=["status"])
        return Response(AIGradingSuggestionSerializer(suggestion).data)

"""
Rubrics & rubric-based assessment. Docs/college_gap_closure_plan.md §1.2.

  rubrics/               CRUD. Criteria and levels are written nested in one payload.
                         Once a rubric has assessments, its criteria/levels are frozen
                         (editing them would silently change past scores); name,
                         description and is_active stay editable.
  rubric-assessments/    one evaluator scoring one student: every criterion of the
                         rubric gets exactly one level. Students see their own.
"""
from decimal import Decimal

from django.db import transaction
from django.db.models import Q
from rest_framework import serializers, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated

from ..models.offerings import CourseOffering
from ..models.profile import StudentProfile
from ..models.rubrics import Rubric, RubricAssessment, RubricCriterion, RubricLevel, RubricScore
from ..permissions import RequiresModule, is_college_admin, is_faculty_or_above, is_hm_or_above
from ..services.rbac import scope_students

RUBRIC_PERMS = [IsAuthenticated, RequiresModule("rubrics")]


def _student_profile(user):
    return getattr(user, "student_profile", None)


def _taught_course_ids(user):
    return CourseOffering.objects.filter(faculty=user).values_list("course_id", flat=True)


# ── Rubric definition ───────────────────────────────────────────────────────

class RubricLevelSerializer(serializers.ModelSerializer):
    class Meta:
        model = RubricLevel
        fields = ["id", "label", "score", "descriptor"]


class RubricCriterionSerializer(serializers.ModelSerializer):
    levels = RubricLevelSerializer(many=True)
    course_outcome_code = serializers.CharField(source="course_outcome.code", read_only=True, default=None)

    class Meta:
        model = RubricCriterion
        fields = ["id", "title", "description", "course_outcome", "course_outcome_code", "weight", "order", "levels"]


class RubricSerializer(serializers.ModelSerializer):
    criteria = RubricCriterionSerializer(many=True)
    course_code = serializers.CharField(source="course.course_code", read_only=True, default=None)
    max_score = serializers.FloatField(read_only=True)
    assessment_count = serializers.SerializerMethodField()

    class Meta:
        model = Rubric
        fields = [
            "id", "name", "description", "course", "course_code", "applies_to", "is_active",
            "criteria", "max_score", "assessment_count", "created_by", "created_at", "updated_at",
        ]
        read_only_fields = ["created_by"]

    def get_assessment_count(self, obj):
        return obj.assessments.count()

    def validate(self, attrs):
        criteria = attrs.get("criteria")
        course = attrs.get("course", getattr(self.instance, "course", None))
        if criteria is None:
            return attrs
        if not criteria:
            raise serializers.ValidationError({"criteria": "A rubric needs at least one criterion."})
        for index, criterion in enumerate(criteria):
            levels = criterion.get("levels") or []
            if len(levels) < 2:
                raise serializers.ValidationError({"criteria": f"Criterion {index + 1} needs at least two levels."})
            labels = [level["label"] for level in levels]
            if len(labels) != len(set(labels)):
                raise serializers.ValidationError({"criteria": f"Criterion {index + 1} has duplicate level labels."})
            if any(level["score"] < 0 for level in levels):
                raise serializers.ValidationError({"criteria": "Level scores can't be negative."})
            if criterion.get("weight", Decimal(1)) <= 0:
                raise serializers.ValidationError({"criteria": "Criterion weight must be greater than zero."})
            co = criterion.get("course_outcome")
            if co is not None and (course is None or co.course_id != course.id):
                raise serializers.ValidationError(
                    {"criteria": f"Criterion {index + 1}: the course outcome must belong to the rubric's course."}
                )
        return attrs

    @staticmethod
    def _write_criteria(rubric, criteria):
        for position, criterion_data in enumerate(criteria):
            levels = criterion_data.pop("levels")
            criterion_data.setdefault("order", position)
            criterion = RubricCriterion.objects.create(rubric=rubric, **criterion_data)
            RubricLevel.objects.bulk_create([RubricLevel(criterion=criterion, **level) for level in levels])

    @transaction.atomic
    def create(self, validated_data):
        criteria = validated_data.pop("criteria")
        rubric = Rubric.objects.create(**validated_data)
        self._write_criteria(rubric, criteria)
        return rubric

    @transaction.atomic
    def update(self, instance, validated_data):
        criteria = validated_data.pop("criteria", None)
        if criteria is not None and instance.assessments.exists():
            raise serializers.ValidationError(
                {"criteria": "This rubric has already been used to assess students, so its criteria and "
                             "levels can't change. Copy it into a new rubric instead."}
            )
        if "course" in validated_data and validated_data["course"] != instance.course and instance.assessments.exists():
            raise serializers.ValidationError({"course": "A rubric that has been used can't move to another course."})
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if criteria is not None:
            instance.criteria.all().delete()
            self._write_criteria(instance, criteria)
        return instance


class RubricViewSet(viewsets.ModelViewSet):
    serializer_class = RubricSerializer
    permission_classes = RUBRIC_PERMS

    def get_queryset(self):
        user = self.request.user
        qs = Rubric.objects.select_related("course").prefetch_related("criteria__levels", "criteria__course_outcome")
        if not is_faculty_or_above(user):
            raise PermissionDenied("Only faculty and above manage rubrics.")
        params = self.request.query_params
        if params.get("course"):
            qs = qs.filter(course_id=params["course"])
        if params.get("applies_to"):
            qs = qs.filter(applies_to=params["applies_to"])
        if params.get("active") in ("1", "true"):
            qs = qs.filter(is_active=True)
        return qs

    def _check_course_access(self, course):
        user = self.request.user
        if course is None or is_hm_or_above(user):
            return
        if course.id not in set(_taught_course_ids(user)):
            raise PermissionDenied("You can only create rubrics for courses you teach.")

    def perform_create(self, serializer):
        self._check_course_access(serializer.validated_data.get("course"))
        serializer.save(created_by=self.request.user)

    def _check_owner(self, rubric):
        user = self.request.user
        if rubric.created_by_id != user.id and not is_hm_or_above(user):
            raise PermissionDenied("Only the rubric's author or an HOD/Admin can change it.")

    def perform_update(self, serializer):
        self._check_owner(serializer.instance)
        if "course" in serializer.validated_data:
            self._check_course_access(serializer.validated_data["course"])
        serializer.save()

    def perform_destroy(self, instance):
        self._check_owner(instance)
        if instance.assessments.exists():
            instance.is_active = False
            instance.save(update_fields=["is_active"])
        else:
            instance.delete()


# ── Assessments ─────────────────────────────────────────────────────────────

class RubricScoreSerializer(serializers.ModelSerializer):
    criterion_title = serializers.CharField(source="criterion.title", read_only=True)
    level_label = serializers.CharField(source="level.label", read_only=True)
    level_score = serializers.DecimalField(source="level.score", max_digits=6, decimal_places=2, read_only=True)

    class Meta:
        model = RubricScore
        fields = ["id", "criterion", "criterion_title", "level", "level_label", "level_score", "comment"]


class RubricAssessmentSerializer(serializers.ModelSerializer):
    scores = RubricScoreSerializer(many=True)
    rubric_name = serializers.CharField(source="rubric.name", read_only=True)
    student_name = serializers.SerializerMethodField()
    student_display_id = serializers.CharField(source="student.student_id", read_only=True)
    evaluator_name = serializers.SerializerMethodField()

    class Meta:
        model = RubricAssessment
        fields = [
            "id", "rubric", "rubric_name", "student", "student_name", "student_display_id",
            "evaluator", "evaluator_name", "assignment", "exam", "context_label", "overall_comment",
            "scores", "total_score", "max_score", "assessed_at", "updated_at",
        ]
        read_only_fields = ["evaluator", "total_score", "max_score"]

    def get_student_name(self, obj):
        return obj.student.user.get_full_name() or obj.student.user.username

    def get_evaluator_name(self, obj):
        return obj.evaluator.get_full_name() if obj.evaluator else None

    def validate(self, attrs):
        rubric = attrs.get("rubric", getattr(self.instance, "rubric", None))
        if self.instance is not None and "rubric" in attrs and attrs["rubric"] != self.instance.rubric:
            raise serializers.ValidationError({"rubric": "An assessment can't switch rubric."})
        if not rubric.is_active and self.instance is None:
            raise serializers.ValidationError({"rubric": "This rubric is inactive."})

        assignment = attrs.get("assignment")
        exam = attrs.get("exam")
        if rubric.course_id:
            if assignment is not None and assignment.course_id != rubric.course_id:
                raise serializers.ValidationError({"assignment": "Assignment is for a different course than the rubric."})
            if exam is not None and exam.course_id != rubric.course_id:
                raise serializers.ValidationError({"exam": "Exam is for a different course than the rubric."})

        scores = attrs.get("scores")
        if scores is not None:
            criteria = {c.id: c for c in rubric.criteria.all()}
            seen = set()
            for score in scores:
                criterion, level = score["criterion"], score["level"]
                if criterion.id not in criteria:
                    raise serializers.ValidationError({"scores": f"'{criterion.title}' is not part of this rubric."})
                if level.criterion_id != criterion.id:
                    raise serializers.ValidationError({"scores": f"Level '{level.label}' is not a level of '{criterion.title}'."})
                if criterion.id in seen:
                    raise serializers.ValidationError({"scores": f"'{criterion.title}' is scored twice."})
                seen.add(criterion.id)
            missing = [c.title for cid, c in criteria.items() if cid not in seen]
            if missing:
                raise serializers.ValidationError({"scores": f"Score every criterion. Missing: {', '.join(missing)}."})
        return attrs

    @staticmethod
    def _write_scores(assessment, scores):
        assessment.scores.all().delete()
        RubricScore.objects.bulk_create([RubricScore(assessment=assessment, **score) for score in scores])
        total = Decimal(0)
        for score in scores:
            total += score["level"].score * score["criterion"].weight
        assessment.total_score = total
        assessment.max_score = Decimal(str(assessment.rubric.max_score))
        assessment.save(update_fields=["total_score", "max_score"])

    @transaction.atomic
    def create(self, validated_data):
        scores = validated_data.pop("scores")
        assessment = RubricAssessment.objects.create(**validated_data)
        self._write_scores(assessment, scores)
        return assessment

    @transaction.atomic
    def update(self, instance, validated_data):
        scores = validated_data.pop("scores", None)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.save()
        if scores is not None:
            self._write_scores(instance, scores)
        return instance


class RubricAssessmentViewSet(viewsets.ModelViewSet):
    serializer_class = RubricAssessmentSerializer
    permission_classes = RUBRIC_PERMS

    def get_queryset(self):
        user = self.request.user
        qs = RubricAssessment.objects.select_related(
            "rubric", "student__user", "evaluator",
        ).prefetch_related("scores__criterion", "scores__level")

        student = _student_profile(user)
        if student is not None:
            return qs.filter(student=student)
        if not is_faculty_or_above(user):
            raise PermissionDenied("Only faculty and above assess with rubrics.")
        if not is_hm_or_above(user):
            qs = qs.filter(Q(evaluator=user) | Q(rubric__course_id__in=_taught_course_ids(user)))
        qs = qs.filter(student__in=scope_students(StudentProfile.objects.all(), user))

        params = self.request.query_params
        for param, lookup in (("rubric", "rubric_id"), ("student", "student_id"),
                              ("assignment", "assignment_id"), ("exam", "exam_id")):
            if params.get(param):
                qs = qs.filter(**{lookup: params[param]})
        return qs

    def _check_can_assess(self, rubric, student):
        user = self.request.user
        if _student_profile(user) is not None or not is_faculty_or_above(user):
            raise PermissionDenied("Only faculty and above assess with rubrics.")
        if not scope_students(StudentProfile.objects.filter(pk=student.pk), user).exists():
            raise PermissionDenied("This student is outside your data scope.")
        if rubric.course_id and not is_hm_or_above(user) and rubric.course_id not in set(_taught_course_ids(user)):
            raise PermissionDenied("You can only assess with rubrics for courses you teach.")

    def perform_create(self, serializer):
        self._check_can_assess(serializer.validated_data["rubric"], serializer.validated_data["student"])
        serializer.save(evaluator=self.request.user)

    def perform_update(self, serializer):
        instance = serializer.instance
        user = self.request.user
        if instance.evaluator_id != user.id and not is_college_admin(user):
            raise PermissionDenied("Only the evaluator or a College Admin can change this assessment.")
        serializer.save()

    def perform_destroy(self, instance):
        user = self.request.user
        if instance.evaluator_id != user.id and not is_college_admin(user):
            raise PermissionDenied("Only the evaluator or a College Admin can delete this assessment.")
        instance.delete()

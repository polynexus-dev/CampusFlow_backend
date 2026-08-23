from django.db import connection
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from ..demo_guard import IsNotDemoTenant
from ..models.outcomes import CourseOutcome
from ..models.result import StudentExamResult
from ..models.student_insight import StudentInsightSnapshot
from ..models.submission import AssignmentSubmission
from ..models.valuation import ScannedPaper
from ..models.profile import StudentProfile
from ..permissions import get_user_group, is_faculty_or_above


def _resolve_student_profile(request):
    """
    Shared self-vs-student_id resolution used by every per-student
    evaluation endpoint below.

    Returns (profile, error_response). Exactly one of the two is None.
    """
    user = request.user
    student_id = request.query_params.get('student_id')

    if get_user_group(user) == 'student':
        profile = getattr(user, 'student_profile', None)
        if not profile:
            return None, Response(
                {"error": "No student profile found for this user."},
                status=status.HTTP_404_NOT_FOUND,
            )
        return profile, None

    # Guardian access — same check views/guardian.py's own endpoints already
    # use (guardian_profile.students is the link ParentLinkChildView builds),
    # kept here too so this resolver is the one place every student-facing
    # analytics view shares, rather than guardians getting a parallel path.
    guardian_profile = getattr(user, 'guardian_profile', None)
    if guardian_profile:
        if not student_id:
            return None, Response(
                {"error": "student_id query parameter is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not guardian_profile.students.filter(id=student_id).exists():
            return None, Response(
                {"error": "This student is not linked to your guardian account."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return StudentProfile.objects.get(pk=student_id), None

    if not is_faculty_or_above(user):
        return None, Response(
            {"error": "You do not have permission to view this data."},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not student_id:
        return None, Response(
            {"error": "student_id query parameter is required."},
            status=status.HTTP_400_BAD_REQUEST,
        )
    try:
        return StudentProfile.objects.get(pk=student_id), None
    except StudentProfile.DoesNotExist:
        return None, Response({"error": "Student not found."}, status=status.HTTP_404_NOT_FOUND)


def _compute_student_progress(profile):
    """
    The body of StudentProgressView, factored out so
    run_student_insight_generation (tasks.py) can recompute the same payload
    from inside a Celery worker, which has no request to hand to the view.
    Returns the same dict StudentProgressView.get() responds with.
    """
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
        entry = by_course.setdefault(key, {"course_name": key, "total_percentage": 0, "exam_count": 0, "failed_count": 0})
        entry["total_percentage"] += r.percentage or 0
        entry["exam_count"] += 1
        if not r.is_pass:
            entry["failed_count"] += 1
    by_course_list = [
        {
            "course_name": v["course_name"],
            "average_percentage": round(v["total_percentage"] / v["exam_count"], 2),
            "exam_count": v["exam_count"],
            "failed_count": v["failed_count"],
        }
        for v in by_course.values()
    ]

    # Strengths: highest-average courses. Areas to improve: courses with
    # a failed exam first, then lowest average — a course you're failing
    # matters more than a course that's merely below your best.
    strengths = sorted(by_course_list, key=lambda c: c["average_percentage"], reverse=True)[:2]
    areas_to_improve = sorted(
        by_course_list,
        key=lambda c: (c["failed_count"] == 0, c["average_percentage"]),
    )[:2]

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

    # Assignment feedback: `grade` is free text entered by faculty (e.g.
    # "A", "8/10") so it isn't averaged numerically — just surfaced as-is.
    submissions = (
        AssignmentSubmission.objects
        .filter(student=profile.user, status='graded')
        .select_related('assignment', 'assignment__course')
        .order_by('-submitted_at')[:20]
    )
    assignments = [
        {
            "assignment_id": s.assignment_id,
            "title": s.assignment.title,
            "course_name": s.assignment.course.course_name if s.assignment.course else None,
            "grade": s.grade,
            "feedback": s.feedback,
            "submitted_at": s.submitted_at.isoformat(),
        }
        for s in submissions
    ]

    return {
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
        "strengths": strengths,
        "areas_to_improve": areas_to_improve,
        "assignments": assignments,
    }


class StudentProgressView(APIView):
    """
    GET: Aggregated exam-score progress for a single student, plus
    auto-computed strengths/areas-to-improve and recent assignment feedback.
    Students see their own data. Faculty/Admin can pass ?student_id=<StudentProfile id>.
    Guardians can pass ?student_id=<StudentProfile id> for a linked child.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, error = _resolve_student_profile(request)
        if error:
            return error
        return Response(_compute_student_progress(profile), status=status.HTTP_200_OK)


class StudentTopicPerformanceView(APIView):
    """
    GET: Topic/skill-level strengths & weaknesses for a single student,
    derived from question-wise marks captured during blind valuation
    (ScannedPaper.question_scores) matched against each exam's
    question_structure (which optionally tags a question with a topic and,
    since the outcomes PR, a course outcome — see services/paper_sync.py).

    Only questions tagged with a topic contribute to `topics` — untagged/
    legacy questions are counted separately so the response is honest about
    how much of the student's grading data actually has topic coverage. The
    same loop, unchanged, also accumulates by course outcome into
    `course_outcomes`: this is the generalisation the CO-attainment engine
    needed, arrived at by adding one grouping key to an existing pass over
    the data rather than writing a second one.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        profile, error = _resolve_student_profile(request)
        if error:
            return error
        return Response(_compute_student_topic_performance(profile), status=status.HTTP_200_OK)


def _compute_student_topic_performance(profile):
    """
    The body of StudentTopicPerformanceView, factored out so
    run_student_insight_generation (tasks.py) can recompute the same payload
    from inside a Celery worker — see _compute_student_progress above for
    why. Returns the same dict StudentTopicPerformanceView.get() responds with.
    """
    papers = (
        ScannedPaper.objects
        .filter(student=profile, status='Evaluated')
        .select_related('session__exam')
    )

    topics = {}
        # Keyed by (course_id, co_code): a CO code is only unique within its
        # course (models/outcomes.py), so "CO1" in one course and "CO1" in
        # another must not be accumulated together.
    course_outcomes = {}
    untagged_marks_excluded = 0
    exams_considered = 0

    for paper in papers:
        structure = paper.session.exam.question_structure or {}
        scores = paper.question_scores or {}
        if not structure or not scores:
            continue
        exams_considered += 1

        for q_key, raw in scores.items():
            spec = structure.get(q_key)
            if spec is None:
                continue

            # question_scores entries come in from two live shapes:
            # a plain number, or a per-question dict carrying its own
            # {'score', 'max_marks', 'note'} (richer grading detail).
            obtained = raw.get('score') if isinstance(raw, dict) else raw
            try:
                obtained = float(obtained)
            except (TypeError, ValueError):
                continue

            if isinstance(spec, dict):
                topic = spec.get('topic')
                co_code = spec.get('course_outcome')
                max_marks = spec.get('marks')
            else:
                topic = None
                co_code = None
                max_marks = spec

            # An explicit max_marks captured alongside the score itself
            # reflects what was actually graded against — prefer it.
            if isinstance(raw, dict) and raw.get('max_marks') is not None:
                max_marks = raw.get('max_marks')

            try:
                max_marks = float(max_marks)
            except (TypeError, ValueError):
                continue

            # Topic and course-outcome tagging are independent — a
            # question missing one may still carry the other, so neither
            # check may gate the other's accumulation (an earlier draft
            # of this loop had a `continue` here that would have silently
            # dropped CO-only-tagged questions from course_outcomes).
            if not topic:
                untagged_marks_excluded += obtained
            else:
                entry = topics.setdefault(topic, {
                    "topic": topic,
                    "obtained": 0.0,
                    "max_marks": 0.0,
                    "question_count": 0,
                    "exam_ids": set(),
                })
                entry["obtained"] += obtained
                entry["max_marks"] += max_marks
                entry["question_count"] += 1
                entry["exam_ids"].add(paper.session.exam_id)

            if co_code:
                co_key = (paper.session.exam.course_id, co_code)
                co_entry = course_outcomes.setdefault(co_key, {
                    "course_id": paper.session.exam.course_id,
                    "code": co_code,
                    "obtained": 0.0,
                    "max_marks": 0.0,
                    "question_count": 0,
                    "exam_ids": set(),
                })
                co_entry["obtained"] += obtained
                co_entry["max_marks"] += max_marks
                co_entry["question_count"] += 1
                co_entry["exam_ids"].add(paper.session.exam_id)

    topic_list = [
        {
            "topic": t["topic"],
            "percentage": round((t["obtained"] / t["max_marks"]) * 100, 2) if t["max_marks"] else None,
            "obtained": t["obtained"],
            "max_marks": t["max_marks"],
            "question_count": t["question_count"],
            "exam_count": len(t["exam_ids"]),
        }
        for t in topics.values()
        if t["max_marks"]
    ]
    topic_list.sort(key=lambda t: t["percentage"], reverse=True)

    # CO definitions are looked up once, in bulk, across every course
    # touched by this student's papers — not per-question inside the loop
    # above, which would turn this into an N+1 over the same handful of
    # courses.
    co_course_ids = {c["course_id"] for c in course_outcomes.values()}
    co_definitions = {
        (co.course_id, co.code): co
        for co in CourseOutcome.objects.filter(course_id__in=co_course_ids)
    } if co_course_ids else {}

    course_outcome_list = []
    for c in course_outcomes.values():
        if not c["max_marks"]:
            continue
        percentage = round((c["obtained"] / c["max_marks"]) * 100, 2)
        definition = co_definitions.get((c["course_id"], c["code"]))
        course_outcome_list.append({
            "course_id": c["course_id"],
            "code": c["code"],
            "statement": definition.statement if definition else None,
            "percentage": percentage,
            "obtained": c["obtained"],
            "max_marks": c["max_marks"],
            "question_count": c["question_count"],
            "exam_count": len(c["exam_ids"]),
            "target_attainment_percent": (
                float(definition.target_attainment_percent) if definition else None
            ),
            "meets_target": (
                percentage >= float(definition.target_attainment_percent) if definition else None
            ),
        })
    course_outcome_list.sort(key=lambda c: c["percentage"], reverse=True)

    return {
        "student_id": profile.student_id,
        "student_name": profile.user.get_full_name() or profile.user.username,
        "topics": topic_list,
        "strengths": topic_list[:3],
        "areas_to_improve": sorted(topic_list, key=lambda t: t["percentage"])[:3],
        "course_outcomes": course_outcome_list,
        "exams_considered": exams_considered,
        "untagged_marks_excluded": untagged_marks_excluded,
    }


class StudentInsightView(APIView):
    """
    GET: The latest AI-generated performance insight for a student — a
    plain-language narrative plus concrete recommendations, interpreting
    the exact same data _compute_student_progress/_compute_student_topic_performance
    expose (see run_student_insight_generation in tasks.py, which recomputes
    it independently rather than trusting anything client-supplied).
    Returns {"status": "not_generated"} if none has been requested yet.

    POST: Queues a (re)generation. Same self/guardian/faculty access as the
    other analytics views above, via _resolve_student_profile.
    """
    permission_classes = [IsAuthenticated]

    def get_permissions(self):
        # Viewing an existing insight isn't mutating; only (re)generating one
        # is, so only POST is blocked in the public demo tenant — same
        # split every other AI-generation endpoint in this app uses.
        if self.request.method == "POST":
            return [IsAuthenticated(), IsNotDemoTenant()]
        return [IsAuthenticated()]

    def get(self, request):
        profile, error = _resolve_student_profile(request)
        if error:
            return error
        snapshot = StudentInsightSnapshot.objects.filter(student=profile).first()
        if not snapshot:
            return Response({"status": "not_generated"})
        return Response({
            "status": snapshot.status,
            "narrative_text": snapshot.narrative_text,
            "recommendations": snapshot.recommendations,
            "generated_at": snapshot.generated_at,
            "model_used": snapshot.model_used,
            "error_message": snapshot.error_message,
        })

    def post(self, request):
        from ..tasks import run_student_insight_generation

        profile, error = _resolve_student_profile(request)
        if error:
            return error

        snapshot, _ = StudentInsightSnapshot.objects.update_or_create(
            student=profile,
            defaults={
                "status": StudentInsightSnapshot.STATUS_PENDING,
                "requested_by": request.user,
                "narrative_text": "",
                "recommendations": [],
                "error_message": "",
            },
        )
        run_student_insight_generation.delay(connection.schema_name, snapshot.id)
        return Response({"status": "pending"}, status=status.HTTP_202_ACCEPTED)

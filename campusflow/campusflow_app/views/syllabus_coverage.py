"""
Syllabus Coverage Tracking
==========================
Per-CourseOffering checklist of which SyllabusTopics have actually been
taught, plus a naive term-elapsed-time pace comparison. Deliberately not an
approval workflow (unlike ResultCorrectionRequest) — a faculty member
updating their own checklist doesn't need HOD sign-off; the HOD role here
is an observer of the department-wide picture, not an approver of each row.

This is Phase 1 only: coverage tracking. No single/blended faculty score,
no cross-signal aggregation with StudentRiskScore/CO-PO attainment, no AI
narrative — those are explicitly deferred (see Docs/ plan discussion).
"""

from datetime import date

from django.utils.dateparse import parse_date
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from ..models import CourseOffering, SyllabusCoverageEntry, SyllabusTopic
from ..permissions import IsFacultyOrAbove, IsHMOrAbove, RequiresModule, is_college_admin, is_hm_or_above


def _compute_offering_pace(offering):
    """
    Shared by the checklist view's summary header and the HOD list view's
    per-row pace figure — same _compute_*(subject) convention as
    views/progress.py, so this stays reusable from a future Celery task
    without duplicating the aggregation logic.
    """
    topics_total = SyllabusTopic.objects.filter(course_id=offering.course_id).count()
    entries = SyllabusCoverageEntry.objects.filter(offering=offering)
    topics_covered = entries.filter(status=SyllabusCoverageEntry.STATUS_COVERED).count()
    topics_in_progress = entries.filter(status=SyllabusCoverageEntry.STATUS_IN_PROGRESS).count()

    coverage_pct = round((topics_covered / topics_total) * 100, 1) if topics_total else 0.0

    term = offering.term
    total_days = (term.end_date - term.start_date).days
    elapsed_days = (date.today() - term.start_date).days
    if total_days > 0:
        expected_pct = round(max(0.0, min(1.0, elapsed_days / total_days)) * 100, 1)
    else:
        expected_pct = 0.0

    # +-10 point tolerance band — a deliberate Phase 1 simplification (naive
    # linear pace against term-elapsed time; real syllabi aren't uniformly
    # paced, e.g. labs/projects cluster at term-end).
    diff = coverage_pct - expected_pct
    if diff >= 10:
        pace_status = "ahead"
    elif diff <= -10:
        pace_status = "behind"
    else:
        pace_status = "on_track"

    return {
        "topics_total": topics_total,
        "topics_covered": topics_covered,
        "topics_in_progress": topics_in_progress,
        "coverage_pct": coverage_pct,
        "expected_pct": expected_pct,
        "pace_status": pace_status,
    }


def _serialize_offering(offering, include_pace=True):
    data = {
        "id": offering.id,
        "course_id": offering.course_id,
        "course_code": offering.course.course_code,
        "course_name": offering.course.course_name,
        "term_id": offering.term_id,
        "term_name": str(offering.term),
        "batch_name": offering.batch.name,
        "section_name": offering.section.name if offering.section_id else None,
        "faculty_name": (
            offering.faculty.get_full_name() or offering.faculty.username
        ) if offering.faculty_id else None,
    }
    if include_pace:
        data.update(_compute_offering_pace(offering))
    return data


class MyOfferingsForCoverageView(APIView):
    """
    GET /api/syllabus-coverage/my-offerings/
    The requesting faculty member's own active course offerings for the
    current term, each with a coverage-pace summary — the offering picker
    a faculty member uses to open a checklist. Not a general CourseOffering
    listing endpoint; deliberately self-scoped only.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove, RequiresModule("syllabus-tracker")]

    def get(self, request):
        offerings = (
            CourseOffering.objects
            .filter(faculty=request.user, is_active=True, term__is_current=True)
            .select_related("course", "term", "batch", "section")
            .order_by("course__course_code")
        )
        return Response({"offerings": [_serialize_offering(o) for o in offerings]}, status=status.HTTP_200_OK)


class OfferingCoverageChecklistView(APIView):
    """
    GET  /api/syllabus-coverage/offerings/<offering_id>/
    POST /api/syllabus-coverage/offerings/<offering_id>/
    Payload (POST): {topic_id, status, covered_on?, remarks?}

    GET returns every SyllabusTopic on the offering's course, left-joined
    with any existing coverage entry (a topic with none yet reads as
    not_started) — the checklist auto-derives from SyllabusTopic, no
    separate provisioning step. POST upserts one (offering, topic) row.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove, RequiresModule("syllabus-tracker")]

    def _get_offering_or_403(self, request, offering_id):
        try:
            offering = CourseOffering.objects.select_related("course", "term", "batch", "section", "faculty").get(pk=offering_id)
        except CourseOffering.DoesNotExist:
            return None, Response({"error": "Course offering not found."}, status=status.HTTP_404_NOT_FOUND)

        if offering.faculty_id != request.user.id and not is_hm_or_above(request.user):
            return None, Response(
                {"error": "You can only view or update coverage for your own course offerings."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return offering, None

    def get(self, request, offering_id):
        offering, error = self._get_offering_or_403(request, offering_id)
        if error:
            return error

        entries_by_topic = {
            e.topic_id: e for e in SyllabusCoverageEntry.objects.filter(offering=offering)
        }
        topics = SyllabusTopic.objects.filter(course_id=offering.course_id).order_by("order", "name")

        rows = []
        for topic in topics:
            entry = entries_by_topic.get(topic.id)
            rows.append({
                "topic_id": topic.id,
                "topic_name": topic.name,
                "topic_order": topic.order,
                "status": entry.status if entry else SyllabusCoverageEntry.STATUS_NOT_STARTED,
                "covered_on": entry.covered_on.isoformat() if entry and entry.covered_on else None,
                "remarks": entry.remarks if entry else "",
                "updated_at": entry.updated_at.isoformat() if entry else None,
            })

        return Response({
            "offering": _serialize_offering(offering, include_pace=False),
            "pace": _compute_offering_pace(offering),
            "topics": rows,
        }, status=status.HTTP_200_OK)

    def post(self, request, offering_id):
        offering, error = self._get_offering_or_403(request, offering_id)
        if error:
            return error

        topic_id = request.data.get("topic_id")
        new_status = request.data.get("status")
        covered_on = request.data.get("covered_on")
        remarks = request.data.get("remarks", "")

        if not topic_id or not new_status:
            return Response({"error": "topic_id and status are required."}, status=status.HTTP_400_BAD_REQUEST)
        if new_status not in dict(SyllabusCoverageEntry.STATUS_CHOICES):
            return Response({"error": "Invalid status."}, status=status.HTTP_400_BAD_REQUEST)

        parsed_covered_on = None
        if covered_on:
            parsed_covered_on = parse_date(covered_on)
            if parsed_covered_on is None:
                return Response({"error": "covered_on must be a valid date (YYYY-MM-DD)."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            topic = SyllabusTopic.objects.get(pk=topic_id, course_id=offering.course_id)
        except SyllabusTopic.DoesNotExist:
            return Response({"error": "This topic does not belong to the offering's course."}, status=status.HTTP_400_BAD_REQUEST)

        entry, _created = SyllabusCoverageEntry.objects.update_or_create(
            offering=offering, topic=topic,
            defaults={
                "status": new_status,
                "covered_on": parsed_covered_on,
                "remarks": remarks,
                "updated_by": request.user,
            },
        )

        return Response({
            "topic_id": topic.id,
            "status": entry.status,
            "covered_on": entry.covered_on.isoformat() if entry.covered_on else None,
            "remarks": entry.remarks,
            "pace": _compute_offering_pace(offering),
        }, status=status.HTTP_200_OK)


class HODOfferingCoverageListView(APIView):
    """
    GET /api/syllabus-coverage/department-offerings/?term_id=
    Active course offerings in the HOD's own department this term (all
    departments for College/SaaS Admin), each with a coverage-pace summary
    — the department-wide dashboard. Defaults to the current term if
    term_id isn't given.
    """
    permission_classes = [IsAuthenticated, IsHMOrAbove, RequiresModule("syllabus-tracker")]

    def get(self, request):
        qs = (
            CourseOffering.objects
            .filter(is_active=True)
            .select_related("course", "term", "batch", "section", "faculty")
        )

        if not is_college_admin(request.user):
            departments = getattr(request.user, "departments_led", None)
            dept_ids = list(departments.values_list("id", flat=True)) if departments is not None else []
            qs = qs.filter(course__department_id__in=dept_ids)

        term_id = request.query_params.get("term_id")
        if term_id:
            qs = qs.filter(term_id=term_id)
        else:
            qs = qs.filter(term__is_current=True)

        offerings = qs.order_by("course__course_code")
        return Response({"offerings": [_serialize_offering(o) for o in offerings]}, status=status.HTTP_200_OK)

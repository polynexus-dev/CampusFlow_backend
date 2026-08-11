"""
campusflow_app/services/timetable_generation.py

CP-SAT-based automatic timetable generation (Google OR-Tools) — a classic
constraint-satisfaction "timetabling problem", not LLM-based. See
models/timetable_generation.py's docstring for the staging/apply pattern
this feeds into (a solve produces draft Schedule rows, never live ones).

v1 scope (see the plan's Context section for the full reasoning):
- One Term at a time, optionally narrowed to one Department.
- Each contact-hour (Course.total_contact_hours) becomes one independent
  1-hour weekly slot — no double-period/lab-block modeling yet.
- Feasibility only — no optimization objective, just "find *a* valid
  assignment."
- A fixed, settings-defined weekly slot grid (TIMETABLE_WORKING_DAYS x
  TIMETABLE_SLOT_START_TIMES), not a per-institution calendar config.
- Classroom-capacity and faculty-load constraints are only applied where
  the data exists (Classroom.capacity / Section.capacity /
  TeachingStaffProfile.max_weekly_teaching_hours) — graceful degradation,
  same philosophy as services/risk_scoring.py, since colleges won't have
  this filled in from day one.
"""

import datetime
from collections import defaultdict

from django.conf import settings
from ortools.sat.python import cp_model

from ..models.classroom import Classroom
from ..models.offerings import CourseOffering
from ..models.schedule import Schedule


class TimetableInfeasibleError(Exception):
    """
    Raised when the solver can't find a complete assignment — either because
    at least one session has zero feasible candidate slots at all (checked
    before solving, to fail fast with a precise offering list), or because
    CP-SAT itself reports INFEASIBLE/UNKNOWN within the time budget.
    """

    def __init__(self, unscheduled_offering_ids):
        self.unscheduled_offering_ids = unscheduled_offering_ids
        super().__init__(f"{len(unscheduled_offering_ids)} offering(s) could not be scheduled.")


def _default_slots():
    return [datetime.time(hour) for hour in (9, 10, 11, 12, 14, 15, 16)]


def _slot_grid():
    """(day_of_week, start_time) pairs for the fixed weekly grid."""
    days = getattr(settings, "TIMETABLE_WORKING_DAYS", None) or [
        "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
    ]
    slots = getattr(settings, "TIMETABLE_SLOT_START_TIMES", None) or _default_slots()
    return [(day, start) for day in days for start in slots]


def _existing_occupied(term):
    """
    (occupied_classroom, occupied_faculty): dict[id -> set[(day, start_time)]]
    from live (is_draft=False) Schedule rows already in this term — the
    solver must route around these. Schedule's own DB uniqueness constraint
    is keyed on `course`, so it does NOT stop two different courses'
    schedules colliding in the same room/time, nor protect faculty at all;
    this is done in Python instead.
    """
    occupied_classroom = defaultdict(set)
    occupied_faculty = defaultdict(set)
    for row in Schedule.objects.filter(term=term, is_draft=False).only(
        "classroom_id", "faculty_id", "day_of_week", "start_time",
    ):
        if row.classroom_id:
            occupied_classroom[row.classroom_id].add((row.day_of_week, row.start_time))
        occupied_faculty[row.faculty_id].add((row.day_of_week, row.start_time))
    return occupied_classroom, occupied_faculty


def generate_timetable(term, department=None, time_limit_seconds=None):
    """
    Solves the timetabling CSP for `term` (optionally narrowed to
    `department`). Returns a list of placement dicts:
    {"offering_id", "day_of_week", "start_time", "classroom_id", "faculty_id"}.
    Raises TimetableInfeasibleError (carrying the offering ids that
    couldn't be placed) if no complete assignment exists or is found within
    the time budget.
    """
    if time_limit_seconds is None:
        time_limit_seconds = getattr(settings, "TIMETABLE_SOLVER_TIME_LIMIT_SECONDS", 60)

    # faculty is required to produce a valid Schedule row (Schedule.faculty
    # is a non-nullable FK), so an offering with no assigned faculty yet
    # can't be scheduled — excluded here rather than surfaced as
    # "infeasible" partway through solving.
    offerings_qs = CourseOffering.objects.filter(
        term=term, is_active=True, faculty__isnull=False,
    ).select_related("course", "section", "batch", "faculty__teaching_staff_profile")
    if department is not None:
        offerings_qs = offerings_qs.filter(course__department=department)
    offerings = list(offerings_qs)
    offerings_by_id = {o.id: o for o in offerings}

    classrooms = list(Classroom.objects.all())
    grid = _slot_grid()
    occupied_classroom, occupied_faculty = _existing_occupied(term)

    faculty_caps = {}
    for offering in offerings:
        if offering.faculty_id and offering.faculty_id not in faculty_caps:
            profile = getattr(offering.faculty, "teaching_staff_profile", None)
            faculty_caps[offering.faculty_id] = getattr(profile, "max_weekly_teaching_hours", None)

    model = cp_model.CpModel()
    session_vars = defaultdict(list)       # (offering_id, session_index) -> [(var, day, start, classroom_id)]
    classroom_slot_vars = defaultdict(list)
    faculty_slot_vars = defaultdict(list)
    group_slot_vars = defaultdict(list)
    faculty_load_vars = defaultdict(list)  # faculty_id -> [var, ...], only populated when a cap is set

    for offering in offerings:
        sessions_needed = offering.course.total_contact_hours or 0
        if sessions_needed <= 0:
            continue

        section_capacity = offering.section.capacity if offering.section_id else None
        eligible_classrooms = [
            c for c in classrooms
            if section_capacity is None or c.capacity is None or c.capacity >= section_capacity
        ]
        group = f"section:{offering.section_id}" if offering.section_id else f"batch:{offering.batch_id}"
        cap = faculty_caps.get(offering.faculty_id)

        for session_index in range(sessions_needed):
            for day, start in grid:
                if offering.faculty_id and (day, start) in occupied_faculty.get(offering.faculty_id, ()):
                    continue
                for classroom in eligible_classrooms:
                    if (day, start) in occupied_classroom.get(classroom.id, ()):
                        continue
                    var = model.NewBoolVar(
                        f"o{offering.id}_s{session_index}_{day}_{start.isoformat()}_c{classroom.id}"
                    )
                    session_vars[(offering.id, session_index)].append((var, day, start, classroom.id))
                    classroom_slot_vars[(classroom.id, day, start)].append(var)
                    group_slot_vars[(group, day, start)].append(var)
                    if offering.faculty_id:
                        faculty_slot_vars[(offering.faculty_id, day, start)].append(var)
                        if cap is not None:
                            faculty_load_vars[offering.faculty_id].append(var)

    # Fail fast (before invoking the solver at all) on any session with zero
    # feasible candidates — e.g. every classroom too small for the section,
    # or the faculty/every room already fully blocked by live schedules.
    unresolvable_offering_ids = set()
    for offering in offerings:
        sessions_needed = offering.course.total_contact_hours or 0
        for session_index in range(sessions_needed):
            if not session_vars.get((offering.id, session_index)):
                unresolvable_offering_ids.add(offering.id)
    if unresolvable_offering_ids:
        raise TimetableInfeasibleError(sorted(unresolvable_offering_ids))

    for candidates in session_vars.values():
        model.Add(sum(v for v, *_ in candidates) == 1)
    for candidates in classroom_slot_vars.values():
        model.Add(sum(candidates) <= 1)
    for candidates in faculty_slot_vars.values():
        model.Add(sum(candidates) <= 1)
    for candidates in group_slot_vars.values():
        model.Add(sum(candidates) <= 1)
    for faculty_id, vlist in faculty_load_vars.items():
        model.Add(sum(vlist) <= faculty_caps[faculty_id])

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = time_limit_seconds
    result_status = solver.Solve(model)

    if result_status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise TimetableInfeasibleError(sorted(offerings_by_id.keys()))

    placements = []
    for (offering_id, _session_index), candidates in session_vars.items():
        for var, day, start, classroom_id in candidates:
            if solver.Value(var):
                placements.append({
                    "offering_id": offering_id,
                    "day_of_week": day,
                    "start_time": start,
                    "classroom_id": classroom_id,
                    "faculty_id": offerings_by_id[offering_id].faculty_id,
                })
    return placements

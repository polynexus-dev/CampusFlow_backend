"""
Management command: seed_demo_data
Seeds the given tenant schema with realistic demo data.

Usage:
    python manage.py seed_demo_data --schema mit
"""
from datetime import date, time, timedelta, datetime
import random
import string

from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from django_tenants.utils import schema_context
from django.utils import timezone
import datetime as dt

from campusflow_app.models.department import Department
from campusflow_app.models.course import Course
from campusflow_app.models.classroom import Classroom
from campusflow_app.models.schedule import Schedule
from campusflow_app.models.lecture import Lecture


COURSES = [
    ('CS101', 'Data Structures & Algorithms'),
    ('CS201', 'Database Management Systems'),
    ('CS301', 'Operating Systems'),
    ('CS401', 'Computer Networks'),
    ('CS501', 'Software Engineering'),
]

ROOMS = [
    ('Room 101', 'R101'),
    ('Room 102', 'R102'),
    ('Lab A',    'LABA'),
    ('Room 201', 'R201'),
    ('Room 202', 'R202'),
]

TIMETABLE = [
    # (day, start, end, course_code, room_code)
    ('Monday',    '09:00', '10:00', 'CS101', 'R101'),
    ('Monday',    '10:00', '11:00', 'CS201', 'R102'),
    ('Monday',    '11:15', '12:15', 'CS301', 'R201'),
    ('Tuesday',   '09:00', '10:00', 'CS401', 'R101'),
    ('Tuesday',   '10:00', '11:00', 'CS501', 'R102'),
    ('Tuesday',   '14:00', '15:00', 'CS101', 'LABA'),
    ('Wednesday', '09:00', '10:00', 'CS201', 'R201'),
    ('Wednesday', '11:00', '12:00', 'CS301', 'R202'),
    ('Thursday',  '09:00', '10:00', 'CS401', 'R101'),
    ('Thursday',  '11:00', '12:00', 'CS501', 'R201'),
    ('Friday',    '10:00', '11:00', 'CS101', 'R202'),
    ('Friday',    '11:00', '12:00', 'CS201', 'LABA'),
    ('Saturday',  '10:00', '12:00', 'CS301', 'LABA'),
]

DAY_IDX = {
    'Monday': 0, 'Tuesday': 1, 'Wednesday': 2,
    'Thursday': 3, 'Friday': 4, 'Saturday': 5, 'Sunday': 6
}


def rand_code(n=5):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=n))


class Command(BaseCommand):
    help = "Seed demo classrooms, courses, schedules and lectures for a tenant schema"
    requires_system_checks = []  # Skip URL/import checks (face_attendance needs cv2 which may not be local)

    def add_arguments(self, parser):
        parser.add_argument(
            '--schema', type=str, default='mit',
            help='Tenant schema name to seed (default: mit)'
        )
        parser.add_argument(
            '--weeks', type=int, default=2,
            help='Number of past weeks of lectures to create (default: 2)'
        )

    def handle(self, *args, **options):
        schema = options['schema']
        weeks  = options['weeks']
        self.stdout.write(self.style.MIGRATE_HEADING(f"\nSeeding demo data into schema: [{schema}]\n"))

        with schema_context(schema):

            # ── Faculty & Student ──────────────────────────────────────────
            faculty = (
                User.objects.filter(username__icontains='faculty').first()
                or User.objects.exclude(username__in=['admin', '']).first()
            )
            if not faculty:
                self.stderr.write("ERROR: No faculty user found. Create one first via admin panel.")
                return

            student = User.objects.filter(username__icontains='student').first()
            self.stdout.write(f"  Faculty : {faculty.username} (ID {faculty.id})")
            self.stdout.write(f"  Student : {student.username if student else 'N/A'}")

            # ── Department ────────────────────────────────────────────────
            dept, created = Department.objects.get_or_create(
                code='CS',
                defaults=dict(name='Computer Science', status='Active')
            )
            self.stdout.write(f"  {'[+]' if created else '[ ]'} Department: {dept}")

            # ── Courses ────────────────────────────────────────────────────
            course_map = {}
            for code, name in COURSES:
                obj, created = Course.objects.get_or_create(
                    course_code=code,
                    defaults=dict(course_name=name, department=dept)
                )
                course_map[code] = obj
                self.stdout.write(f"  {'[+]' if created else '[ ]'} Course: {obj}")

            # ── Classrooms ─────────────────────────────────────────────────
            room_map = {}
            for name, code in ROOMS:
                obj, created = Classroom.objects.get_or_create(
                    code=code,
                    defaults=dict(name=name)
                )
                room_map[code] = obj
                self.stdout.write(f"  {'[+]' if created else '[ ]'} Classroom: {obj}")

            # ── Schedules ──────────────────────────────────────────────────
            schedules_created = 0
            for day, s_str, e_str, ccode, rcode in TIMETABLE:
                try:
                    _, created = Schedule.objects.get_or_create(
                        course=course_map[ccode],
                        classroom=room_map[rcode],
                        day_of_week=day,
                        start_time=time.fromisoformat(s_str),
                        defaults=dict(
                            faculty=faculty,
                            end_time=time.fromisoformat(e_str),
                            semester='Semester 3',
                            academic_year='2025-2026',
                        )
                    )
                    if created:
                        schedules_created += 1
                        self.stdout.write(f"  [+] Schedule: {day} {s_str}-{e_str} {ccode}@{rcode}")
                except Exception as e:
                    self.stderr.write(f"  SKIP Schedule {day} {s_str} {ccode}: {e}")

            # ── Lectures ────────────────────────────────────────────────────
            today  = date.today()
            monday = today - timedelta(days=today.weekday())
            lectures_created = 0

            for week_offset in range(-weeks + 1, 1):  # e.g. -1, 0 for 2 weeks
                week_monday = monday + timedelta(weeks=week_offset)
                for day, s_str, e_str, ccode, rcode in TIMETABLE:
                    lecture_date = week_monday + timedelta(days=DAY_IDX[day])
                    start_dt = timezone.make_aware(datetime.combine(lecture_date, time.fromisoformat(s_str)))
                    end_dt   = timezone.make_aware(datetime.combine(lecture_date, time.fromisoformat(e_str)))
                    room     = room_map[rcode]
                    course   = course_map[ccode]

                    if Lecture.objects.filter(start_time=start_dt, classroom=room).exists():
                        continue

                    unique_code = f"L{ccode[2:]}{lecture_date.strftime('%d%m')}{rand_code(4)}"
                    try:
                        Lecture.objects.create(
                            name=f"{course.course_name} – {day}",
                            subject=course.course_name,
                            faculty=faculty,
                            classroom=room,
                            start_time=start_dt,
                            end_time=end_dt,
                            code=unique_code,
                        )
                        lectures_created += 1
                    except Exception as e:
                        self.stderr.write(f"  SKIP Lecture {lecture_date} {s_str} {ccode}: {e}")

            # ── Summary ────────────────────────────────────────────────────
            self.stdout.write(self.style.SUCCESS("\n=== SEEDING COMPLETE ==="))
            self.stdout.write(f"  Departments : {Department.objects.count()}")
            self.stdout.write(f"  Courses     : {Course.objects.count()}")
            self.stdout.write(f"  Classrooms  : {Classroom.objects.count()}")
            self.stdout.write(f"  Schedules   : {Schedule.objects.count()} (+{schedules_created} new)")
            self.stdout.write(f"  Lectures    : {Lecture.objects.count()} (+{lectures_created} new)")
            self.stdout.write(self.style.SUCCESS("\nStudent can now see timetable and attend lectures!"))

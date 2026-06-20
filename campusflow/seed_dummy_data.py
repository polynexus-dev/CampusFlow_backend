"""
CampusFlow Dummy Data Seeder
Run with: python manage.py shell < seed_dummy_data.py
  OR paste block-by-block into: python manage.py shell

This seeds the 'mit' tenant schema with:
  - 1 Department (Computer Science)
  - 5 Courses
  - 5 Classrooms
  - 13 Weekly Schedule entries
  - ~26 Lecture entries (current week + last week)
"""

from django_tenants.utils import schema_context
from django.contrib.auth.models import User
from campusflow_app.models.department import Department
from campusflow_app.models.course import Course
from campusflow_app.models.classroom import Classroom
from campusflow_app.models.schedule import Schedule
from campusflow_app.models.lecture import Lecture
from datetime import datetime, date, time, timedelta
import random, string

SCHEMA = 'mit'

with schema_context(SCHEMA):

    # ── 1. Get faculty & student users ──────────────────────────────────────
    faculty = User.objects.filter(username__icontains='faculty').first() \
           or User.objects.exclude(username='admin').first()
    student = User.objects.filter(username__icontains='student').first()

    if not faculty:
        print("ERROR: No faculty user found! Create one first.")
        raise SystemExit

    print(f"Faculty : {faculty.username} (ID {faculty.id})")
    print(f"Student : {student.username if student else 'None'} (ID {student.id if student else 'N/A'})")

    # ── 2. Department ────────────────────────────────────────────────────────
    dept, created = Department.objects.get_or_create(
        code='CS',
        defaults=dict(name='Computer Science', status='Active')
    )
    print(f"{'Created' if created else 'Found'} Department: {dept}")

    # ── 3. Courses ───────────────────────────────────────────────────────────
    COURSES = [
        ('CS101', 'Data Structures & Algorithms'),
        ('CS201', 'Database Management Systems'),
        ('CS301', 'Operating Systems'),
        ('CS401', 'Computer Networks'),
        ('CS501', 'Software Engineering'),
    ]
    course_map = {}
    for code, name in COURSES:
        obj, created = Course.objects.get_or_create(
            course_code=code,
            defaults=dict(course_name=name, department=dept)
        )
        course_map[code] = obj
        print(f"{'Created' if created else 'Found'} Course: {obj}")

    # ── 4. Classrooms ────────────────────────────────────────────────────────
    ROOMS = [
        ('Room 101', 'R101'),
        ('Room 102', 'R102'),
        ('Lab A',    'LABA'),
        ('Room 201', 'R201'),
        ('Room 202', 'R202'),
    ]
    room_map = {}
    for name, code in ROOMS:
        obj, created = Classroom.objects.get_or_create(
            code=code,
            defaults=dict(name=name)
        )
        room_map[code] = obj
        print(f"{'Created' if created else 'Found'} Classroom: {obj}")

    # ── 5. Weekly Schedules ──────────────────────────────────────────────────
    TIMETABLE = [
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

    schedule_objs = []
    for day, s_str, e_str, ccode, rcode in TIMETABLE:
        try:
            obj, created = Schedule.objects.get_or_create(
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
            schedule_objs.append(obj)
            print(f"{'Created' if created else 'Found'} Schedule: {day} {s_str}-{e_str} {ccode} @ {rcode}")
        except Exception as e:
            print(f"  SKIP Schedule {day} {s_str} {ccode}: {e}")

    # ── 6. Specific Lecture Sessions ─────────────────────────────────────────
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    DAY_IDX = {d: i for i, d in enumerate(['Monday','Tuesday','Wednesday','Thursday','Friday','Saturday','Sunday'])}

    lectures_created = 0
    for week_offset in [-1, 0]:
        week_monday = monday + timedelta(weeks=week_offset)
        for day, s_str, e_str, ccode, rcode in TIMETABLE:
            lecture_date = week_monday + timedelta(days=DAY_IDX[day])
            start_dt = datetime.combine(lecture_date, time.fromisoformat(s_str))
            end_dt   = datetime.combine(lecture_date, time.fromisoformat(e_str))
            course   = course_map[ccode]
            room     = room_map[rcode]
            subject  = course.course_name

            # Check existing
            if Lecture.objects.filter(start_time=start_dt, classroom=room).exists():
                print(f"  Lecture exists: {lecture_date} {s_str} {ccode}")
                continue

            # Generate unique code
            suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
            code_str = f"L{ccode[2:]}{lecture_date.strftime('%d%m')}{suffix}"

            try:
                lec = Lecture.objects.create(
                    name=f"{subject} – {day}",
                    subject=subject,
                    faculty=faculty,
                    classroom=room,
                    start_time=start_dt,
                    end_time=end_dt,
                    code=code_str,
                )
                lectures_created += 1
                print(f"  Created Lecture [{lec.code}]: {lec.name} on {lecture_date}")
            except Exception as e:
                print(f"  SKIP Lecture {lecture_date} {s_str} {ccode}: {e}")

    # ── 7. Summary ───────────────────────────────────────────────────────────
    print("\n" + "="*50)
    print("SEEDING COMPLETE")
    print("="*50)
    print(f"  Departments : {Department.objects.count()}")
    print(f"  Courses     : {Course.objects.count()}")
    print(f"  Classrooms  : {Classroom.objects.count()}")
    print(f"  Schedules   : {Schedule.objects.count()}")
    print(f"  Lectures    : {Lecture.objects.count()} (added {lectures_created} new)")
    print(f"  Faculty     : {faculty.username}")
    print(f"  Student     : {student.username if student else 'N/A'}")
    print("\nStudent can now see timetable and attend lectures!")

"""Add more timetable entries for a richer demo experience."""
import os, django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "campusflow.settings")
django.setup()

from django_tenants.utils import schema_context
from datetime import time

with schema_context("demo"):
    from campusflow_app.models import Schedule, Course, Classroom
    from django.contrib.auth.models import User

    u_faculty = User.objects.get(username="demo_faculty")
    u_faculty2 = User.objects.get(username="demo_faculty2")
    cs101 = Course.objects.get(course_code="CS101")
    cs201 = Course.objects.get(course_code="CS201")
    cs301 = Course.objects.get(course_code="CS301")
    it101 = Course.objects.get(course_code="IT101")
    it201 = Course.objects.get(course_code="IT201")
    r101 = Classroom.objects.get(code="R101")
    r102 = Classroom.objects.get(code="R102")
    laba = Classroom.objects.get(code="LABA")

    new_tt = [
        # More Tuesday slots for CS students
        ("Tuesday", "10:00", "11:00", cs201, r102, u_faculty),
        ("Tuesday", "11:00", "12:00", cs301, laba, u_faculty),
        # More Wednesday
        ("Wednesday", "10:00", "11:00", cs301, laba, u_faculty),
        ("Wednesday", "14:00", "15:00", it201, r102, u_faculty2),
        # More Thursday
        ("Thursday", "09:00", "10:00", cs101, r101, u_faculty),
        ("Thursday", "14:00", "15:00", cs201, r102, u_faculty),
        # Friday
        ("Friday", "09:00", "10:00", cs101, r101, u_faculty),
        ("Friday", "10:00", "11:00", cs301, laba, u_faculty),
        ("Friday", "14:00", "15:00", it101, r102, u_faculty2),
        # Saturday
        ("Saturday", "09:00", "10:00", cs201, r101, u_faculty),
    ]

    created_count = 0
    for day, s, e, course, room, fac in new_tt:
        obj, c = Schedule.objects.get_or_create(
            course=course, classroom=room, day_of_week=day, start_time=time.fromisoformat(s),
            defaults={
                "faculty": fac,
                "end_time": time.fromisoformat(e),
                "semester": "Semester 4",
                "academic_year": "2025-2026",
            }
        )
        if c:
            created_count += 1

    total = Schedule.objects.count()
    print(f"Created {created_count} new schedule entries. Total: {total}")

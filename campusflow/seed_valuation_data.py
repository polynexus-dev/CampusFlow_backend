"""
CampusFlow Digital Valuation Test Data Seeding Tool
===================================================
Usage:
  python seed_valuation_data.py
"""
import os
import django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'campusflow.settings')
django.setup()

import datetime
from django.contrib.auth.models import User, Group

from django.utils import timezone
from django_tenants.utils import schema_context
from campusflow_app.models.department import Department
from campusflow_app.models.course import Course
from campusflow_app.models.exam import ExamType, Exam
from campusflow_app.models.profile import StudentProfile, TeachingStaffProfile
from campusflow_app.models.valuation import ValuationSession, ScannedPaper

TARGET_SCHEMA = 'demo'

print(f"Starting digital valuation seeding for schema context: '{TARGET_SCHEMA}'")

try:
    with schema_context(TARGET_SCHEMA):
        # 1. Fetch default department
        dept, _ = Department.objects.get_or_create(
            code='GEN',
            defaults={'name': 'General Department', 'status': 'Active'}
        )

        # 2. Get or create Course
        math_course, _ = Course.objects.get_or_create(
            course_code='MATH101',
            defaults={'course_name': 'Mathematics 101', 'department': dept}
        )
        phys_course, _ = Course.objects.get_or_create(
            course_code='PHYS101',
            defaults={'course_name': 'Physics 101', 'department': dept}
        )

        # 3. Fetch default users
        faculty_user = User.objects.filter(username='demo_faculty').first()
        if not faculty_user:
            raise ValueError("Required user 'demo_faculty' not found. Please run seed_test_users.py first.")
        faculty_profile = TeachingStaffProfile.objects.filter(user=faculty_user).first()
        if not faculty_profile:
            raise ValueError("Required TeachingStaffProfile for 'demo_faculty' not found.")

        student_user = User.objects.filter(username='demo_student').first()
        if not student_user:
            raise ValueError("Required user 'demo_student' not found. Please run seed_test_users.py first.")
        student_profile = StudentProfile.objects.filter(user=student_user).first()
        if not student_profile:
            raise ValueError("Required StudentProfile for 'demo_student' not found.")

        # Ensure dynamic second test student for better listings
        student_user_2, _ = User.objects.get_or_create(
            username='demo_student_2',
            defaults={'email': 'student2@demo.edu', 'is_staff': False}
        )
        student_user_2.set_password('Password123')
        student_user_2.save()
        student_group = Group.objects.get(name='student')
        student_user_2.groups.add(student_group)

        student_profile_2, _ = StudentProfile.objects.get_or_create(
            user=student_user_2,
            defaults={
                'student_id': 'STU-DUMMY2',
                'department': dept,
                'status': 'active'
            }
        )

        # 4. Get or create ExamType
        mid_type, _ = ExamType.objects.get_or_create(
            code='MID',
            defaults={'name': 'Mid-Term Exam'}
        )

        # 5. Create Exams
        math_exam, _ = Exam.objects.get_or_create(
            name='Mathematics Mid-Term Exam June 2026',
            defaults={
                'exam_type': mid_type,
                'department': dept,
                'course': math_course,
                'date': datetime.date.today(),
                'start_time': datetime.time(9, 0),
                'end_time': datetime.time(12, 0),
                'total_marks': 100,
                'passing_marks': 35,
                'semester': 'Semester 1',
                'academic_year': '2025-2026',
                'status': 'completed'
            }
        )

        phys_exam, _ = Exam.objects.get_or_create(
            name='Physics Mid-Term Exam June 2026',
            defaults={
                'exam_type': mid_type,
                'department': dept,
                'course': phys_course,
                'date': datetime.date.today(),
                'start_time': datetime.time(14, 0),
                'end_time': datetime.time(17, 0),
                'total_marks': 100,
                'passing_marks': 35,
                'semester': 'Semester 1',
                'academic_year': '2025-2026',
                'status': 'completed'
            }
        )

        # 6. Set up Valuation Sessions
        # Session A: Active Session (Mathematics)
        math_session, _ = ValuationSession.objects.get_or_create(
            exam=math_exam,
            evaluator=faculty_profile,
            defaults={'status': 'Active'}
        )
        # Ensure status is active for testing updates
        math_session.status = 'Active'
        math_session.save()

        # Session B: Completed / Locked Session (Physics)
        phys_session, _ = ValuationSession.objects.get_or_create(
            exam=phys_exam,
            evaluator=faculty_profile,
            defaults={'status': 'Completed'}
        )
        phys_session.status = 'Completed'
        phys_session.save()

        # 7. Create Scanned Answer Sheets
        # Paper 1: Pending Grading (in Active Mathematics Session)
        paper_1, created_1 = ScannedPaper.objects.get_or_create(
            session=math_session,
            student=student_profile,
            defaults={
                'scanned_file_url': 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf',
                'status': 'Pending',
                'question_scores': {}
            }
        )
        if not created_1:
            paper_1.allocated_marks = None
            paper_1.status = 'Pending'
            paper_1.question_scores = {}
            paper_1.save()

        # Paper 2: Evaluated / Graded (in Active Mathematics Session)
        paper_2, created_2 = ScannedPaper.objects.get_or_create(
            session=math_session,
            student=student_profile_2,
            defaults={
                'scanned_file_url': 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf',
                'allocated_marks': 85.00,
                'status': 'Evaluated',
                'question_scores': {'Q1': 25, 'Q2': 20, 'Q3': 40},
                'evaluated_at': timezone.now()
            }
        )

        # Paper 3: Evaluated / Graded (in Completed/Locked Physics Session)
        paper_3, created_3 = ScannedPaper.objects.get_or_create(
            session=phys_session,
            student=student_profile,
            defaults={
                'scanned_file_url': 'https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf',
                'allocated_marks': 92.50,
                'status': 'Evaluated',
                'question_scores': {'Q1': 30, 'Q2': 32.5, 'Q3': 30},
                'evaluated_at': timezone.now()
            }
        )

        print("--------------------------------------------------")
        print("Digital Valuation test data seeded successfully!")
        print("Active Session Exam: Mathematics Mid-Term")
        print("Completed Session Exam: Physics Mid-Term")
        print("--------------------------------------------------")

except Exception as e:
    print(f"Error seeding digital valuation data: {str(e)}")

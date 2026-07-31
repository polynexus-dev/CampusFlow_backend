"""
Generic in-app notification service, shared by every workstream that needs
to notify a user or a student's guardians (bus events, homework posts, marks
publish, correction approvals, ...).

This creates pollable Notification rows (GET /api/notifications/). It does
NOT send real mobile push (FCM/APNs) — that needs Firebase project
credentials and a device-token model, which is a separate follow-up.
"""

from campusflow_app.models import Notification


def notify_user(user, title, body="", category="general", data=None):
    """Create a single in-app notification for one user."""
    return Notification.objects.create(
        recipient=user,
        title=title,
        body=body,
        category=category,
        data=data or {},
    )


def notify_guardians_of_student(student_profile, title, body="", category="general", data=None):
    """Create an in-app notification for every guardian linked to a student."""
    notifications = []
    for guardian in student_profile.guardians.select_related("user").all():
        notifications.append(
            notify_user(guardian.user, title, body=body, category=category, data=data)
        )
    return notifications


def notify_guardians_of_department(department_id, title, body="", category="general", data=None):
    """Create an in-app notification for every guardian of every student in a department."""
    from campusflow_app.models import StudentProfile

    notifications = []
    students = StudentProfile.objects.filter(department_id=department_id)
    for student_profile in students:
        notifications.extend(
            notify_guardians_of_student(student_profile, title, body=body, category=category, data=data)
        )
    return notifications


def notify_guardians_of_course_roster(course_id, department_id, title, body="", category="general", data=None):
    """
    Create an in-app notification for every guardian of every student actually
    taking a course — used for assignments, which are course-specific, unlike
    department-wide announcements.

    Falls back to the whole department when no roster exists for this course
    in the current term: CourseOffering/StudentCourseRegistration rows only
    exist where an admin has run bootstrap_offerings_from_exams or the
    offering was created directly, so most courses at most tenants have no
    roster yet. Notifying nobody because the roster is merely unpopulated
    would be a regression from today's department-wide behaviour, which this
    is meant to narrow, not replace, wherever real roster data exists.
    """
    from campusflow_app.models import StudentProfile
    from campusflow_app.models.offerings import CourseOffering, StudentCourseRegistration
    from campusflow_app.services.academics import get_current_term

    term = get_current_term()
    roster_student_ids = list(
        StudentCourseRegistration.objects.filter(
            offering__course_id=course_id, term=term,
            status=StudentCourseRegistration.STATUS_REGISTERED,
        ).values_list("student_id", flat=True)
    ) if term and CourseOffering.objects.filter(course_id=course_id, term=term).exists() else []

    if roster_student_ids:
        students = StudentProfile.objects.filter(id__in=roster_student_ids)
    else:
        students = StudentProfile.objects.filter(department_id=department_id)

    notifications = []
    for student_profile in students:
        notifications.extend(
            notify_guardians_of_student(student_profile, title, body=body, category=category, data=data)
        )
    return notifications

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

"""
ABC (Academic Bank of Credits) credit records.

Phase A (built): credits reach ABC through a CSV the college uploads on the
NAD / DigiLocker portal itself. This system produces that CSV
(views/abc_credit.py export), checks APAAR IDs first, and records the upload
the college reports back ("uploaded", with its batch reference). It never
claims a government system was contacted.

Phase B (not built): a direct ABC/NAD API call, once a client college's NAD
onboarding gives API credentials. That is what SYNC_SYNCED / SYNC_FAILED are
reserved for.

One ABCCreditEntry per (student, course, academic_year), created by
services/abc_credit.record_credit_entry() when an exam's results are
published (ExamPublishResultsView, views/result.py), since "credits earned"
only exists once a result is final.

What the college has to do on the government side (NAD registration, APAAR
IDs, the upload itself) is listed for staff on the ABC tab of the State
Portals page and in Docs/abc_nad_college_checklist.md.
"""
import re

from django.conf import settings
from django.db import models

from .academics import AcademicYear
from .course import Course
from .profile import StudentProfile


class ABCCreditEntry(models.Model):
    SYNC_PENDING = "pending"
    # Phase A: the college uploaded the CSV on the NAD portal and told us so.
    SYNC_UPLOADED = "uploaded"
    # Phase B only (direct API). Nothing sets these yet.
    SYNC_SYNCED = "synced"
    SYNC_FAILED = "failed"
    SYNC_STATUS_CHOICES = [
        (SYNC_PENDING, "Pending"),
        (SYNC_UPLOADED, "Uploaded to NAD"),
        (SYNC_SYNCED, "Synced"),
        (SYNC_FAILED, "Failed"),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name="abc_credit_entries")
    course = models.ForeignKey(Course, on_delete=models.CASCADE, related_name="abc_credit_entries")
    academic_year = models.ForeignKey(AcademicYear, on_delete=models.CASCADE, related_name="abc_credit_entries")
    credits_earned = models.DecimalField(max_digits=5, decimal_places=2)
    grade = models.CharField(max_length=5, blank=True)
    sync_status = models.CharField(max_length=10, choices=SYNC_STATUS_CHOICES, default=SYNC_PENDING)
    synced_at = models.DateTimeField(null=True, blank=True)
    upload_batch_reference = models.CharField(
        max_length=100, blank=True,
        help_text="Reference the NAD portal (or the university) gave for the upload batch.",
    )
    uploaded_on = models.DateField(null=True, blank=True, help_text="Date the college uploaded the CSV.")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
        related_name="abc_credit_uploads",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "ABC Credit Entry"
        verbose_name_plural = "ABC Credit Entries"
        ordering = ["-academic_year__start_date", "student__student_id"]
        constraints = [
            models.UniqueConstraint(
                fields=["student", "course", "academic_year"], name="uniq_abc_credit_entry",
            ),
        ]

    def __str__(self):
        return f"{self.student.student_id} — {self.course.course_code}: {self.credits_earned} cr [{self.sync_status}]"

    def mark_uploaded(self, batch_reference, uploaded_on, user):
        """Record that the college uploaded this entry on the NAD portal (Phase A)."""
        self.sync_status = self.SYNC_UPLOADED
        self.upload_batch_reference = batch_reference
        self.uploaded_on = uploaded_on
        self.uploaded_by = user
        self.save(update_fields=["sync_status", "upload_batch_reference", "uploaded_on", "uploaded_by"])


APAAR_RE = re.compile(r"^\d{12}$")


def apaar_problem(apaar_id):
    """
    Why this APAAR ID can't go into an ABC upload, or None if it looks fine.
    APAAR IDs are 12 digits. Only the format is checked here; whether the ID
    really belongs to the student is checked by the NAD portal on upload.
    """
    value = (apaar_id or "").strip()
    if not value:
        return "missing"
    if not APAAR_RE.match(value):
        return "malformed"
    return None

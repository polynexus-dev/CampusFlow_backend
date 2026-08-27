"""
ABC (Academic Bank of Credits) internal modeling — the part of roadmap gap
#14 buildable without a live government API. ABC/APAAR/DigiLocker's actual
integration (submitting credits to the real ABC portal, issuing documents
through DigiLocker) needs external API access this codebase doesn't have;
what's built here is everything on this system's own side of that
boundary — the record of what would be uploaded, and the pipeline trigger
point that produces it — so the real integration is a matter of replacing
`sync()`'s stub body with an actual API call, not inventing new
data model or a new place in the codebase to hook into.

One ABCCreditEntry per (student, course, academic_year), created by
services/abc_credit.record_credit_entry() when an exam's results are
published (see ExamPublishResultsView, views/result.py) — the same trigger
point that already fires guardian notifications, since "credits earned"
only exists once a result is final. `sync_status` starts and stays
"pending" until something calls `sync()`; `sync()` itself is intentionally
a no-op stub (see its docstring) rather than a fabricated success.
"""
from django.db import models
from django.utils import timezone

from .academics import AcademicYear
from .course import Course
from .profile import StudentProfile


class ABCCreditEntry(models.Model):
    SYNC_PENDING = "pending"
    SYNC_SYNCED = "synced"
    SYNC_FAILED = "failed"
    SYNC_STATUS_CHOICES = [
        (SYNC_PENDING, "Pending"),
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

    def sync(self):
        """
        Stub: no real ABC portal integration exists yet (see module
        docstring). Marks this entry synced so the rest of the workflow
        (status filtering, the "what's left to upload" view) has something
        real to operate against, without claiming a government system was
        actually contacted. Replace this body with the real API call when
        that integration is scoped.
        """
        self.sync_status = self.SYNC_SYNCED
        self.synced_at = timezone.now()
        self.save(update_fields=["sync_status", "synced_at"])

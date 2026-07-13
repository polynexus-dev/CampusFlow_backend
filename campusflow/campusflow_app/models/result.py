from django.db import models
from django.contrib.auth.models import User
from .exam import Exam
from .profile import StudentProfile


class StudentExamResult(models.Model):
    """
    Canonical per-student, per-exam marks record used to compute
    grades and drive student progress/evaluation reporting.
    """
    GRADE_CHOICES = [
        ('A+', 'A+'), ('A', 'A'), ('B+', 'B+'), ('B', 'B'),
        ('C', 'C'), ('D', 'D'), ('F', 'F'),
    ]

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='results')
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='exam_results')
    marks_obtained = models.DecimalField(max_digits=6, decimal_places=2)
    grade = models.CharField(max_length=5, choices=GRADE_CHOICES, blank=True, null=True)
    is_pass = models.BooleanField(default=False)
    remarks = models.TextField(blank=True, null=True)
    entered_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='exam_results_entered'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Student Exam Result"
        verbose_name_plural = "Student Exam Results"
        unique_together = ('exam', 'student')
        ordering = ['-exam__date']

    def __str__(self):
        return f"{self.student.student_id} — {self.exam.name}: {self.marks_obtained}/{self.exam.total_marks}"

    @property
    def percentage(self):
        if not self.exam.total_marks:
            return None
        return round((float(self.marks_obtained) / self.exam.total_marks) * 100, 2)

    def compute_grade(self):
        pct = self.percentage
        if pct is None:
            return None
        if pct >= 90:
            return 'A+'
        if pct >= 75:
            return 'A'
        if pct >= 60:
            return 'B+'
        if pct >= 50:
            return 'B'
        if pct >= 40:
            return 'C'
        pass_pct = (self.exam.passing_marks / self.exam.total_marks) * 100 if self.exam.total_marks else 0
        if pct >= pass_pct:
            return 'D'
        return 'F'

    def save(self, *args, **kwargs):
        self.is_pass = self.marks_obtained >= self.exam.passing_marks
        self.grade = self.compute_grade()
        super().save(*args, **kwargs)

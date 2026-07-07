from django.db import models
from .exam import Exam
from .profile import TeachingStaffProfile, StudentProfile
import random
import string


class ValuationSession(models.Model):
    STATUS_CHOICES = [
        ('Active', 'Active'),
        ('Completed', 'Completed'),
    ]

    exam = models.ForeignKey(Exam, on_delete=models.CASCADE, related_name='valuation_sessions')
    evaluator = models.ForeignKey(TeachingStaffProfile, on_delete=models.CASCADE, related_name='valuation_sessions')
    started_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')

    def __str__(self):
        return f"Valuation for {self.exam.name} by {self.evaluator.employee_id}"


class ScannedPaper(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending'),
        ('Evaluated', 'Evaluated'),
    ]

    session = models.ForeignKey(ValuationSession, on_delete=models.CASCADE, related_name='papers')
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='scanned_papers')
    scanned_file_url = models.CharField(max_length=500, help_text="S3 / storage URL of scanned answer script")
    allocated_marks = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    evaluated_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    remarks = models.TextField(blank=True, null=True)

    # New fields for college valuation requirements
    mask_code = models.CharField(max_length=50, unique=True, blank=True, null=True, help_text="Anonymous code for blind evaluation")
    question_scores = models.JSONField(default=dict, blank=True, help_text="Breakdown of marks by question (e.g. {'Q1': 10, 'Q2': 8})")

    def save(self, *args, **kwargs):
        if not self.mask_code:
            while True:
                code = "VAL-" + "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
                if not ScannedPaper.objects.filter(mask_code=code).exists():
                    self.mask_code = code
                    break
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Paper for {self.student.student_id} - {self.status}"

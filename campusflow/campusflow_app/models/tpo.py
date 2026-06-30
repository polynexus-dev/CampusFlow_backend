from django.db import models
from .profile import StudentProfile


class RecruitmentDrive(models.Model):
    STATUS_CHOICES = [
        ('Upcoming', 'Upcoming'),
        ('Active', 'Active'),
        ('Completed', 'Completed'),
    ]

    company_name = models.CharField(max_length=200)
    job_title = models.CharField(max_length=150)
    job_description = models.TextField(blank=True, null=True)
    eligibility_criteria = models.TextField(blank=True, null=True)
    package_lpa = models.DecimalField(max_digits=5, decimal_places=2, help_text="CTC package in Lakhs Per Annum")
    drive_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Active')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.company_name} - {self.job_title}"


class PlacementApplication(models.Model):
    STATUS_CHOICES = [
        ('Applied', 'Applied'),
        ('Shortlisted', 'Shortlisted'),
        ('Interviewing', 'Interviewing'),
        ('Selected', 'Selected'),
        ('Rejected', 'Rejected'),
    ]

    drive = models.ForeignKey(RecruitmentDrive, on_delete=models.CASCADE, related_name='applications')
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='placement_applications')
    applied_date = models.DateField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Applied')
    remarks = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('drive', 'student')

    def __str__(self):
        return f"{self.student.student_id} for {self.drive.company_name} ({self.status})"

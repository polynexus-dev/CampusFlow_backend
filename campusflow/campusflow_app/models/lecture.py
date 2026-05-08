from django.db import models
from ..models.classroom import Classroom

from django.contrib.auth.models import User

class Lecture(models.Model):
    name = models.CharField(max_length=255)
    subject = models.CharField(max_length=255)
    faculty = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='lectures', null=True, blank=True)
    classroom = models.ForeignKey(
        Classroom, on_delete=models.CASCADE, related_name='lectures')
    start_time = models.DateTimeField()
    end_time = models.DateTimeField()
    code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} | {self.classroom.name} ({self.start_time.strftime('%Y-%m-%d %H:%M')})"

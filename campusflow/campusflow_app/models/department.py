from django.db import models
from django.conf import settings
from django.core.validators import RegexValidator
from django.contrib.auth.models import User


class Department(models.Model):

    name = models.CharField(max_length=100)
    code = models.CharField(
        max_length=10,
        unique=True,
        validators=[RegexValidator(regex=r'^[A-Za-z0-9_]+$', message='Code must be alphanumeric or underscore')]
    )
    hod = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='departments_led',
        help_text='Head of Department (must be a Teacher with HOD role)'
    )
    email = models.EmailField(null=True, blank=True)
    phone_number = models.CharField(
        max_length=15,
        null=True,
        blank=True,
        validators=[RegexValidator(regex=r'^\+91-\d{3,4}-\d{6,7}$', message='Enter a valid Indian phone number')]
    )
    
    description = models.TextField(null=True, blank=True)
    accreditation_status = models.CharField(max_length=100, null=True, blank=True)
    date_established = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, default='Active')
    remarks = models.TextField(null=True, blank=True)
    created_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='departments_created'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='departments_updated'
    )
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

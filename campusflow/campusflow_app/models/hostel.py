from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from .profile import StudentProfile


class Hostel(models.Model):
    GENDER_CHOICES = [
        ('Boys', 'Boys'),
        ('Girls', 'Girls'),
        ('Co-ed', 'Co-ed'),
    ]

    name = models.CharField(max_length=100)
    gender_type = models.CharField(max_length=10, choices=GENDER_CHOICES, default='Boys')
    capacity = models.PositiveIntegerField(default=100)
    address = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name


class HostelRoom(models.Model):
    hostel = models.ForeignKey(Hostel, on_delete=models.CASCADE, related_name='rooms')
    room_number = models.CharField(max_length=20)
    capacity = models.PositiveIntegerField(default=4, help_text="Number of beds in this room")
    rent_per_semester = models.DecimalField(max_digits=10, decimal_places=2, default=25000.00)
    occupied_beds = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('hostel', 'room_number')

    def __str__(self):
        return f"{self.hostel.name} - Room {self.room_number}"


class HostelAllocation(models.Model):
    STATUS_CHOICES = [
        ('Allocated', 'Allocated'),
        ('Vacated', 'Vacated'),
    ]

    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='hostel_allocations')
    room = models.ForeignKey(HostelRoom, on_delete=models.CASCADE, related_name='allocations')
    academic_year = models.CharField(max_length=20, blank=True, null=True, help_text='e.g. 2026-2027')
    base_rent = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Base standard room rent")
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Concession/Scholarship discount")
    discount_reason = models.CharField(max_length=255, blank=True, help_text="Reason for fee concession")
    final_rent = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, help_text="Payable amount: base_rent - discount_amount")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_hostel_allocations")
    allocated_date = models.DateField(auto_now_add=True)
    vacated_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Allocated')
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if not self.base_rent or self.base_rent == 0:
            if self.room and self.room.rent_per_semester:
                self.base_rent = self.room.rent_per_semester
        base = Decimal(str(self.base_rent or 0.00))
        disc = Decimal(str(self.discount_amount or 0.00))
        self.final_rent = max(Decimal("0.00"), base - disc)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.student.student_id} allocated to {self.room.room_number} in {self.room.hostel.name}"

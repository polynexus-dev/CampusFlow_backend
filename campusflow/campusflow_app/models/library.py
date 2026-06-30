from django.db import models
from django.contrib.auth.models import User
from .profile import StudentProfile


class Book(models.Model):
    title = models.CharField(max_length=255)
    author = models.CharField(max_length=255)
    isbn = models.CharField(max_length=50, unique=True)
    publisher = models.CharField(max_length=150, blank=True, null=True)
    total_copies = models.PositiveIntegerField(default=1)
    available_copies = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.title


class BookCopy(models.Model):
    STATUS_CHOICES = [
        ('Available', 'Available'),
        ('Issued', 'Issued'),
        ('Lost', 'Lost'),
    ]

    book = models.ForeignKey(Book, on_delete=models.CASCADE, related_name='copies')
    barcode = models.CharField(max_length=100, unique=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Available')

    def __str__(self):
        return f"{self.book.title} ({self.barcode}) - {self.status}"


class BookIssue(models.Model):
    STATUS_CHOICES = [
        ('Issued', 'Issued'),
        ('Returned', 'Returned'),
        ('Overdue', 'Overdue'),
    ]

    book_copy = models.ForeignKey(BookCopy, on_delete=models.CASCADE, related_name='issues')
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='book_issues', null=True, blank=True)
    staff_user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='staff_book_issues', null=True, blank=True)
    issued_date = models.DateField(auto_now_add=True)
    due_date = models.DateField()
    returned_date = models.DateField(null=True, blank=True)
    fine_amount = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Issued')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        borrower = self.student.student_id if self.student else (self.staff_user.username if self.staff_user else 'Unknown')
        return f"{self.book_copy.book.title} issued to {borrower} ({self.status})"

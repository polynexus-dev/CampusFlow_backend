import uuid
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from .department import Department

User = get_user_model()


class FeeCategory(models.Model):
    """
    A category of fees (e.g. Tuition Fee, Hostel Fee, Exam Fee, Bus Fee, Library Fee).
    """
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Fee Category"
        verbose_name_plural = "Fee Categories"

    def __str__(self):
        return self.name


class FeeStructure(models.Model):
    """
    A template containing fee components for a department, program, batch, or semester.
    """
    name = models.CharField(max_length=255, help_text="e.g. CS Batch 2026 - Semester 1")
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fee_structures",
        help_text="Department this fee structure applies to (optional).",
    )
    batch_academic_year = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Academic year / batch, e.g. 2025-2026 (optional).",
    )
    program_enrolled_in = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Program code / degree, e.g. B.Tech CS (optional).",
    )
    current_semester_year = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        help_text="Current Semester / Year, e.g. Semester 1 (optional).",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Fee Structure"
        verbose_name_plural = "Fee Structures"

    def __str__(self):
        return self.name


class FeeStructureItem(models.Model):
    """
    Individual fee head amount inside a FeeStructure template.
    """
    fee_structure = models.ForeignKey(
        FeeStructure,
        on_delete=models.CASCADE,
        related_name="items",
    )
    category = models.ForeignKey(
        FeeCategory,
        on_delete=models.CASCADE,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Fee Structure Item"
        verbose_name_plural = "Fee Structure Items"
        unique_together = [("fee_structure", "category")]

    def __str__(self):
        return f"{self.fee_structure.name} - {self.category.name}: ₹{self.amount}"


class StudentFeeInvoice(models.Model):
    """
    Invoice generated for an individual student.
    """
    STATUS_UNPAID = "unpaid"
    STATUS_PARTIALLY_PAID = "partially_paid"
    STATUS_PAID = "paid"
    STATUS_CHOICES = [
        (STATUS_UNPAID, "Unpaid"),
        (STATUS_PARTIALLY_PAID, "Partially Paid"),
        (STATUS_PAID, "Paid"),
    ]

    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="fee_invoices",
        help_text="The student to whom this invoice is billed.",
    )
    fee_structure = models.ForeignKey(
        FeeStructure,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="invoices",
        help_text="The fee structure this invoice was generated from (optional).",
    )
    invoice_number = models.CharField(max_length=50, unique=True, blank=True)
    due_date = models.DateField()
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_UNPAID)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Student Fee Invoice"
        verbose_name_plural = "Student Fee Invoices"

    def __str__(self):
        return f"Invoice {self.invoice_number} - {self.student.get_full_name()} (Dues: ₹{self.remaining_balance})"

    @property
    def remaining_balance(self):
        return max(0, self.total_amount - self.discount_amount - self.paid_amount)

    def update_payment_status(self):
        """Recalculate total payments and update status accordingly."""
        payments = self.payments.all()
        total_paid = sum(p.amount_paid for p in payments)
        self.paid_amount = total_paid

        net_amount = self.total_amount - self.discount_amount
        if self.paid_amount >= net_amount:
            self.status = self.STATUS_PAID
        elif self.paid_amount > 0:
            self.status = self.STATUS_PARTIALLY_PAID
        else:
            self.status = self.STATUS_UNPAID
        self.save(update_fields=["paid_amount", "status"])

    def save(self, *args, **kwargs):
        if not self.invoice_number:
            timestamp = timezone.now().strftime("%Y%m%d%H%M%S")
            short_id = uuid.uuid4().hex[:6].upper()
            self.invoice_number = f"INV-{timestamp}-{short_id}"
        super().save(*args, **kwargs)


class StudentFeeInvoiceItem(models.Model):
    """
    Detailed items of a student fee invoice.
    """
    invoice = models.ForeignKey(
        StudentFeeInvoice,
        on_delete=models.CASCADE,
        related_name="items",
    )
    category = models.ForeignKey(
        FeeCategory,
        on_delete=models.CASCADE,
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Student Fee Invoice Item"
        verbose_name_plural = "Student Fee Invoice Items"
        unique_together = [("invoice", "category")]

    def __str__(self):
        return f"{self.invoice.invoice_number} - {self.category.name}: ₹{self.amount}"


class FeePayment(models.Model):
    """
    Recording fee payment transactions.
    """
    METHOD_CASH = "cash"
    METHOD_UPI = "upi"
    METHOD_CARD = "card"
    METHOD_NET_BANKING = "net_banking"
    METHOD_CHOICES = [
        (METHOD_CASH, "Cash"),
        (METHOD_UPI, "UPI"),
        (METHOD_CARD, "Card"),
        (METHOD_NET_BANKING, "Net Banking"),
    ]

    invoice = models.ForeignKey(
        StudentFeeInvoice,
        on_delete=models.CASCADE,
        related_name="payments",
    )
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=METHOD_CHOICES, default=METHOD_CASH)
    transaction_reference = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Reference ID for UPI, Bank Transfer or Card slip.",
    )
    receipt_number = models.CharField(max_length=50, unique=True, blank=True)
    payment_date = models.DateTimeField(default=timezone.now)
    remarks = models.TextField(blank=True, null=True)
    collected_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="collected_payments",
        help_text="Admin/Staff user who collected this fee.",
    )

    class Meta:
        verbose_name = "Fee Payment"
        verbose_name_plural = "Fee Payments"

    def __str__(self):
        return f"Receipt {self.receipt_number} - ₹{self.amount_paid} for {self.invoice.invoice_number}"

    def save(self, *args, **kwargs):
        if not self.receipt_number:
            timestamp = timezone.now().strftime("%Y%m%d")
            short_id = uuid.uuid4().hex[:6].upper()
            self.receipt_number = f"REC-{timestamp}-{short_id}"
        super().save(*args, **kwargs)
        self.invoice.update_payment_status()

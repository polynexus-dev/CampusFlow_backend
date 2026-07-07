from django.db import models
from django.contrib.auth import get_user_model
from .fees import StudentFeeInvoice

User = get_user_model()


class PaymentGatewayTransaction(models.Model):
    """
    One attempt to pay a StudentFeeInvoice online through a payment gateway.
    A successful transaction results in a FeePayment (see fees.py) being
    created so the existing invoice/dues logic stays untouched.
    """
    GATEWAY_RAZORPAY = "razorpay"
    GATEWAY_CASHFREE = "cashfree"
    GATEWAY_PAYU = "payu"
    GATEWAY_PHONEPE = "phonepe"
    GATEWAY_PAYTM = "paytm"
    GATEWAY_MOBIKWIK = "mobikwik"
    GATEWAY_CHOICES = [
        (GATEWAY_RAZORPAY, "Razorpay"),
        (GATEWAY_CASHFREE, "Cashfree"),
        (GATEWAY_PAYU, "PayU"),
        (GATEWAY_PHONEPE, "PhonePe"),
        (GATEWAY_PAYTM, "Paytm"),
        (GATEWAY_MOBIKWIK, "MobiKwik (Zaakpay)"),
    ]

    STATUS_CREATED = "created"
    STATUS_PAID = "paid"
    STATUS_FAILED = "failed"
    STATUS_REFUNDED = "refunded"
    STATUS_CHOICES = [
        (STATUS_CREATED, "Created"),
        (STATUS_PAID, "Paid"),
        (STATUS_FAILED, "Failed"),
        (STATUS_REFUNDED, "Refunded"),
    ]

    invoice = models.ForeignKey(
        StudentFeeInvoice, on_delete=models.CASCADE, related_name="gateway_transactions",
    )
    initiated_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="payment_transactions",
    )
    gateway = models.CharField(max_length=20, choices=GATEWAY_CHOICES)
    gateway_order_id = models.CharField(max_length=255, blank=True, null=True)
    gateway_payment_id = models.CharField(max_length=255, blank=True, null=True)

    amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="Base amount applied to the invoice.")
    convenience_fee_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, help_text="What the payer is actually charged (amount + convenience_fee_amount).")
    currency = models.CharField(max_length=10, default="INR")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_CREATED)
    raw_create_response = models.JSONField(default=dict, blank=True)
    raw_webhook_payload = models.JSONField(default=dict, blank=True)
    failure_reason = models.TextField(blank=True, null=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Payment Gateway Transaction"
        verbose_name_plural = "Payment Gateway Transactions"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.gateway}:{self.gateway_order_id} - {self.status} (₹{self.total_amount})"

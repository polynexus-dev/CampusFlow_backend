from django.db import models
from django_tenants.models import TenantMixin, DomainMixin
from campusflow_app.fields import EncryptedCharField


class Tenant(TenantMixin):
    """
    Each tenant represents a college.
    The schema_name field is inherited from TenantMixin.
    """
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    logo = models.ImageField(upload_to='tenant_logos/', blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    permitted_email_domain = models.CharField(max_length=100, blank=True, null=True, help_text="e.g. mit.edu.in. If set, students must register with this domain.")
    created_on = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    timezone = models.CharField(max_length=100, default='Asia/Kolkata', help_text="e.g. Asia/Kolkata")
    subscribed_modules = models.JSONField(
        default=list,
        blank=True,
        help_text="List of modules subscribed by this college, e.g. ['attendance', 'exams', 'fees']"
    )


    # SMTP / Email configuration (optional/non-operational for now)
    email_smtp_host = models.CharField(max_length=255, blank=True, null=True)
    email_smtp_port = models.IntegerField(blank=True, null=True, default=587)
    email_smtp_username = models.CharField(max_length=255, blank=True, null=True)
    email_smtp_password = models.CharField(max_length=255, blank=True, null=True)

    # ERP Product Integration configuration (optional/non-operational for now)
    erp_system_name = models.CharField(max_length=100, blank=True, null=True, help_text="e.g. SAP, Banner, Custom ERP")
    erp_api_url = models.CharField(max_length=500, blank=True, null=True)
    erp_auth_token = models.CharField(max_length=500, blank=True, null=True)

    # Billing Settings
    billing_student_rate = models.DecimalField(max_digits=10, decimal_places=2, default=50.00)
    billing_student_discount = models.DecimalField(max_digits=10, decimal_places=2, default=10.00)
    billing_employee_rate = models.DecimalField(max_digits=10, decimal_places=2, default=100.00)
    billing_employee_discount = models.DecimalField(max_digits=10, decimal_places=2, default=100.00)

    # Payment Gateway Configuration
    GATEWAY_MANUAL = 'manual'
    GATEWAY_RAZORPAY = 'razorpay'
    GATEWAY_CASHFREE = 'cashfree'
    GATEWAY_PAYU = 'payu'
    GATEWAY_PHONEPE = 'phonepe'
    GATEWAY_PAYTM = 'paytm'
    GATEWAY_MOBIKWIK = 'mobikwik'
    GATEWAY_CHOICES = [
        (GATEWAY_MANUAL, 'Manual (Offline / Cash)'),
        (GATEWAY_RAZORPAY, 'Razorpay'),
        (GATEWAY_CASHFREE, 'Cashfree'),
        (GATEWAY_PAYU, 'PayU'),
        (GATEWAY_PHONEPE, 'PhonePe'),
        (GATEWAY_PAYTM, 'Paytm'),
        (GATEWAY_MOBIKWIK, 'MobiKwik (Zaakpay)'),
    ]

    SURCHARGE_ABSORB = 'absorb'
    SURCHARGE_PASS = 'pass_to_student'
    SURCHARGE_CHOICES = [
        (SURCHARGE_ABSORB, 'Absorb fees (College pays transaction cost)'),
        (SURCHARGE_PASS, 'Pass surcharge to student (Student pays convenience fee)'),
    ]

    payment_gateway_active = models.CharField(
        max_length=20,
        choices=GATEWAY_CHOICES,
        default=GATEWAY_MANUAL
    )
    fee_surcharge_mode = models.CharField(
        max_length=20,
        choices=SURCHARGE_CHOICES,
        default=SURCHARGE_ABSORB
    )
    negotiated_education_rates = models.BooleanField(
        default=False,
        help_text="Enable negotiated education rates (e.g. ~0% UPI MDR/platform fees for colleges)"
    )
    convenience_fee_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=0,
        help_text="Percentage charged to the payer on top of the fee amount when fee_surcharge_mode=pass_to_student."
    )

    # Razorpay credentials
    razorpay_key_id = models.CharField(max_length=255, blank=True, null=True)
    razorpay_key_secret = EncryptedCharField(blank=True, null=True)
    razorpay_webhook_secret = EncryptedCharField(blank=True, null=True, help_text="Secret configured in the Razorpay dashboard's Webhooks section, used to verify webhook signatures.")

    # Cashfree credentials
    cashfree_app_id = models.CharField(max_length=255, blank=True, null=True)
    cashfree_secret_key = EncryptedCharField(blank=True, null=True)

    # PayU credentials
    payu_merchant_key = models.CharField(max_length=255, blank=True, null=True)
    payu_merchant_salt = EncryptedCharField(blank=True, null=True)

    # PhonePe credentials
    phonepe_merchant_id = models.CharField(max_length=255, blank=True, null=True)
    phonepe_salt_key = EncryptedCharField(blank=True, null=True)
    phonepe_salt_index = models.CharField(max_length=50, blank=True, null=True)

    # Paytm credentials
    paytm_merchant_id = models.CharField(max_length=255, blank=True, null=True)
    paytm_merchant_key = EncryptedCharField(blank=True, null=True)

    # MobiKwik (Zaakpay) credentials
    mobikwik_merchant_id = models.CharField(max_length=255, blank=True, null=True)
    mobikwik_secret_key = EncryptedCharField(blank=True, null=True)

    # Subscribed Modules
    subscribed_modules = models.JSONField(
        default=list,
        blank=True,
        help_text="Modules subscribed by this tenant (e.g. ['Hostel', 'TPO', 'Library', 'Inventory', 'Valuation', 'Leave', 'Payroll', 'Exams', 'Assignments', 'Attendance', 'Announcements'])"
    )


    # Default: auto-create schema on save
    auto_create_schema = True

    class Meta:
        verbose_name = "Tenant (College)"
        verbose_name_plural = "Tenants (Colleges)"

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    """
    Each tenant can have multiple domains.
    One domain must be marked as primary (is_primary=True).
    """

    class Meta:
        verbose_name = "Domain"
        verbose_name_plural = "Domains"

    def __str__(self):
        return f"{self.domain} -> {self.tenant.name}"

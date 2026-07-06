from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


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

    # Subscribed Modules
    subscribed_modules = models.JSONField(
        default=list,
        blank=True,
        help_text="Modules subscribed by this tenant (e.g. ['Hostel', 'TPO', 'Library', 'Inventory', 'Valuation', 'Leave', 'Payroll', 'Exams', 'Assignments', 'Attendance', 'Announcements'])"
    )

    # Subscription status and cycle
    subscription_status = models.CharField(
        max_length=20,
        choices=[('trial', 'Trial'), ('active', 'Active'), ('suspended', 'Suspended')],
        default='trial'
    )
    billing_cycle = models.CharField(
        max_length=20,
        choices=[('monthly', 'Monthly'), ('annual', 'Annual')],
        default='monthly'
    )
    trial_start_date = models.DateField(null=True, blank=True)
    trial_end_date = models.DateField(null=True, blank=True)
    subscription_end_date = models.DateField(null=True, blank=True)

    # Default: auto-create schema on save
    auto_create_schema = True

    class Meta:
        verbose_name = "Tenant (College)"
        verbose_name_plural = "Tenants (Colleges)"

    def __str__(self):
        return self.name


class Invoice(models.Model):
    """
    Manages offline bank-transfer B2B invoicing and validation.
    """
    tenant = models.ForeignKey(Tenant, on_delete=models.CASCADE, related_name='invoices')
    invoice_number = models.CharField(max_length=100, unique=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    billing_period_start = models.DateField()
    billing_period_end = models.DateField()
    due_date = models.DateField()
    
    status = models.CharField(
        max_length=30,
        choices=[
            ('pending_payment', 'Pending Payment'),
            ('under_review', 'Under Review'),
            ('paid', 'Paid'),
            ('overdue', 'Overdue')
        ],
        default='pending_payment'
    )
    
    # RTGS/NEFT transaction verification
    bank_receipt = models.FileField(upload_to='billing_receipts/', blank=True, null=True)
    utr_number = models.CharField(max_length=100, blank=True, null=True, help_text="Transaction Ref ID (UTR/NEFT)")
    
    uploaded_at = models.DateTimeField(null=True, blank=True)
    marked_paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Invoice"
        verbose_name_plural = "Invoices"

    def __str__(self):
        return f"{self.invoice_number} ({self.tenant.name}) - {self.status}"


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

from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Tenant(TenantMixin):
    """
    Each tenant represents a college.
    The schema_name field is inherited from TenantMixin.
    """
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=20, unique=True, null=True, blank=True)
    address = models.TextField(blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    permitted_email_domain = models.CharField(max_length=100, blank=True, null=True, help_text="e.g. mit.edu.in. If set, students must register with this domain.")
    created_on = models.DateField(auto_now_add=True)
    is_active = models.BooleanField(default=True)

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

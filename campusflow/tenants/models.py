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

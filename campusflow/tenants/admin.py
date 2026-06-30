from django.contrib import admin
from django_tenants.admin import TenantAdminMixin
from .models import Tenant, Domain


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ('name', 'code', 'schema_name', 'contact_email', 'is_active', 'created_on')
    search_fields = ('name', 'code', 'schema_name')
    list_filter = ('is_active',)
    fields = (
        'schema_name', 'name', 'code', 'address', 'contact_email',
        'permitted_email_domain', 'is_active', 'timezone',
        'email_smtp_host', 'email_smtp_port', 'email_smtp_username', 'email_smtp_password',
        'erp_system_name', 'erp_api_url', 'erp_auth_token',
        'billing_student_rate', 'billing_student_discount', 'billing_employee_rate', 'billing_employee_discount',
        'subscribed_modules'
    )



@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ('domain', 'tenant', 'is_primary')
    search_fields = ('domain',)
    list_filter = ('is_primary',)

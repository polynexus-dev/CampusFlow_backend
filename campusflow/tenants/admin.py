from django import forms
from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html
from django_tenants.admin import TenantAdminMixin
from .models import Tenant, Domain

ALL_MODULE_CHOICES = [
    ("management", "Management Portal"),
    ("administrator", "Administrator Console"),
    ("department", "Department Admin"),
    ("room", "Room Manager"),
    ("staff", "Staff Directory"),
    ("student", "Student Console"),
    ("attendance", "Attendance Tracker"),
    ("schedule", "Time Table / Schedule"),
    ("leave", "Leave Management"),
    ("payroll", "Payroll / Salary"),
    ("exams", "Examinations Control"),
    ("analytics", "Analytics & Reports"),
    ("announcements", "Announcements & Broadcasts"),
    ("audit-logs", "System Audit Logs"),
    ("assignments", "Assignments Upload"),
    ("fees", "Fee Collection"),
    ("bus-tracking", "Real-Time Bus Tracking"),
    ("hostel", "Hostel Allocations"),
    ("tpo", "Training & Placements (TPO)"),
    ("library", "Library Management"),
    ("inventory", "Inventory & Store"),
    ("valuation", "Digital Valuation Cockpit"),
]


class TenantAdminForm(forms.ModelForm):
    subscribed_modules = forms.MultipleChoiceField(
        choices=ALL_MODULE_CHOICES,
        widget=forms.CheckboxSelectMultiple(attrs={'style': 'display: inline-block; width: auto; margin-right: 15px; margin-bottom: 5px;'}),
        required=False,
        help_text="Check the modules that this college has access to."
    )

    class Meta:
        model = Tenant
        fields = '__all__'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['subscribed_modules'] = self.instance.subscribed_modules or []

    def clean_subscribed_modules(self):
        return self.cleaned_data.get('subscribed_modules', [])


@admin.register(Tenant)
class TenantAdmin(TenantAdminMixin, admin.ModelAdmin):
    form = TenantAdminForm
    list_display = (
        'name', 'code', 'schema_name', 'contact_email',
        'is_active', 'created_on', 'legal_agreement_link',
    )
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

    @admin.display(description="Legal Agreement")
    def legal_agreement_link(self, obj):
        if not obj or not obj.pk or obj.schema_name == 'public':
            return "—"
        url = f"{reverse('college-legal-agreement', args=[obj.pk])}?raw=1"
        return format_html(
            '<a class="button" href="{}" target="_blank" rel="noopener noreferrer">'
            'Generate Contract &nearr;</a>',
            url,
        )


@admin.register(Domain)
class DomainAdmin(admin.ModelAdmin):
    list_display = ('domain', 'tenant', 'is_primary')
    search_fields = ('domain',)
    list_filter = ('is_primary',)


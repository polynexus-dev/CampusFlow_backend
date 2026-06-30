from rest_framework import serializers
from .models import Tenant, Domain
from django.utils.text import slugify
from django.contrib.auth.models import User, Group
from django_tenants.utils import schema_context
from campusflow_app.models.profile import ManagementProfile
import uuid

class TenantCreateSerializer(serializers.ModelSerializer):
    domain_name = serializers.CharField(write_only=True, help_text="The full domain for this college, e.g. 'mit.localhost'")
    admin_username = serializers.CharField(write_only=True)
    admin_email = serializers.EmailField(write_only=True)
    admin_password = serializers.CharField(write_only=True, style={'input_type': 'password'})

    class Meta:
        model = Tenant
        fields = [
            'name', 'code', 'address', 'contact_email', 'permitted_email_domain', 'domain_name',
            'admin_username', 'admin_email', 'admin_password', 'timezone',
            'email_smtp_host', 'email_smtp_port', 'email_smtp_username', 'email_smtp_password',
            'erp_system_name', 'erp_api_url', 'erp_auth_token'
        ]

    def create(self, validated_data):
        domain_name = validated_data.pop('domain_name')
        admin_username = validated_data.pop('admin_username')
        admin_email = validated_data.pop('admin_email')
        admin_password = validated_data.pop('admin_password')
        name = validated_data['name']
        
        # 1. Automatically calculate schema name
        base_schema = slugify(name).replace('-', '_')
        schema_name = base_schema
        counter = 1
        while Tenant.objects.filter(schema_name=schema_name).exists():
            schema_name = f"{base_schema}_{counter}"
            counter += 1
            
        # 2. Create Tenant & Domain
        tenant = Tenant.objects.create(schema_name=schema_name, **validated_data)
        Domain.objects.create(domain=domain_name, tenant=tenant, is_primary=True)
        
        # 3. Provision the new Tenant (Switch to the new schema context)
        with schema_context(tenant.schema_name):
            # A. Create necessary Role Groups
            roles = ['student', 'Faculty', 'Support Staff', 'Management', 'Administrator', 'Department Head']
            for role_name in roles:
                Group.objects.get_or_create(name=role_name)
            
            # B. Create the initial College Admin User
            admin_user = User.objects.create_user(
                username=admin_username,
                email=admin_email,
                password=admin_password,
                is_staff=True # Allow them to access the Django admin for this tenant
            )
            
            # C. Assign Admin to 'Management' group
            management_group = Group.objects.get(name='Management')
            admin_user.groups.add(management_group)
            
            # D. Create Management Profile for the admin
            ManagementProfile.objects.create(
                user=admin_user,
                employee_id=f"ADMIN-{uuid.uuid4().hex[:6].upper()}",
                designation="College Administrator",
                status="active"
            )
            
        return tenant


class TenantListSerializer(serializers.ModelSerializer):
    domain_name = serializers.SerializerMethodField()
    student_count = serializers.SerializerMethodField()
    faculty_count = serializers.SerializerMethodField()
    management_count = serializers.SerializerMethodField()
    support_staff_count = serializers.SerializerMethodField()
    hod_count = serializers.SerializerMethodField()

    class Meta:
        model = Tenant
        fields = [
            'id', 'name', 'code', 'address', 'contact_email', 'permitted_email_domain', 'domain_name',
            'created_on', 'is_active', 'timezone',
            'email_smtp_host', 'email_smtp_port', 'email_smtp_username', 'email_smtp_password',
            'erp_system_name', 'erp_api_url', 'erp_auth_token',
            'student_count', 'faculty_count', 'management_count', 'support_staff_count', 'hod_count',
            'billing_student_rate', 'billing_student_discount', 'billing_employee_rate', 'billing_employee_discount',
            'subscribed_modules'
        ]

    def get_domain_name(self, obj):
        try:
            return obj.get_primary_domain().domain
        except Exception:
            return None

    def get_student_count(self, obj):
        if obj.schema_name == 'public':
            return 0
        from campusflow_app.models.profile import StudentProfile
        with schema_context(obj.schema_name):
            try:
                return StudentProfile.objects.count()
            except Exception:
                return 0

    def get_faculty_count(self, obj):
        if obj.schema_name == 'public':
            return 0
        from campusflow_app.models.profile import TeachingStaffProfile
        with schema_context(obj.schema_name):
            try:
                return TeachingStaffProfile.objects.count()
            except Exception:
                return 0

    def get_management_count(self, obj):
        if obj.schema_name == 'public':
            return 0
        from campusflow_app.models.profile import ManagementProfile
        with schema_context(obj.schema_name):
            try:
                return ManagementProfile.objects.count()
            except Exception:
                return 0

    def get_support_staff_count(self, obj):
        if obj.schema_name == 'public':
            return 0
        from campusflow_app.models.profile import NonTeachingStaffProfile
        with schema_context(obj.schema_name):
            try:
                return NonTeachingStaffProfile.objects.count()
            except Exception:
                return 0

    def get_hod_count(self, obj):
        if obj.schema_name == 'public':
            return 0
        from campusflow_app.models.profile import DepartmentHeadProfile
        with schema_context(obj.schema_name):
            try:
                return DepartmentHeadProfile.objects.count()
            except Exception:
                return 0


class TenantUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tenant
        fields = [
            'name', 'address', 'contact_email', 'permitted_email_domain', 'is_active', 'timezone',
            'email_smtp_host', 'email_smtp_port', 'email_smtp_username', 'email_smtp_password',
            'erp_system_name', 'erp_api_url', 'erp_auth_token',
            'billing_student_rate', 'billing_student_discount', 'billing_employee_rate', 'billing_employee_discount',
            'subscribed_modules'
        ]

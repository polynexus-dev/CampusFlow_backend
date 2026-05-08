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
        fields = ['name', 'code', 'address', 'contact_email', 'permitted_email_domain', 'domain_name', 'admin_username', 'admin_email', 'admin_password']

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

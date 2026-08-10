# ── Standard Library Imports ──────────────────────────────────────────────────
import datetime
import uuid

# ── Django Core Imports ──────────────────────────────────────────────────────
from django.contrib.auth.models import Group, Permission, User
from django.db import connection, transaction
from django.db.models import Q
from django.http import HttpRequest
from django.utils.translation import gettext_lazy as _

# ── Third-Party Framework Imports ─────────────────────────────────────────────
from ipware import get_client_ip
from rest_framework import serializers
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from user_agents import parse

# ── Local App-Specific Imports ────────────────────────────────────────────────
from .models.attendance import Attendance
from .models.attendance_log import FaceAttendanceLog
from .models.classroom import Classroom
from .models.department import Department
from .models.hostel import Hostel, HostelAllocation, HostelRoom
from .models.inventory import (
    InventoryCategory,
    InventoryItem,
    InventoryTransaction,
    Supplier,
)
from .models.lecture import Lecture
from .models.library import Book, BookCopy, BookIssue
from .models.location import Location
from .models.profile import (
    AdministratorProfile,
    DepartmentHeadProfile,
    ManagementProfile,
    NonTeachingStaffProfile,
    StudentProfile,
    TeachingStaffProfile,
    GuardianProfile,
)
from .models.schedule import Schedule
from .models.tpo import PlacementApplication, RecruitmentDrive
from .models.valuation import ScannedPaper, ValuationSession
from .models.ai_grading import AIGradingSuggestion
from .models.result import StudentExamResult
from .models.bus_tracking import BusRoute
from .models.compliance import (
    ComplianceCertificateType, ComplianceCertificate,
    AccreditationCriterion, EvidenceItem,
)
from .models.finance import (
    FinancialYear, IncomeCategory, IncomeEntry, ExpenseCategory, ExpenseEntry, FixedAsset,
)
from .models.audit_portal import AuditorProfile, AuditEngagement, AuditorAccessLog
from .models.scholarship import StateScholarshipScheme, StudentScholarshipRecord
from .demo_guard import is_demo_tenant





class ClassroomSerializer(serializers.ModelSerializer):
    class Meta:
        model = Classroom
        fields = ('id', 'name', 'code', 'main_entry_location',)
        read_only_fields = ('id',)

class LectureSerializer(serializers.ModelSerializer):
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)
    faculty_username = serializers.CharField(source='faculty.username', read_only=True)
    teacher_name = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = Lecture
        fields = ('id', 'name', 'subject', 'faculty', 'faculty_username', 'teacher_name', 'classroom', 'classroom_name', 'start_time', 'end_time', 'code', 'created_at')
        read_only_fields = ('id', 'code', 'created_at')
        extra_kwargs = {
            'classroom': {'required': True, 'allow_null': False}
        }

    def get_teacher_name(self, obj):
        if obj.faculty:
            return obj.faculty.get_full_name() or obj.faculty.username
        return None


class LectureAttendanceCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=20)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)


class AttendanceMarkSerializer(serializers.Serializer):
    student_id = serializers.IntegerField()
    location_id = serializers.CharField()
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    lecture_id = serializers.IntegerField(required=False)

class LocationValidationSerializer(serializers.Serializer):
    classroom_id = serializers.IntegerField()
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6)

class MyTokenObtainPairSerializer(TokenObtainPairSerializer):
    @classmethod
    def get_token(cls, user):
        token = super().get_token(user)
        # Add the schema name to the token payload so it can be verified later
        # This prevents a token from one college being used in another college.
        token['tenant_schema'] = connection.schema_name
        return token

    def validate(self, attrs):
        request = self.context.get('request')
        username = attrs.get('username')
        password = attrs.get('password')

        # --- BLOCK LOGIN FROM A TENANT SUBDOMAIN ---
        # Login must always happen via the base/public URL (the frontend doesn't
        # know which college a user belongs to ahead of time). If this request
        # was routed here via a tenant subdomain (CampusFlowTenantMiddleware
        # already resolved connection.schema_name to that tenant), reject it
        # and tell the frontend where the base portal actually lives.
        if connection.schema_name != 'public':
            from urllib.parse import urlparse
            origin = request.headers.get('Origin') or request.headers.get('Referer', '')
            frontend_host = urlparse(origin).hostname or request.get_host().split(':')[0]
            parts = frontend_host.split('.')
            base_domain = '.'.join(parts[1:]) if len(parts) > 1 else frontend_host
            raise serializers.ValidationError(
                {
                    'error': "Please login from the main portal, not your college's page.",
                    'redirect_domain': base_domain,
                },
                code='wrong_login_domain',
            )

        # --- Device Info Extraction ---
        client_ip, is_routable = get_client_ip(request)
        user_agent_string = request.headers.get('User-Agent', '')
        user_agent = parse(user_agent_string)
        os_name = user_agent.os.family
        os_version = user_agent.os.version_string
        browser_name = user_agent.browser.family
        browser_version = user_agent.browser.version_string
        device_type = "Unknown Device"
        if user_agent.is_mobile:
            device_type = "Mobile Phone"
        elif user_agent.is_tablet:
            device_type = "Tablet"
        elif user_agent.is_pc:
            device_type = "Desktop/PC"
        elif user_agent.is_bot:
            device_type = "Bot/Crawler"
        device_brand = user_agent.device.brand
        device_model = user_agent.device.model
        device_description = f"{browser_name} on {os_name}"
        if os_version:
            device_description += f" {os_version}"
        if device_brand and device_model:
            device_description += f" ({device_brand} {device_model})"
        else:
            device_description += f" ({device_type})"
        self.device_info = {
            "client_ip": client_ip, "os_name": os_name, "os_version": os_version,
            "browser_name": browser_name, "browser_version": browser_version,
            "device_type": device_type, "device_brand": device_brand,
            "device_model": device_model, "device_description": device_description,
        }

        if not password or " " in password:
            raise serializers.ValidationError("Password cannot contain spaces.", code='invalid_password')

        from tenants.models import Tenant

        user = None
        target_tenant = None

        # First try to find user in current schema (search by username or email)
        user = User.objects.filter(Q(username=username) | Q(email=username)).first()
        if user:
            target_tenant = Tenant.objects.filter(schema_name=connection.schema_name).first()
        elif connection.schema_name == 'public':
            # Search all other tenant schemas
            from django_tenants.utils import schema_context
            for tenant in Tenant.objects.exclude(schema_name='public'):
                with schema_context(tenant.schema_name):
                    u = User.objects.filter(Q(username=username) | Q(email=username)).first()
                    if u:
                        user = u
                        target_tenant = tenant
                        break

        if not user:
            raise serializers.ValidationError(f"{username} does not exist", code='not_found')

        # Switch context to the target tenant's schema for the rest of this request
        if target_tenant and target_tenant.schema_name != connection.schema_name:
            connection.set_tenant(target_tenant)
            # Re-fetch user in the active tenant connection context
            user = User.objects.get(id=user.id)

        profile_data = None
        user_group = None

        # Only enforce group and profile checks for non-superusers
        if not user.is_superuser:
            if not user.groups.exists():
                raise serializers.ValidationError(f"User '{username}' does not have a group assigned.", code='no_group_assigned')
    
            user_group = user.groups.first()
    
            if user_group.name == 'student':
                profile_data = StudentProfile.objects.filter(user=user).first()
            elif user_group.name == 'Faculty':
                profile_data = TeachingStaffProfile.objects.filter(user=user).first()
            elif user_group.name == 'Support Staff':
                profile_data = NonTeachingStaffProfile.objects.filter(user=user).first()
            elif user_group.name == 'Management':
                profile_data = ManagementProfile.objects.filter(user=user).first()
            elif user_group.name == 'Administrator':
                profile_data = AdministratorProfile.objects.filter(user=user).first()
            elif user_group.name == 'Department Head':
                profile_data = DepartmentHeadProfile.objects.filter(user=user).first()
            elif user_group.name == 'guardian':
                profile_data = GuardianProfile.objects.filter(user=user).first()
            elif user_group.name == 'CA':
                profile_data = AuditorProfile.objects.filter(user=user).first()

            if not profile_data:
                raise serializers.ValidationError(
                    f"User '{username}' with role '{user_group.name}' does not have an associated profile.",
                    code='no_profile_found'
                )
            
            # --- STATUS CHECK: Block Pending/Rejected Users ---
            if profile_data.status == 'pending':
                raise serializers.ValidationError(
                    "Your account is pending approval by an administrator or HOD.",
                    code='account_pending'
                )
            elif profile_data.status == 'rejected':
                raise serializers.ValidationError(
                    "Your account registration has been rejected. Please contact administration.",
                    code='account_rejected'
                )
            elif profile_data.status != 'active':
                raise serializers.ValidationError(
                    f"Your account status is '{profile_data.status}'. Please contact administration.",
                    code='account_inactive'
                )

        if not user.check_password(password):
            raise serializers.ValidationError("Invalid Credentials", code='INVALID_CREDENTIALS')

        attrs['username'] = user.username
        data = super().validate(attrs)

        data['user_id'] = user.id
        data['user'] = user.username
        data['roleName'] = user_group.name if user_group else "Superuser"
        if target_tenant and target_tenant.schema_name != 'public':
            try:
                schema = target_tenant.schema_name

                # Use the Origin (or Referer) header to get the FRONTEND domain.
                # request.get_host() returns the BACKEND host — we need the frontend host
                # so the redirect URL points to the correct frontend subdomain.
                #
                # Dev:        Origin = "http://localhost:5173"         → "mit.localhost"
                # Production: Origin = "https://campusnexus.in" → "mit.campusnexus.in"
                from urllib.parse import urlparse
                origin = request.headers.get('Origin') or request.headers.get('Referer', '')
                parsed_origin = urlparse(origin)
                frontend_host = parsed_origin.hostname  # strips port automatically

                # Fallback: strip known backend prefix from request host
                if not frontend_host:
                    frontend_host = request.get_host().split(':')[0]

                if frontend_host in ('localhost', '127.0.0.1'):
                    computed_domain = f"{schema}.localhost"
                else:
                    computed_domain = f"{schema}.{frontend_host}"

                data['tenant_domain'] = computed_domain
                data['tenant_code'] = target_tenant.code
                data['tenant_schema'] = schema  # Used by mobile app for X-Tenant header
            except Exception:
                data['tenant_domain'] = None
                data['tenant_code'] = None
                data['tenant_schema'] = target_tenant.schema_name if target_tenant else None
        elif target_tenant:
            # Public schema / superuser: no cross-domain redirect needed.
            # They are already on the correct host.
            data['tenant_domain'] = None
            data['tenant_code'] = target_tenant.code
            data['tenant_schema'] = target_tenant.schema_name

        # --- SECURITY: AUTO-DEVICE BINDING ---
        if user_group and user_group.name == 'student':
            device_id = request.data.get('device_id')
            if device_id:
                profile = user.student_profile
                if not profile.locked_device_id:
                    profile.locked_device_id = device_id  # Bind for the first time
                    profile.save()
                elif profile.locked_device_id != device_id:
                    # Optional: We could block login here, but usually we just block attendance.
                    # For now, let's just add it to the response data for the frontend to handle.
                    data['device_mismatch'] = True

        data['first_name'] = self.user.first_name
        data['last_name'] = self.user.last_name
        data['email'] = self.user.email
        data['date_joined'] = self.user.date_joined
        data['date'] = datetime.date.today()

        # Add tenant info from the current schema
        tenant = getattr(connection, 'tenant', None)
        if tenant:
            data['tenant'] = {
                'name': getattr(tenant, 'name', None) or getattr(tenant, 'schema_name', 'Public'),
                'schema': getattr(tenant, 'schema_name', 'public'),
                'code': getattr(tenant, 'code', None),
                'logo': request.build_absolute_uri(tenant.logo.url) if getattr(tenant, 'logo', None) else None,
                'tenant_type': getattr(tenant, 'tenant_type', 'college'),
            }

        if profile_data:
            data['profile'] = {
                'id': profile_data.id,
                'department_id': profile_data.department.id if hasattr(profile_data, 'department') and profile_data.department else None,
            }
            if user_group.name == 'student':
                data['profile']['student_id'] = profile_data.student_id
                data['profile']['program_enrolled_in'] = profile_data.program_enrolled_in if hasattr(profile_data, 'program_enrolled_in') else None
                data['profile']['is_face_registered'] = getattr(profile_data, 'is_face_registered', False)
                data['profile']['locked_device_id'] = getattr(profile_data, 'locked_device_id', None)
            elif user_group.name in ['Faculty', 'Support Staff', 'Management', 'Administrator', 'Department Head']:
                data['profile']['employee_id'] = profile_data.employee_id
            elif user_group.name == 'guardian':
                data['profile']['guardian_id'] = profile_data.guardian_id
                data['profile']['contact_number'] = profile_data.contact_number

        # --- BUS DRIVER / CONDUCTOR ADDITIONAL CHARGE ---
        # Support Staff (and any other employee) can be handed the extra charge of
        # driving/conducting a bus route without changing their base role/group.
        # Surface it on login so the mobile app can gate the Conductor Panel on the
        # actual BusRoute assignment instead of guessing from the role name alone.
        if user_group and user_group.name != 'student':
            assigned_route = BusRoute.objects.filter(
                Q(driver=user) | Q(conductor=user), is_active=True
            ).first()
            data['is_bus_driver'] = bool(assigned_route and assigned_route.driver_id == user.id)
            data['is_bus_conductor'] = bool(assigned_route and assigned_route.conductor_id == user.id)
            data['bus_route_id'] = assigned_route.id if assigned_route else None

        data['device_info'] = self.device_info
        data['consent_given'] = getattr(profile_data, 'consent_given', True)
        return data
 

class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()
    default_error_messages = {'bad_token': ('Token is expired or invalid')}

    def validate(self, attrs):
        self.token = attrs['refresh']
        return attrs

    def save(self):
        try:
            token = RefreshToken(self.token)
            try:
                token.blacklist()
            except AttributeError:
                raise ValidationError("Token blacklisting is not enabled.")
        except TokenError:
            raise ValidationError(self.error_messages['bad_token'])

def assign_role_permissions(user, role_group_name):
    """Assigns user to a specific role group and sets permissions."""
    try:
        group = Group.objects.get(name=role_group_name)
    except Group.DoesNotExist:
        raise ValueError(f"Group '{role_group_name}' does not exist. Please create it first.")
    user.groups.clear()
    user.groups.add(group)
    group_permissions_codenames = group.permissions.values_list('codename', flat=True)
    user.user_permissions.set(Permission.objects.filter(codename__in=group_permissions_codenames))
    user.save()

class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    password2 = serializers.CharField(write_only=True, required=True, style={'input_type': 'password'})
    role = serializers.CharField(required=True)
    department_id = serializers.PrimaryKeyRelatedField(queryset=Department.objects.all(), write_only=True, required=False, allow_null=True)
    program_enrolled_in_id = serializers.CharField(write_only=True, required=False, allow_null=True)
    student_id = serializers.CharField(required=False, allow_blank=True, max_length=20)
    employee_id = serializers.CharField(required=False, allow_blank=True, max_length=20)
    middle_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    contact_number = serializers.CharField(max_length=15, required=False, allow_blank=True)
    date_of_birth = serializers.DateField(required=False, allow_null=True)
    gender = serializers.CharField(max_length=10, required=False, allow_blank=True)
    blood_group = serializers.CharField(max_length=5, required=False, allow_blank=True)
    aadhaar_number = serializers.CharField(max_length=12, required=False, allow_blank=True)
    nationality = serializers.CharField(max_length=100, required=False, allow_blank=True)
    emergency_contact_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    emergency_contact_relationship = serializers.CharField(max_length=50, required=False, allow_blank=True)
    emergency_contact_phone = serializers.CharField(max_length=15, required=False, allow_blank=True)
    alternate_phone_number = serializers.CharField(max_length=15, required=False, allow_blank=True)
    current_address_line1 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    current_address_line2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    current_city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    current_district = serializers.CharField(max_length=100, required=False, allow_blank=True)
    current_state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    current_pincode = serializers.CharField(max_length=10, required=False, allow_blank=True)
    permanent_address_line1 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    permanent_address_line2 = serializers.CharField(max_length=255, required=False, allow_blank=True)
    permanent_city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    permanent_district = serializers.CharField(max_length=100, required=False, allow_blank=True)
    permanent_state = serializers.CharField(max_length=100, required=False, allow_blank=True)
    permanent_pincode = serializers.CharField(max_length=10, required=False, allow_blank=True)
    profile_picture = serializers.ImageField(required=False, allow_null=True)
    religion = serializers.CharField(max_length=100, required=False, allow_blank=True)
    category = serializers.CharField(max_length=50, required=False, allow_blank=True)
    disability_status = serializers.BooleanField(required=False, allow_null=True)
    disability_details = serializers.CharField(max_length=500, required=False, allow_blank=True)
    admission_date = serializers.DateField(required=False, allow_null=True)
    admission_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    batch_academic_year = serializers.CharField(max_length=50, required=False, allow_blank=True)
    current_semester_year = serializers.CharField(max_length=50, required=False, allow_blank=True)
    section_division = serializers.CharField(max_length=10, required=False, allow_blank=True)
    previous_school_college = serializers.CharField(max_length=255, required=False, allow_blank=True)
    tenth_marksheet_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    twelfth_marksheet_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, allow_null=True)
    biometric_id = serializers.CharField(max_length=255, required=False, allow_blank=True)
    hostel_transport_details = serializers.CharField(max_length=500, required=False, allow_blank=True)
    scholarship_fee_concession_details = serializers.CharField(max_length=500, required=False, allow_blank=True)
    medical_conditions_allergies = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    extracurricular_interests = serializers.CharField(max_length=1000, required=False, allow_blank=True)
    date_of_joining = serializers.DateField(required=False, allow_null=True)
    designation = serializers.CharField(max_length=100, required=False, allow_blank=True)
    employee_type = serializers.CharField(max_length=20, required=False, allow_blank=True)
    bank_account_number = serializers.CharField(max_length=50, required=False, allow_blank=True)
    pan_number = serializers.CharField(max_length=10, required=False, allow_blank=True)
    staff_role = serializers.CharField(max_length=50, required=False, allow_blank=True)
    status = serializers.CharField(max_length=20, required=False, allow_blank=True)
    qualifications = serializers.CharField(required=False, allow_blank=True)
    specializations = serializers.CharField(required=False, allow_blank=True)
    experience_years = serializers.IntegerField(required=False, allow_null=True)
    epf_esi_details = serializers.CharField(required=False, allow_blank=True)
    office_room_number = serializers.CharField(max_length=20, required=False, allow_blank=True)
    research_interests = serializers.CharField(required=False, allow_blank=True)
    publications_link = serializers.URLField(max_length=500, required=False, allow_blank=True)
    replacement_availability_preferences = serializers.CharField(required=False, allow_blank=True)
    assigned_responsibilities = serializers.CharField(required=False, allow_blank=True)
    office_location_details = serializers.CharField(max_length=255, required=False, allow_blank=True)
    
    # DPDP Compliance fields
    consent_given = serializers.BooleanField(required=False, default=True)
    consent_version = serializers.CharField(max_length=10, required=False, allow_blank=True, default='v1.0')
    parent_guardian_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    parent_guardian_email = serializers.EmailField(required=False, allow_null=True)

    class Meta:
        model = User
        fields = [
            'username', 'email', 'password', 'password2', 'first_name', 'last_name', 'role',
            'department_id', 'student_id', 'employee_id', 'program_enrolled_in_id',
            'middle_name', 'contact_number', 'date_of_birth', 'gender', 'blood_group',
            'aadhaar_number', 'nationality', 'emergency_contact_name',
            'emergency_contact_relationship', 'emergency_contact_phone', 'alternate_phone_number',
            'current_address_line1', 'current_address_line2', 'current_city',
            'current_district', 'current_state', 'current_pincode',
            'permanent_address_line1', 'permanent_address_line2', 'permanent_city',
            'permanent_district', 'permanent_state', 'permanent_pincode', 'profile_picture',
            'religion', 'category', 'disability_status', 'disability_details',
            'admission_date', 'admission_number', 'batch_academic_year', 'current_semester_year',
            'section_division', 'previous_school_college', 'tenth_marksheet_percentage',
            'twelfth_marksheet_percentage', 'biometric_id', 'hostel_transport_details',
            'scholarship_fee_concession_details', 'medical_conditions_allergies',
            'extracurricular_interests', 'date_of_joining', 'designation', 'employee_type',
            'bank_account_number', 'pan_number', 'staff_role', 'status',
            'qualifications', 'specializations', 'experience_years', 'epf_esi_details',
            'office_room_number', 'research_interests', 'publications_link',
            'replacement_availability_preferences', 'assigned_responsibilities',
            'office_location_details', 'consent_given', 'consent_version',
            'parent_guardian_name', 'parent_guardian_email',
        ]
        extra_kwargs = {
            'first_name': {'required': False},
            'last_name': {'required': False},
            'email': {'required': True},
        }

    def validate(self, data):
        if data['password'] != data['password2']:
            raise serializers.ValidationError({"password": "Password fields didn't match."})
        role = data.get('role')
        student_id = data.get('student_id')
        employee_id = data.get('employee_id')
        valid_roles = ['student', 'Faculty', 'Support Staff', 'Management', 'Administrator', 'Department Head', 'guardian']
        if role not in valid_roles:
            raise serializers.ValidationError({"role": f"Invalid role. Must be one of: {', '.join(valid_roles)}."})
        
        # --- DPDP CONSENT VALIDATION ---
        if not data.get('consent_given', False):
            raise serializers.ValidationError({"consent_given": "You must accept the privacy notice to register."})

        if role == 'student':
            if not student_id:
                raise serializers.ValidationError({"student_id": "Student ID is required for students."})
            if StudentProfile.objects.filter(student_id=student_id).exists():
                raise serializers.ValidationError({"student_id": "A student with this ID already exists."})
            if employee_id:
                raise serializers.ValidationError({"employee_id": "Employee ID should not be provided for students."})
            if not data.get('program_enrolled_in_id'):
                raise serializers.ValidationError({"program_enrolled_in_id": "Program enrolled in is required for students."})
            
            # --- DPDP MINOR CHECK ---
            dob = data.get('date_of_birth')
            if not dob:
                raise serializers.ValidationError({"date_of_birth": "Date of birth is required for students to determine age group."})
            today = datetime.date.today()
            age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            if age < 18:
                if not data.get('parent_guardian_name') or not data.get('parent_guardian_email'):
                    raise serializers.ValidationError({
                        "parent_guardian_name": "Parent or guardian details (name and email) are required for students under 18 years of age."
                    })
        elif role in ['Faculty', 'Support Staff', 'Management', 'Administrator', 'Department Head']:
            if not employee_id:
                raise serializers.ValidationError({"employee_id": "Employee ID is required for staff/admin/HOD members."})
            if (TeachingStaffProfile.objects.filter(employee_id=employee_id).exists() or
                NonTeachingStaffProfile.objects.filter(employee_id=employee_id).exists() or
                ManagementProfile.objects.filter(employee_id=employee_id).exists() or
                AdministratorProfile.objects.filter(employee_id=employee_id).exists() or
                DepartmentHeadProfile.objects.filter(employee_id=employee_id).exists()):
                raise serializers.ValidationError({"employee_id": "An employee with this ID already exists."})
            if student_id:
                raise serializers.ValidationError({"student_id": "Student ID should not be provided for staff."})
        
        # Department validation for specific roles
        department = data.get('department_id')
        roles_requiring_dept = ['student', 'Faculty', 'Department Head']
        if role in roles_requiring_dept and not department:
            raise serializers.ValidationError({"department_id": "A department must be assigned for this role."})

        if User.objects.filter(email=data['email']).exists():
            raise serializers.ValidationError({"email": "A user with this email already exists."})
        return data

    @transaction.atomic
    def create(self, validated_data):
        password = validated_data.pop('password')
        validated_data.pop('password2')
        role = validated_data.pop('role')
        profile_data = {}
        profile_field_names = [
            'department_id', 'student_id', 'employee_id', 'program_enrolled_in_id',
            'middle_name', 'contact_number', 'date_of_birth', 'gender', 'blood_group',
            'aadhaar_number', 'nationality', 'emergency_contact_name',
            'emergency_contact_relationship', 'emergency_contact_phone', 'alternate_phone_number',
            'current_address_line1', 'current_address_line2', 'current_city',
            'current_district', 'current_state', 'current_pincode',
            'permanent_address_line1', 'permanent_address_line2', 'permanent_city',
            'permanent_district', 'permanent_state', 'permanent_pincode', 'profile_picture',
            'religion', 'category', 'disability_status', 'disability_details',
            'admission_date', 'admission_number', 'batch_academic_year', 'current_semester_year',
            'section_division', 'previous_school_college', 'tenth_marksheet_percentage',
            'twelfth_marksheet_percentage', 'biometric_id', 'hostel_transport_details',
            'scholarship_fee_concession_details', 'medical_conditions_allergies',
            'extracurricular_interests', 'date_of_joining', 'designation', 'employee_type',
            'bank_account_number', 'pan_number', 'staff_role', 'status',
            'qualifications', 'specializations', 'experience_years', 'epf_esi_details',
            'office_room_number', 'research_interests', 'publications_link',
            'replacement_availability_preferences', 'assigned_responsibilities',
            'office_location_details', 'consent_given', 'consent_version',
            'parent_guardian_name', 'parent_guardian_email',
        ]
        for field_name in profile_field_names:
            if field_name in validated_data:
                if field_name == 'department_id':
                    profile_data['department'] = validated_data.pop(field_name)
                elif field_name == 'program_enrolled_in_id':
                    profile_data['program_enrolled_in'] = validated_data.pop(field_name)
                else:
                    profile_data[field_name] = validated_data.pop(field_name)

        # Set consent timestamp if consent was given
        if profile_data.get('consent_given'):
            from django.utils import timezone
            profile_data['consent_timestamp'] = timezone.now()

        # Handle student status and parental consent checks
        if role == 'student':
            dob = profile_data.get('date_of_birth')
            if dob:
                today = datetime.date.today()
                age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
                if age < 18:
                    profile_data['status'] = 'pending_guardian'
                    profile_data['guardian_consent_given'] = False

        is_demo = is_demo_tenant() or connection.schema_name == 'demo'

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=password,
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            is_active=True if is_demo else False,  # Auto-activate for demo tenant, else OTP required
        )

        if role == 'student':
            fields = {k: v for k, v in profile_data.items() if hasattr(StudentProfile, k)}
            StudentProfile.objects.create(user=user, **fields)
            assign_role_permissions(user, 'student')
        elif role == 'Faculty':
            fields = {k: v for k, v in profile_data.items() if hasattr(TeachingStaffProfile, k)}
            if 'staff_role' not in fields or not fields['staff_role']:
                fields['staff_role'] = 'lecturer'
            fields['status'] = 'pending'  # Faculty needs HOD approval
            TeachingStaffProfile.objects.create(user=user, **fields)
            assign_role_permissions(user, 'Faculty')
        elif role == 'Support Staff':
            fields = {k: v for k, v in profile_data.items() if hasattr(NonTeachingStaffProfile, k)}
            if 'staff_role' not in fields or not fields['staff_role']:
                fields['staff_role'] = 'administrator'
            fields['status'] = 'pending'  # Support needs Admin/HOD approval
            NonTeachingStaffProfile.objects.create(user=user, **fields)
            assign_role_permissions(user, 'Support Staff')
        elif role == 'Management':
            fields = {k: v for k, v in profile_data.items() if hasattr(ManagementProfile, k)}
            if 'staff_role' not in fields or not fields['staff_role']:
                fields['staff_role'] = 'director'
            fields['status'] = 'active'
            ManagementProfile.objects.create(user=user, **fields)
            assign_role_permissions(user, 'Management')
        elif role == 'Administrator':
            fields = {k: v for k, v in profile_data.items() if hasattr(AdministratorProfile, k)}
            fields['status'] = 'active'
            AdministratorProfile.objects.create(user=user, **fields)
            assign_role_permissions(user, 'Administrator')
        elif role == 'Department Head':
            fields = {k: v for k, v in profile_data.items() if hasattr(DepartmentHeadProfile, k)}
            fields['status'] = 'pending'
            DepartmentHeadProfile.objects.create(user=user, **fields)
            assign_role_permissions(user, 'Department Head')
        elif role == 'guardian':
            fields = {k: v for k, v in profile_data.items() if hasattr(GuardianProfile, k)}
            fields['guardian_id'] = f"GUA-{uuid.uuid4().hex[:6].upper()}"
            fields['status'] = 'active'
            GuardianProfile.objects.create(user=user, **fields)
            assign_role_permissions(user, 'guardian')
        else:
            raise serializers.ValidationError({"role": "Invalid role provided."})
        return user


class LocationSerializer(serializers.ModelSerializer):
    department_owner_name = serializers.CharField(source='department_owner.name', read_only=True)

    class Meta:
        model = Location
        fields = [
            'id', 'location_id', 'name', 'latitude', 'longitude', 'geofence_radius_meters',
            'is_premises_entry', 'department_owner', 'department_owner_name'
        ]
        read_only_fields = ['department_owner_name']

class AttendanceSerializer(serializers.ModelSerializer):
    user_username = serializers.CharField(source='user.username', read_only=True)
    user_role = serializers.SerializerMethodField()

    class Meta:
        model = Attendance
        fields = [
            'id', 'user', 'user_username', 'user_role',
            'schedule', 'lecture', 'check_in_time', 'check_out_time',
            'is_geofence_valid', 'device_id', 'verification_method'
        ]
        read_only_fields = ['id', 'user_username', 'user_role', 'check_in_time', 'is_geofence_valid']

    def get_user_role(self, obj):
        if hasattr(obj.user, 'student_profile'):
            return 'student'
        elif hasattr(obj.user, 'teaching_staff_profile'):
            return obj.user.teaching_staff_profile.staff_role
        elif hasattr(obj.user, 'non_teaching_staff_profile'):
            return obj.user.non_teaching_staff_profile.staff_role
        elif hasattr(obj.user, 'management_profile'):
            return obj.user.management_profile.staff_role
        elif obj.user.is_superuser:
            return 'admin'
        return 'unknown'


# ──────────────────────────────────────────────────────────────────────────────
# Face Attendance Serializers
# ──────────────────────────────────────────────────────────────────────────────
class FaceRegistrationSerializer(serializers.Serializer):
    """
    Accepts three face images as multipart file uploads.
    """
    front = serializers.ImageField(help_text="Front-facing photo of the student.")
    left = serializers.ImageField(help_text="Left profile photo of the student.")
    right = serializers.ImageField(help_text="Right profile photo of the student.")


class MarkAttendanceSerializer(serializers.Serializer):
    """
    Request body for the face attendance verification endpoint.
    """
    lecture_id = serializers.IntegerField(
        help_text="ID of the active lecture to mark attendance for."
    )
    photo = serializers.ImageField(
        help_text="Live selfie captured by the student."
    )
    photo_prev = serializers.ImageField(
        required=False,
        help_text="Baseline frame captured before the challenge action, used for motion liveness check.",
    )
    challenge_id = serializers.CharField(
        help_text="Single-use token from /api/liveness-challenge/.",
    )


class FaceAttendanceLogSerializer(serializers.ModelSerializer):
    """Read-only attendance log for history."""
    student_name = serializers.CharField(
        source="student.user.get_full_name", read_only=True
    )
    enrollment_number = serializers.CharField(
        source="student.student_id", read_only=True
    )
    lecture_info = serializers.SerializerMethodField()

    class Meta:
        model = FaceAttendanceLog
        fields = [
            "id",
            "student_name",
            "enrollment_number",
            "lecture",
            "lecture_info",
            "timestamp",
            "confidence_score",
            "is_verified",
            "liveness_passed",
        ]
        read_only_fields = fields

    def get_lecture_info(self, obj):
        return {
            "course_name": obj.lecture.name,
            "course_code": obj.lecture.code,
            "date": obj.lecture.start_time.strftime("%Y-%m-%d") if obj.lecture.start_time else "",
        }


class AttendanceResultSerializer(serializers.Serializer):
    """
    Response body for the face attendance verification endpoint.
    """
    success = serializers.BooleanField()
    is_verified = serializers.BooleanField()
    confidence_score = serializers.FloatField()
    liveness_passed = serializers.BooleanField()
    message = serializers.CharField()


class ScheduleSerializer(serializers.ModelSerializer):
    course_code = serializers.CharField(source='course.course_code', read_only=True)
    course_name = serializers.CharField(source='course.course_name', read_only=True)
    classroom_name = serializers.CharField(source='classroom.name', read_only=True)
    classroom_code = serializers.CharField(source='classroom.code', read_only=True)
    faculty_name = serializers.SerializerMethodField()
    faculty_username = serializers.CharField(source='faculty.username', read_only=True)

    class Meta:
        model = Schedule
        fields = [
            'id', 'course', 'course_code', 'course_name',
            'faculty', 'faculty_name', 'faculty_username',
            'classroom', 'classroom_name', 'classroom_code',
            'day_of_week', 'start_time', 'end_time',
            'semester', 'academic_year'
        ]

    def get_faculty_name(self, obj):
        return obj.faculty.get_full_name() or obj.faculty.username


# ── Hostel Management Serializers ──
class HostelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hostel
        fields = '__all__'

class HostelRoomSerializer(serializers.ModelSerializer):
    hostel_name = serializers.CharField(source='hostel.name', read_only=True)
    class Meta:
        model = HostelRoom
        fields = '__all__'

class HostelAllocationSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.user.get_full_name', read_only=True)
    student_id = serializers.CharField(source='student.student_id', read_only=True)
    hostel_name = serializers.CharField(source='room.hostel.name', read_only=True)
    room_number = serializers.CharField(source='room.room_number', read_only=True)
    class Meta:
        model = HostelAllocation
        fields = '__all__'


# ── Training & Placement (TPO) Serializers ──
class RecruitmentDriveSerializer(serializers.ModelSerializer):
    class Meta:
        model = RecruitmentDrive
        fields = '__all__'

class PlacementApplicationSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source='student.user.get_full_name', read_only=True)
    student_id = serializers.CharField(source='student.student_id', read_only=True)
    company_name = serializers.CharField(source='drive.company_name', read_only=True)
    job_title = serializers.CharField(source='drive.job_title', read_only=True)
    class Meta:
        model = PlacementApplication
        fields = '__all__'
        extra_kwargs = {
            'student': {'required': False}
        }


# ── Library Management Serializers ──
class BookSerializer(serializers.ModelSerializer):
    class Meta:
        model = Book
        fields = '__all__'

class BookCopySerializer(serializers.ModelSerializer):
    book_title = serializers.CharField(source='book.title', read_only=True)
    class Meta:
        model = BookCopy
        fields = '__all__'

class BookIssueSerializer(serializers.ModelSerializer):
    book_title = serializers.CharField(source='book_copy.book.title', read_only=True)
    barcode = serializers.CharField(source='book_copy.barcode', read_only=True)
    student_name = serializers.CharField(source='student.user.get_full_name', read_only=True)
    student_id = serializers.CharField(source='student.student_id', read_only=True)
    staff_name = serializers.CharField(source='staff_user.get_full_name', read_only=True)

    class Meta:
        model = BookIssue
        fields = '__all__'

    def validate(self, attrs):
        book_copy = attrs.get('book_copy')
        # Only validate on creation (new issue)
        if not self.instance:
            if book_copy.status != 'Available':
                raise serializers.ValidationError(
                    {"book_copy": f"Book copy with barcode '{book_copy.barcode}' is currently '{book_copy.status}' and cannot be issued."}
                )
        return attrs



# ── Inventory & Store Serializers ──
class InventoryCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = InventoryCategory
        fields = '__all__'

class InventoryItemSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    class Meta:
        model = InventoryItem
        fields = '__all__'

class SupplierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Supplier
        fields = '__all__'

class InventoryTransactionSerializer(serializers.ModelSerializer):
    item_name = serializers.CharField(source='item.name', read_only=True)
    category_name = serializers.CharField(source='item.category.name', read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True)
    class Meta:
        model = InventoryTransaction
        fields = '__all__'


# ── Digital Valuation Serializers ──
class ValuationSessionSerializer(serializers.ModelSerializer):
    exam_name = serializers.CharField(source='exam.name', read_only=True)
    evaluator_name = serializers.SerializerMethodField()
    academic_year = serializers.CharField(source='exam.academic_year', read_only=True)
    semester = serializers.CharField(source='exam.semester', read_only=True)
    course_name = serializers.CharField(source='exam.course.course_name', read_only=True)
    total_papers = serializers.SerializerMethodField()
    graded_papers = serializers.SerializerMethodField()

    class Meta:
        model = ValuationSession
        fields = '__all__'

    def get_evaluator_name(self, obj):
        if not obj.evaluator or not obj.evaluator.user:
            return "Unknown Evaluator"
        full_name = obj.evaluator.user.get_full_name()
        if not full_name:
            full_name = obj.evaluator.user.username
        return f"{full_name} ({obj.evaluator.employee_id})"

    def get_total_papers(self, obj):
        return obj.papers.count()

    def get_graded_papers(self, obj):
        return obj.papers.filter(status='Evaluated').count()

class ScannedPaperSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_id = serializers.SerializerMethodField()
    exam_name = serializers.CharField(source='session.exam.name', read_only=True)
    session_status = serializers.CharField(source='session.status', read_only=True)
    question_paper_url = serializers.CharField(source='session.exam.question_paper_url', read_only=True)
    question_structure = serializers.JSONField(source='session.exam.question_structure', read_only=True)
    academic_year = serializers.CharField(source='session.exam.academic_year', read_only=True)
    semester = serializers.CharField(source='session.exam.semester', read_only=True)
    course_name = serializers.CharField(source='session.exam.course.course_name', read_only=True)

    class Meta:
        model = ScannedPaper
        fields = '__all__'



    def get_student_name(self, obj):
        request = self.context.get('request')
        if request and request.user:
            group = request.user.groups.first().name if request.user.groups.exists() else None
            # Mask student name for Faculty (evaluators)
            if group == 'Faculty':
                return "Anonymous Student"
        if not obj.student or not obj.student.user:
            return "Unknown Student"
        full_name = obj.student.user.get_full_name()
        if not full_name:
            return obj.student.user.username
        return full_name

    def get_student_id(self, obj):
        request = self.context.get('request')
        if request and request.user:
            group = request.user.groups.first().name if request.user.groups.exists() else None
            # Mask student ID for Faculty (evaluators)
            if group == 'Faculty':
                return "VAL-MASKED"
        return obj.student.student_id

    def validate(self, attrs):
        if self.instance:
            # Enforce lock on completed runs
            if self.instance.session.status == 'Completed':
                raise serializers.ValidationError("Cannot modify paper evaluation. The valuation session is completed/locked.")
        return attrs


class AIGradingSuggestionSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.SerializerMethodField()
    applied_by_name = serializers.SerializerMethodField()

    class Meta:
        model = AIGradingSuggestion
        fields = '__all__'
        read_only_fields = [
            'scanned_paper', 'requested_by', 'requested_at', 'model_used',
            'question_scores_suggested', 'overall_confidence', 'overall_notes',
            'status', 'error_message', 'applied_at', 'applied_by',
        ]

    def get_requested_by_name(self, obj):
        return obj.requested_by.get_full_name() or obj.requested_by.username if obj.requested_by else None

    def get_applied_by_name(self, obj):
        return obj.applied_by.get_full_name() or obj.applied_by.username if obj.applied_by else None


# ── Student Exam Results ──
class StudentExamResultSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    student_id = serializers.CharField(source='student.student_id', read_only=True)
    exam_name = serializers.CharField(source='exam.name', read_only=True)
    course_name = serializers.CharField(source='exam.course.course_name', read_only=True)
    total_marks = serializers.IntegerField(source='exam.total_marks', read_only=True)
    academic_year = serializers.CharField(source='exam.academic_year', read_only=True)
    semester = serializers.CharField(source='exam.semester', read_only=True)
    percentage = serializers.SerializerMethodField()

    class Meta:
        model = StudentExamResult
        fields = '__all__'
        read_only_fields = ('grade', 'is_pass', 'entered_by')

    def get_student_name(self, obj):
        if not obj.student or not obj.student.user:
            return "Unknown Student"
        return obj.student.user.get_full_name() or obj.student.user.username

    def get_percentage(self, obj):
        return obj.percentage

    def validate(self, attrs):
        exam = attrs.get('exam') or getattr(self.instance, 'exam', None)
        marks = attrs.get('marks_obtained', getattr(self.instance, 'marks_obtained', None))
        if exam and marks is not None and marks > exam.total_marks:
            raise serializers.ValidationError("Marks obtained cannot exceed exam total marks.")
        return attrs


# ── Compliance & Accreditation Serializers ──
class ComplianceCertificateTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComplianceCertificateType
        fields = '__all__'


class ComplianceCertificateSerializer(serializers.ModelSerializer):
    certificate_type_name = serializers.CharField(source='certificate_type.name', read_only=True)
    uploaded_by_name = serializers.SerializerMethodField()
    status = serializers.ReadOnlyField()

    class Meta:
        model = ComplianceCertificate
        fields = '__all__'
        read_only_fields = ('uploaded_by',)

    def get_uploaded_by_name(self, obj):
        if not obj.uploaded_by:
            return None
        return obj.uploaded_by.get_full_name() or obj.uploaded_by.username


class AccreditationCriterionSerializer(serializers.ModelSerializer):
    class Meta:
        model = AccreditationCriterion
        fields = '__all__'


class EvidenceItemSerializer(serializers.ModelSerializer):
    criterion_code = serializers.CharField(source='criterion.code', read_only=True)
    criterion_title = serializers.CharField(source='criterion.title', read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True, default=None)
    financial_year_label = serializers.CharField(source='financial_year.label', read_only=True)
    uploaded_by_name = serializers.SerializerMethodField()
    signed_off_by_name = serializers.SerializerMethodField()

    class Meta:
        model = EvidenceItem
        fields = '__all__'
        read_only_fields = ('uploaded_by', 'status', 'submitted_at', 'signed_off_by', 'signed_off_at')

    def get_uploaded_by_name(self, obj):
        return obj.uploaded_by.get_full_name() or obj.uploaded_by.username if obj.uploaded_by else None

    def get_signed_off_by_name(self, obj):
        return obj.signed_off_by.get_full_name() or obj.signed_off_by.username if obj.signed_off_by else None


# ── Financial Year & Ledger Serializers ──
class FinancialYearSerializer(serializers.ModelSerializer):
    opening_balance = serializers.ReadOnlyField()
    total_receipts = serializers.SerializerMethodField()
    total_payments = serializers.SerializerMethodField()
    closing_balance = serializers.SerializerMethodField()

    class Meta:
        model = FinancialYear
        fields = '__all__'
        read_only_fields = ('is_locked', 'locked_at', 'locked_by')

    def get_total_receipts(self, obj):
        return obj.total_receipts()

    def get_total_payments(self, obj):
        return obj.total_payments()

    def get_closing_balance(self, obj):
        return obj.closing_balance()


class IncomeCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = IncomeCategory
        fields = '__all__'


class IncomeEntrySerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    financial_year_label = serializers.CharField(source='financial_year.label', read_only=True)
    recorded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = IncomeEntry
        fields = '__all__'
        read_only_fields = ('recorded_by',)

    def get_recorded_by_name(self, obj):
        return obj.recorded_by.get_full_name() or obj.recorded_by.username if obj.recorded_by else None

    def validate_financial_year(self, value):
        if value.is_locked:
            raise serializers.ValidationError(f"Financial year {value.label} is locked — closed years are append-only.")
        return value


class ExpenseCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = ExpenseCategory
        fields = '__all__'


class ExpenseEntrySerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    department_name = serializers.CharField(source='department.name', read_only=True, default=None)
    vendor_name = serializers.CharField(source='vendor.name', read_only=True, default=None)
    financial_year_label = serializers.CharField(source='financial_year.label', read_only=True)
    recorded_by_name = serializers.SerializerMethodField()

    class Meta:
        model = ExpenseEntry
        fields = '__all__'
        read_only_fields = ('recorded_by',)

    def get_recorded_by_name(self, obj):
        return obj.recorded_by.get_full_name() or obj.recorded_by.username if obj.recorded_by else None

    def validate_financial_year(self, value):
        if value.is_locked:
            raise serializers.ValidationError(f"Financial year {value.label} is locked — closed years are append-only.")
        return value


class FixedAssetSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.name', read_only=True, default=None)
    supplier_name = serializers.CharField(source='supplier.name', read_only=True, default=None)
    current_written_down_value = serializers.SerializerMethodField()

    class Meta:
        model = FixedAsset
        fields = '__all__'

    def get_current_written_down_value(self, obj):
        return obj.written_down_value(datetime.date.today())

    def validate_purchase_date(self, value):
        from .models.finance import get_locked_financial_year_for_date
        locked_fy = get_locked_financial_year_for_date(value)
        if locked_fy:
            raise serializers.ValidationError(f"Financial year {locked_fy.label} is locked — closed years are append-only.")
        return value


# ── CA Role & Audit Portal Serializers ──
class AuditorProfileSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='user.username', read_only=True)
    email = serializers.CharField(source='user.email', read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditorProfile
        fields = '__all__'
        read_only_fields = ('user', 'invited_by')

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username


class AuditEngagementSerializer(serializers.ModelSerializer):
    auditor_name = serializers.SerializerMethodField()
    financial_year_label = serializers.CharField(source='financial_year.label', read_only=True)
    is_active = serializers.ReadOnlyField()

    class Meta:
        model = AuditEngagement
        fields = '__all__'
        read_only_fields = ('granted_by', 'revoked_at', 'revoked_by')

    def get_auditor_name(self, obj):
        return obj.auditor.firm_name or obj.auditor.user.get_full_name()


class AuditorAccessLogSerializer(serializers.ModelSerializer):
    auditor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditorAccessLog
        fields = '__all__'

    def get_auditor_name(self, obj):
        return obj.auditor.firm_name or obj.auditor.user.get_full_name()


# ── State Scholarship Reconciliation Serializers ──
class StateScholarshipSchemeSerializer(serializers.ModelSerializer):
    class Meta:
        model = StateScholarshipScheme
        fields = '__all__'


class StudentScholarshipRecordSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    scheme_name = serializers.CharField(source='scheme.name', read_only=True)
    financial_year_label = serializers.CharField(source='financial_year.label', read_only=True)
    reconciliation_gap = serializers.ReadOnlyField()

    class Meta:
        model = StudentScholarshipRecord
        fields = '__all__'
        read_only_fields = ('recorded_by',)

    def get_student_name(self, obj):
        return obj.student.get_full_name() or obj.student.username



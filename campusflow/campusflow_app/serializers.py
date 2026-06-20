from rest_framework import serializers
from .models.department import Department
from django.contrib.auth.models import User, Group, Permission
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
import uuid
import datetime
from user_agents import parse
from django.utils.translation import gettext_lazy as _
from django.http import HttpRequest
from ipware import get_client_ip
from .models.profile import StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile, ManagementProfile, AdministratorProfile, DepartmentHeadProfile
from .models.attendance import Attendance
from .models.location import Location
from django.db import transaction, connection
from django.db.models import Q
from rest_framework.exceptions import ValidationError
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from .models.classroom import Classroom
from .models.lecture import Lecture
from .models.attendance_log import FaceAttendanceLog
from .models.schedule import Schedule


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
        from django.db import connection

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
        if target_tenant:
            try:
                data['tenant_domain'] = target_tenant.get_primary_domain().domain
                data['tenant_code'] = target_tenant.code
                data['tenant_schema'] = target_tenant.schema_name  # Used by mobile app for X-Tenant header
            except Exception:
                data['tenant_domain'] = None
                data['tenant_code'] = None
                data['tenant_schema'] = target_tenant.schema_name if target_tenant else None

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
                'name': tenant.name,
                'schema': tenant.schema_name,
                'code': getattr(tenant, 'code', None),
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

        data['device_info'] = self.device_info
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
            'office_location_details',
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
        valid_roles = ['student', 'Faculty', 'Support Staff', 'Management', 'Administrator', 'Department Head']
        if role not in valid_roles:
            raise serializers.ValidationError({"role": f"Invalid role. Must be one of: {', '.join(valid_roles)}."})
        if role == 'student':
            if not student_id:
                raise serializers.ValidationError({"student_id": "Student ID is required for students."})
            if StudentProfile.objects.filter(student_id=student_id).exists():
                raise serializers.ValidationError({"student_id": "A student with this ID already exists."})
            if employee_id:
                raise serializers.ValidationError({"employee_id": "Employee ID should not be provided for students."})
            if not data.get('program_enrolled_in_id'):
                raise serializers.ValidationError({"program_enrolled_in_id": "Program enrolled in is required for students."})
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
            'office_location_details',
        ]
        for field_name in profile_field_names:
            if field_name in validated_data:
                if field_name == 'department_id':
                    profile_data['department'] = validated_data.pop(field_name)
                elif field_name == 'program_enrolled_in_id':
                    profile_data['program_enrolled_in'] = validated_data.pop(field_name)
                else:
                    profile_data[field_name] = validated_data.pop(field_name)

        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=password,
            first_name=validated_data.get('first_name', ''),
            last_name=validated_data.get('last_name', ''),
            is_active=False,  # Account needs activation via OTP
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
            # Management is usually created by SaaS Admin, so we might keep it active or pending
            fields['status'] = 'active' 
            ManagementProfile.objects.create(user=user, **fields)
            assign_role_permissions(user, 'Management')
        elif role == 'Administrator':
            fields = {k: v for k, v in profile_data.items() if hasattr(AdministratorProfile, k)}
            fields['status'] = 'active' # Admin created by SaaS/Mgmt is auto-active
            AdministratorProfile.objects.create(user=user, **fields)
            assign_role_permissions(user, 'Administrator')
        elif role == 'Department Head':
            fields = {k: v for k, v in profile_data.items() if hasattr(DepartmentHeadProfile, k)}
            fields['status'] = 'pending' # HOD needs Admin approval
            DepartmentHeadProfile.objects.create(user=user, **fields)
            assign_role_permissions(user, 'Department Head')
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

import math
# pyrefly: ignore [missing-import]
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
from django.db import transaction, connection
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from django.contrib.auth.models import User
from ..serializers import UserRegistrationSerializer, MyTokenObtainPairSerializer, LogoutSerializer
from rest_framework_simplejwt.views import TokenObtainPairView
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt
from rest_framework import generics, permissions
from ..models.profile import (
    StudentProfile, TeachingStaffProfile, NonTeachingStaffProfile,
    ManagementProfile, AdministratorProfile, DepartmentHeadProfile
)
from ..permissions import (
    IsSaaSAdmin, IsCollegeAdmin, IsSaaSOrCollegeAdmin, IsFacultyOrAbove,
    IsNotStudent, DepartmentExistsForUserCreation, CanCreateCollegeAdmin,
    is_saas_admin, is_college_admin, get_user_group
)
import random
import datetime
from django.core.mail import send_mail
from django.utils import timezone
from django.core.cache import cache
# from ..models.otp import EmailOTP  # Removed in favor of Cache


@method_decorator(csrf_exempt, name='dispatch')
class MyObtainTokenPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer


class VerifyTokenView(APIView):
    def post(self, request, *args, **kwargs):
        token = request.data.get('token')
        if token:
            return Response({'message': 'Token is valid.'}, status=status.HTTP_200_OK)
        return Response({'error': 'Invalid token.'}, status=status.HTTP_400_BAD_REQUEST)


class RequestOTPView(APIView):
    """
    Generate and send an OTP to the user's email for verification.
    If role is 'student', it checks if the email domain is allowed.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        role = request.data.get('role', '').strip()

        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        # ── Domain Check for Students & Faculty ──
        # Any role that belongs to the college should ideally use the official domain.
        if role in ('student', 'Faculty', 'Support Staff', 'Department Head'):
            tenant = getattr(connection, 'tenant', None)
            permitted_domain = getattr(tenant, 'permitted_email_domain', None)
            if tenant and permitted_domain:
                if not email.endswith(f"@{permitted_domain}"):
                    return Response(
                        {"error": f"Registration for '{role}' is only allowed with @{permitted_domain} emails."},
                        status=status.HTTP_400_BAD_REQUEST
                    )

        # Generate 6-digit OTP
        otp_code = str(random.randint(100000, 999999))
        expiry_time = timezone.now() + datetime.timedelta(minutes=10)

        # Save to Cache (expires in 10 minutes)
        cache.set(f"otp_{email}", otp_code, timeout=600)

        # Send Email via Brevo (SMTP)
        try:
            subject = "Your CampusFlow Verification Code"
            message = f"Your OTP for registration is: {otp_code}\n\nThis code will expire in 10 minutes."
            send_mail(
                subject,
                message,
                None, # Uses DEFAULT_FROM_EMAIL
                [email],
                fail_silently=False,
            )
            return Response({"message": f"OTP sent successfully to {email}."}, status=status.HTTP_200_OK)
        except Exception as e:
            return Response(
                {"error": f"Failed to send email. Please check SMTP settings. Detail: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class StudentRegistrationView(generics.CreateAPIView):
    """
    Public self-registration for Students.
    Requires OTP verification after registration.
    """
    serializer_class = UserRegistrationSerializer
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        # Force the role to 'student' to prevent role escalation
        data = request.data.copy()
        data['role'] = 'student'
        
        email = data.get('email', '').strip().lower()

        # ── Auto-tenant routing by email domain ──
        if connection.schema_name == 'public':
            if not email or '@' not in email:
                return Response({"error": "A valid email address is required for registration."}, status=status.HTTP_400_BAD_REQUEST)
            email_domain = email.split('@')[-1]
            
            from tenants.models import Tenant
            # Find the tenant with this permitted email domain
            target_tenant = Tenant.objects.filter(permitted_email_domain=email_domain).first()
            if not target_tenant:
                return Response(
                    {"error": f"No college registration is configured for the email domain '@{email_domain}'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Switch context to the target tenant's schema for the rest of this request
            connection.set_tenant(target_tenant)
        
        # ── Domain Check ──
        tenant = getattr(connection, 'tenant', None)
        permitted_domain = getattr(tenant, 'permitted_email_domain', None)
        if tenant and permitted_domain:
            if not email.endswith(f"@{permitted_domain}"):
                return Response(
                    {"error": f"Student registration must use @{permitted_domain} emails."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # ── Department Check ──
        from ..models.department import Department
        if not Department.objects.exists():
            return Response(
                {"error": "Student registration is currently closed: no departments exist."},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        new_user = serializer.save()

        # ── Generate & Send Activation OTP ──
        otp_code = str(random.randint(100000, 999999))
        cache.set(f"otp_{new_user.email}", otp_code, timeout=600)

        try:
            send_mail(
                "Verify your CampusFlow Account",
                f"Hello {new_user.first_name},\n\nYour student verification code is: {otp_code}",
                None, [new_user.email]
            )
        except Exception:
            pass

        return Response(
            {
                "message": "Student registration successful. Please check your email for the OTP.",
                "username": new_user.username,
                "email": new_user.email,
                "role": "student"
            },
            status=status.HTTP_201_CREATED
        )


class StaffRegistrationView(generics.CreateAPIView):
    """
    Restricted registration for Faculty, Support Staff, and Department Heads.
    Must be performed by a College Admin (Management/Administrator).
    """
    serializer_class = UserRegistrationSerializer
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def post(self, request, *args, **kwargs):
        role = request.data.get('role', '').strip()
        user = request.user

        # ── Role Validation ──
        valid_staff_roles = ('Faculty', 'Support Staff', 'Department Head', 'Administrator', 'Management')
        if role not in valid_staff_roles:
            return Response(
                {"error": f"Invalid role for staff registration. Must be one of: {', '.join(valid_staff_roles)}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # ── Higher Level Role Gating ──
        if role == 'Management' and not is_saas_admin(user):
            return Response({"error": "Only SaaS Admin can create Management accounts."}, status=status.HTTP_403_FORBIDDEN)
        
        if role == 'Administrator' and not (is_saas_admin(user) or get_user_group(user) == 'Management'):
            return Response({"error": "Insufficient permissions to create Administrator accounts."}, status=status.HTTP_403_FORBIDDEN)

        # ── Domain Check ──
        email = request.data.get('email', '').strip().lower()
        tenant = getattr(connection, 'tenant', None)
        permitted_domain = getattr(tenant, 'permitted_email_domain', None)
        if tenant and permitted_domain:
            if not email.endswith(f"@{permitted_domain}"):
                return Response(
                    {"error": f"Staff email must end with @{permitted_domain}."},
                    status=status.HTTP_400_BAD_REQUEST
                )

        # ── Department Check ──
        roles_requiring_dept = ('Faculty', 'Department Head')
        if role in roles_requiring_dept:
            from ..models.department import Department
            if not Department.objects.exists():
                return Response({"error": f"A department must exist to create a {role}."}, status=status.HTTP_400_BAD_REQUEST)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        new_user = serializer.save()

        # ── Generate OTP for staff activation (optional, but consistent) ──
        otp_code = str(random.randint(100000, 999999))
        cache.set(f"otp_{new_user.email}", otp_code, timeout=600)
        try:
            send_mail("CampusFlow Staff Account Created", f"Account created for {role} role. OTP: {otp_code}", None, [new_user.email])
        except Exception:
            pass

        return Response(
            {
                "message": f"{role} account created successfully. OTP sent for activation.",
                "username": new_user.username,
                "role": role
            },
            status=status.HTTP_201_CREATED
        )


class VerifyAccountView(APIView):
    """
    Verify the OTP sent to the user's email and activate their account.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        otp_provided = request.data.get('otp', '').strip()

        if not email or not otp_provided:
            return Response({"error": "Email and OTP are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Verify OTP from cache
        cached_otp = cache.get(f"otp_{email}")
        if not cached_otp or cached_otp != otp_provided:
            return Response({"error": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)

        # Activate the user
        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        if user.is_active:
            return Response({"message": "Account is already active."}, status=status.HTTP_200_OK)

        user.is_active = True
        user.save()
        cache.delete(f"otp_{email}")

        return Response({"message": "Account activated successfully! You can now log in."}, status=status.HTTP_200_OK)


class ResendOTPView(APIView):
    """
    Resend the activation OTP to the user's email.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        if user.is_active:
            return Response({"error": "Account is already active."}, status=status.HTTP_400_BAD_REQUEST)

        otp_code = str(random.randint(100000, 999999))
        cache.set(f"otp_{email}", otp_code, timeout=600)

        try:
            send_mail("Verify your CampusFlow Account", f"Your verification code is: {otp_code}", None, [email])
            return Response({"message": "OTP resent successfully."}, status=status.HTTP_200_OK)
        except Exception:
            return Response({"error": "Failed to send email."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ResetDeviceLockView(APIView):
    """
    Allow Faculty, Department Heads, or Management to reset a student's device lock.
    This is used when a student gets a new phone and needs to re-bind their account.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def post(self, request):
        student_id_str = request.data.get('student_id', '').strip()
        
        if not student_id_str:
            return Response({"error": "student_id is required."}, status=status.HTTP_400_BAD_REQUEST)
        
        # Find the student profile by their student_id (e.g. STU001)
        profile = StudentProfile.objects.filter(student_id=student_id_str).first()
        if not profile:
            return Response({"error": f"Student with ID '{student_id_str}' not found."}, status=status.HTTP_404_NOT_FOUND)
        
        profile.locked_device_id = None
        profile.save()
        
        return Response(
            {
                "message": f"Device lock reset successfully for student {profile.user.get_full_name()} ({student_id_str}).",
                "student": profile.user.username
            },
            status=status.HTTP_200_OK
        )


class RequestBiometricResetView(APIView):
    """
    Allow a student to submit a request to reset their biometric data / device lock.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if not hasattr(request.user, 'student_profile'):
            return Response({"error": "Only students can view reset requests."}, status=status.HTTP_400_BAD_REQUEST)
        
        profile = request.user.student_profile
        from ..models.device_reset import DeviceResetRequest
        
        latest_request = DeviceResetRequest.objects.filter(student=profile).order_by('-requested_at').first()
        if not latest_request:
            return Response({"has_request": False, "status": None}, status=status.HTTP_200_OK)
        
        return Response({
            "has_request": True,
            "status": latest_request.status,
            "requested_at": latest_request.requested_at,
            "reason": latest_request.reason
        }, status=status.HTTP_200_OK)

    def post(self, request):
        if not hasattr(request.user, 'student_profile'):
            return Response({"error": "Only students can submit biometric reset requests."}, status=status.HTTP_400_BAD_REQUEST)
        
        profile = request.user.student_profile
        reason = request.data.get('reason', 'Request biometric reset').strip()

        from ..models.device_reset import DeviceResetRequest
        
        # Check if there is already a pending request
        existing_request = DeviceResetRequest.objects.filter(student=profile, status='pending').first()
        if existing_request:
            return Response(
                {"error": "You already have a pending biometric reset request. Please wait for review or contact your HOD/Admin."},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Create a new reset request
        DeviceResetRequest.objects.create(
            student=profile,
            reason=reason,
            status='pending'
        )

        return Response(
            {"message": "Biometric reset request submitted successfully. Please wait for HOD/Admin review."},
            status=status.HTTP_201_CREATED
        )


class LogoutAPIView(generics.GenericAPIView):
    serializer_class = LogoutSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        serializer = self.serializer_class(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({'detail': 'Logout successful'}, status=status.HTTP_204_NO_CONTENT)


# ─────────────────────────────────────────────────────────────────────────────
# Profile Views
# ─────────────────────────────────────────────────────────────────────────────

class ManagementUserProfileView(APIView):
    """View all Management profiles. Only Management or SaaS Admin can access."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        user = request.user
        group = get_user_group(user)

        # Non-superuser must specifically be Management to list all management profiles
        if not is_saas_admin(user) and group != 'Management':
            return Response(
                {"detail": "Only Management users or SaaS Admin can view management profiles."},
                status=status.HTTP_403_FORBIDDEN
            )

        management_profiles = ManagementProfile.objects.all().select_related('user', 'department')

        result = []
        for prof in management_profiles:
            result.append({
                "user": {
                    "username": prof.user.username, "email": prof.user.email,
                    "first_name": prof.user.first_name, "last_name": prof.user.last_name
                },
                "role": "Management",
                "employee_id": prof.employee_id,
                "department": prof.department.name if prof.department else None,
                "middle_name": prof.middle_name, "date_of_birth": prof.date_of_birth,
                "gender": prof.gender, "aadhaar_number": prof.aadhaar_number,
                "emergency_contact_name": prof.emergency_contact_name,
                "emergency_contact_relationship": prof.emergency_contact_relationship,
                "emergency_contact_phone": prof.emergency_contact_phone,
                "contact_number": prof.contact_number,
                "current_address_line1": prof.current_address_line1,
                "current_address_line2": prof.current_address_line2,
                "current_city": prof.current_city, "current_district": prof.current_district,
                "current_state": prof.current_state, "current_pincode": prof.current_pincode,
                "permanent_address_line1": prof.permanent_address_line1,
                "permanent_address_line2": prof.permanent_address_line2,
                "permanent_city": prof.permanent_city,
                "permanent_district": prof.permanent_district,
                "permanent_state": prof.permanent_state,
                "permanent_pincode": prof.permanent_pincode,
                "date_of_joining": prof.date_of_joining, "designation": prof.designation,
                "employee_type": prof.employee_type,
                "bank_account_number": prof.bank_account_number,
                "pan_number": prof.pan_number, "staff_role": prof.staff_role,
                "status": prof.status,
                "profile_picture": prof.profile_picture.url if prof.profile_picture else None,
                "assigned_responsibilities": prof.assigned_responsibilities,
                "office_location_details": prof.office_location_details,
            })
        return Response(result, status=status.HTTP_200_OK)


class AdministratorUserProfileView(APIView):
    """View all Administrator profiles. Only Management or SaaS Admin can access."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        user = request.user
        group = get_user_group(user)

        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response(
                {"detail": "You do not have permission to view administrator profiles."},
                status=status.HTTP_403_FORBIDDEN
            )

        admin_profiles = AdministratorProfile.objects.all().select_related('user', 'department')

        result = []
        for prof in admin_profiles:
            result.append({
                "user": {
                    "username": prof.user.username, "email": prof.user.email,
                    "first_name": prof.user.first_name, "last_name": prof.user.last_name
                },
                "role": "Administrator",
                "employee_id": prof.employee_id,
                "department": prof.department.name if prof.department else None,
                "middle_name": prof.middle_name, "date_of_birth": prof.date_of_birth,
                "gender": prof.gender, "aadhaar_number": prof.aadhaar_number,
                "emergency_contact_name": prof.emergency_contact_name,
                "emergency_contact_relationship": prof.emergency_contact_relationship,
                "emergency_contact_phone": prof.emergency_contact_phone,
                "contact_number": prof.contact_number,
                "current_address_line1": prof.current_address_line1,
                "current_address_line2": prof.current_address_line2,
                "current_city": prof.current_city, "current_district": prof.current_district,
                "current_state": prof.current_state, "current_pincode": prof.current_pincode,
                "permanent_address_line1": prof.permanent_address_line1,
                "permanent_address_line2": prof.permanent_address_line2,
                "permanent_city": prof.permanent_city,
                "permanent_district": prof.permanent_district,
                "permanent_state": prof.permanent_state,
                "permanent_pincode": prof.permanent_pincode,
                "date_of_joining": prof.date_of_joining, "designation": prof.designation,
                "employee_type": prof.employee_type,
                "bank_account_number": prof.bank_account_number,
                "pan_number": prof.pan_number, "staff_role": prof.staff_role,
                "status": prof.status,
                "profile_picture": prof.profile_picture.url if prof.profile_picture else None,
                "assigned_responsibilities": prof.assigned_responsibilities,
            })
        return Response(result, status=status.HTTP_200_OK)


class TeachingStaffUserProfileView(APIView):
    """View all Teaching Staff profiles. College Admins and above only."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        user = request.user
        group = get_user_group(user)

        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response(
                {"detail": "You do not have permission to view teaching staff profiles."},
                status=status.HTTP_403_FORBIDDEN
            )

        teaching_staff_profiles = TeachingStaffProfile.objects.all().select_related('user', 'department')

        result = []
        for prof in teaching_staff_profiles:
            result.append({
                "user": {
                    "username": prof.user.username, "email": prof.user.email,
                    "first_name": prof.user.first_name, "last_name": prof.user.last_name
                },
                "role": "Faculty",
                "employee_id": prof.employee_id,
                "department": prof.department.name if prof.department else None,
                "middle_name": prof.middle_name, "date_of_birth": prof.date_of_birth,
                "gender": prof.gender, "blood_group": prof.blood_group,
                "aadhaar_number": prof.aadhaar_number, "nationality": prof.nationality,
                "emergency_contact_name": prof.emergency_contact_name,
                "emergency_contact_relationship": prof.emergency_contact_relationship,
                "emergency_contact_phone": prof.emergency_contact_phone,
                "contact_number": prof.contact_number,
                "alternate_phone_number": prof.alternate_phone_number,
                "current_address_line1": prof.current_address_line1,
                "current_address_line2": prof.current_address_line2,
                "current_city": prof.current_city, "current_district": prof.current_district,
                "current_state": prof.current_state, "current_pincode": prof.current_pincode,
                "permanent_address_line1": prof.permanent_address_line1,
                "permanent_address_line2": prof.permanent_address_line2,
                "permanent_city": prof.permanent_city,
                "permanent_district": prof.permanent_district,
                "permanent_state": prof.permanent_state,
                "permanent_pincode": prof.permanent_pincode,
                "date_of_joining": prof.date_of_joining, "designation": prof.designation,
                "qualifications": prof.qualifications, "specializations": prof.specializations,
                "experience_years": prof.experience_years, "employee_type": prof.employee_type,
                "bank_account_number": prof.bank_account_number,
                "pan_number": prof.pan_number, "epf_esi_details": prof.epf_esi_details,
                "staff_role": prof.staff_role, "status": prof.status,
                "profile_picture": prof.profile_picture.url if prof.profile_picture else None,
                "office_room_number": prof.office_room_number,
                "research_interests": prof.research_interests,
                "publications_link": prof.publications_link,
                "replacement_availability_preferences": prof.replacement_availability_preferences,
            })
        return Response(result, status=status.HTTP_200_OK)


class StudentUserProfileView(APIView):
    """
    View all Student profiles.
    Students cannot list other students — only Faculty and above can.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request):
        student_profiles = StudentProfile.objects.all().select_related('user', 'department')

        result = []
        for stud in student_profiles:
            result.append({
                "user": {
                    "username": stud.user.username, "email": stud.user.email,
                    "first_name": stud.user.first_name, "last_name": stud.user.last_name
                },
                "role": "Student",
                "student_id": stud.student_id,
                "department": stud.department.name if stud.department else None,
                "middle_name": stud.middle_name, "date_of_birth": stud.date_of_birth,
                "gender": stud.gender, "blood_group": stud.blood_group,
                "aadhaar_number": stud.aadhaar_number, "nationality": stud.nationality,
                "religion": stud.religion, "category": stud.category,
                "disability_status": stud.disability_status,
                "disability_details": stud.disability_details,
                "emergency_contact_name": stud.emergency_contact_name,
                "emergency_contact_relationship": stud.emergency_contact_relationship,
                "emergency_contact_phone": stud.emergency_contact_phone,
                "contact_number": stud.contact_number,
                "alternate_phone_number": stud.alternate_phone_number,
                "current_address_line1": stud.current_address_line1,
                "current_address_line2": stud.current_address_line2,
                "current_city": stud.current_city, "current_district": stud.current_district,
                "current_state": stud.current_state, "current_pincode": stud.current_pincode,
                "permanent_address_line1": stud.permanent_address_line1,
                "permanent_address_line2": stud.permanent_address_line2,
                "permanent_city": stud.permanent_city,
                "permanent_district": stud.permanent_district,
                "permanent_state": stud.permanent_state,
                "permanent_pincode": stud.permanent_pincode,
                "admission_date": stud.admission_date,
                "admission_number": stud.admission_number,
                "program_enrolled_in": stud.program_enrolled_in if stud.program_enrolled_in else None,
                "batch_academic_year": stud.batch_academic_year,
                "current_semester_year": stud.current_semester_year,
                "section_division": stud.section_division,
                "previous_school_college": stud.previous_school_college,
                "tenth_marksheet_percentage": stud.tenth_marksheet_percentage,
                "twelfth_marksheet_percentage": stud.twelfth_marksheet_percentage,
                "status": stud.status,
                "profile_picture": stud.profile_picture.url if stud.profile_picture else None,
                "biometric_id": stud.biometric_id,
                "hostel_transport_details": stud.hostel_transport_details,
                "scholarship_fee_concession_details": stud.scholarship_fee_concession_details,
                "medical_conditions_allergies": stud.medical_conditions_allergies,
                "extracurricular_interests": stud.extracurricular_interests,
            })
        return Response(result, status=status.HTTP_200_OK)


class DepartmentHeadUserProfileView(APIView):
    """View all Department Head profiles. College Admins and above only."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        user = request.user
        group = get_user_group(user)

        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response(
                {"detail": "You do not have permission to view department head profiles."},
                status=status.HTTP_403_FORBIDDEN
            )

        profiles = DepartmentHeadProfile.objects.all().select_related('user', 'department')

        result = []
        for prof in profiles:
            result.append({
                "user": {
                    "username": prof.user.username, "email": prof.user.email,
                    "first_name": prof.user.first_name, "last_name": prof.user.last_name
                },
                "role": "Department Head",
                "employee_id": prof.employee_id,
                "department": prof.department.name if prof.department else None,
                "middle_name": prof.middle_name, "date_of_birth": prof.date_of_birth,
                "gender": prof.gender, "aadhaar_number": prof.aadhaar_number,
                "emergency_contact_name": prof.emergency_contact_name,
                "emergency_contact_relationship": prof.emergency_contact_relationship,
                "emergency_contact_phone": prof.emergency_contact_phone,
                "contact_number": prof.contact_number,
                "current_address_line1": prof.current_address_line1, "current_address_line2": prof.current_address_line2,
                "current_city": prof.current_city, "current_district": prof.current_district,
                "current_state": prof.current_state, "current_pincode": prof.current_pincode,
                "permanent_address_line1": prof.permanent_address_line1, "permanent_address_line2": prof.permanent_address_line2,
                "permanent_city": prof.permanent_city, "permanent_district": prof.permanent_district,
                "permanent_state": prof.permanent_state, "permanent_pincode": prof.permanent_pincode,
                "date_of_joining": prof.date_of_joining, "designation": prof.designation,
                "employee_type": prof.employee_type, "bank_account_number": prof.bank_account_number,
                "pan_number": prof.pan_number, "staff_role": prof.staff_role, "status": prof.status,
                "profile_picture": prof.profile_picture.url if prof.profile_picture else None,
            })
        return Response(result, status=status.HTTP_200_OK)


class NonTeachingStaffUserProfileView(APIView):
    """View all Support Staff profiles. College Admins and above only."""
    permission_classes = [IsAuthenticated, IsSaaSOrCollegeAdmin]

    def get(self, request):
        user = request.user
        group = get_user_group(user)

        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response(
                {"detail": "You do not have permission to view support staff profiles."},
                status=status.HTTP_403_FORBIDDEN
            )

        profiles = NonTeachingStaffProfile.objects.all().select_related('user', 'department')

        result = []
        for prof in profiles:
            result.append({
                "user": {
                    "username": prof.user.username, "email": prof.user.email,
                    "first_name": prof.user.first_name, "last_name": prof.user.last_name
                },
                "role": "Support Staff",
                "employee_id": prof.employee_id,
                "department": prof.department.name if prof.department else None,
                "middle_name": prof.middle_name, "date_of_birth": prof.date_of_birth,
                "gender": prof.gender, "aadhaar_number": prof.aadhaar_number,
                "emergency_contact_name": prof.emergency_contact_name,
                "emergency_contact_relationship": prof.emergency_contact_relationship,
                "emergency_contact_phone": prof.emergency_contact_phone,
                "contact_number": prof.contact_number,
                "current_address_line1": prof.current_address_line1, "current_address_line2": prof.current_address_line2,
                "current_city": prof.current_city, "current_district": prof.current_district,
                "current_state": prof.current_state, "current_pincode": prof.current_pincode,
                "permanent_address_line1": prof.permanent_address_line1, "permanent_address_line2": prof.permanent_address_line2,
                "permanent_city": prof.permanent_city, "permanent_district": prof.permanent_district,
                "permanent_state": prof.permanent_state, "permanent_pincode": prof.permanent_pincode,
                "date_of_joining": prof.date_of_joining, "designation": prof.designation,
                "employee_type": prof.employee_type, "bank_account_number": prof.bank_account_number,
                "pan_number": prof.pan_number, "staff_role": prof.staff_role, "status": prof.status,
                "profile_picture": prof.profile_picture.url if prof.profile_picture else None,
                "assigned_responsibilities": prof.assigned_responsibilities,
            })
        return Response(result, status=status.HTTP_200_OK)


class UserProfileView(APIView):
    """Return the requesting user's own profile."""
    permission_classes = [IsAuthenticated]

    def get(self, request):
        user = request.user
        usergroup = get_user_group(user)

        # Get tenant info
        tenant = getattr(connection, 'tenant', None)
        tenant_name = getattr(tenant, 'name', None) or (tenant.schema_name if tenant and hasattr(tenant, 'schema_name') else None)
        tenant_logo = None
        if tenant and hasattr(tenant, 'logo') and tenant.logo:
            try:
                tenant_logo = request.build_absolute_uri(tenant.logo.url)
            except (ValueError, AttributeError):
                pass

        profile_data = {}

        if usergroup == 'student':
            profile = StudentProfile.objects.filter(user=user).first()
            if not profile:
                return Response({"detail": "Student profile not found."}, status=status.HTTP_404_NOT_FOUND)
            profile_data = {
                "user": {"username": user.username, "email": user.email, "first_name": user.first_name, "last_name": user.last_name},
                "role": usergroup, "tenant": tenant_name,
                "student_id": profile.student_id,
                "department": profile.department.name if profile.department else None,
                "middle_name": profile.middle_name, "date_of_birth": profile.date_of_birth,
                "gender": profile.gender, "blood_group": profile.blood_group,
                "aadhaar_number": profile.aadhaar_number, "nationality": profile.nationality,
                "religion": profile.religion, "category": profile.category,
                "disability_status": profile.disability_status, "disability_details": profile.disability_details,
                "emergency_contact_name": profile.emergency_contact_name,
                "emergency_contact_relationship": profile.emergency_contact_relationship,
                "emergency_contact_phone": profile.emergency_contact_phone,
                "contact_number": profile.contact_number, "alternate_phone_number": profile.alternate_phone_number,
                "current_address_line1": profile.current_address_line1, "current_address_line2": profile.current_address_line2,
                "current_city": profile.current_city, "current_district": profile.current_district,
                "current_state": profile.current_state, "current_pincode": profile.current_pincode,
                "permanent_address_line1": profile.permanent_address_line1, "permanent_address_line2": profile.permanent_address_line2,
                "permanent_city": profile.permanent_city, "permanent_district": profile.permanent_district,
                "permanent_state": profile.permanent_state, "permanent_pincode": profile.permanent_pincode,
                "admission_date": profile.admission_date, "admission_number": profile.admission_number,
                "program_enrolled_in": profile.program_enrolled_in if profile.program_enrolled_in else None,
                "batch_academic_year": profile.batch_academic_year, "current_semester_year": profile.current_semester_year,
                "section_division": profile.section_division, "previous_school_college": profile.previous_school_college,
                "tenth_marksheet_percentage": profile.tenth_marksheet_percentage,
                "twelfth_marksheet_percentage": profile.twelfth_marksheet_percentage,
                "status": profile.status,
                "profile_picture": profile.profile_picture.url if profile.profile_picture else None,
                "biometric_id": profile.biometric_id, "hostel_transport_details": profile.hostel_transport_details,
                "scholarship_fee_concession_details": profile.scholarship_fee_concession_details,
                "medical_conditions_allergies": profile.medical_conditions_allergies,
                "extracurricular_interests": profile.extracurricular_interests,
            }

        elif usergroup == 'Faculty':
            profile = TeachingStaffProfile.objects.filter(user=user).first()
            if not profile:
                return Response({"detail": "Faculty profile not found."}, status=status.HTTP_404_NOT_FOUND)
            profile_data = {
                "user": {"username": user.username, "email": user.email, "first_name": user.first_name, "last_name": user.last_name},
                "role": usergroup, "tenant": tenant_name,
                "employee_id": profile.employee_id,
                "department": profile.department.name if profile.department else None,
                "middle_name": profile.middle_name, "date_of_birth": profile.date_of_birth,
                "gender": profile.gender, "blood_group": profile.blood_group,
                "aadhaar_number": profile.aadhaar_number, "nationality": profile.nationality,
                "emergency_contact_name": profile.emergency_contact_name,
                "emergency_contact_relationship": profile.emergency_contact_relationship,
                "emergency_contact_phone": profile.emergency_contact_phone,
                "contact_number": profile.contact_number, "alternate_phone_number": profile.alternate_phone_number,
                "current_address_line1": profile.current_address_line1, "current_address_line2": profile.current_address_line2,
                "current_city": profile.current_city, "current_district": profile.current_district,
                "current_state": profile.current_state, "current_pincode": profile.current_pincode,
                "permanent_address_line1": profile.permanent_address_line1, "permanent_address_line2": profile.permanent_address_line2,
                "permanent_city": profile.permanent_city, "permanent_district": profile.permanent_district,
                "permanent_state": profile.permanent_state, "permanent_pincode": profile.permanent_pincode,
                "date_of_joining": profile.date_of_joining, "designation": profile.designation,
                "qualifications": profile.qualifications, "specializations": profile.specializations,
                "experience_years": profile.experience_years, "employee_type": profile.employee_type,
                "bank_account_number": profile.bank_account_number, "pan_number": profile.pan_number,
                "epf_esi_details": profile.epf_esi_details, "staff_role": profile.staff_role, "status": profile.status,
                "profile_picture": profile.profile_picture.url if profile.profile_picture else None,
                "office_room_number": profile.office_room_number, "research_interests": profile.research_interests,
                "publications_link": profile.publications_link,
                "replacement_availability_preferences": profile.replacement_availability_preferences,
            }

        elif usergroup == 'Support Staff':
            profile = NonTeachingStaffProfile.objects.filter(user=user).first()
            if not profile:
                return Response({"detail": "Support Staff profile not found."}, status=status.HTTP_404_NOT_FOUND)
            profile_data = {
                "user": {"username": user.username, "email": user.email, "first_name": user.first_name, "last_name": user.last_name},
                "role": usergroup, "tenant": tenant_name,
                "employee_id": profile.employee_id,
                "department": profile.department.name if profile.department else None,
                "middle_name": profile.middle_name, "date_of_birth": profile.date_of_birth,
                "gender": profile.gender, "aadhaar_number": profile.aadhaar_number,
                "emergency_contact_name": profile.emergency_contact_name,
                "emergency_contact_relationship": profile.emergency_contact_relationship,
                "emergency_contact_phone": profile.emergency_contact_phone,
                "contact_number": profile.contact_number,
                "current_address_line1": profile.current_address_line1, "current_address_line2": profile.current_address_line2,
                "current_city": profile.current_city, "current_district": profile.current_district,
                "current_state": profile.current_state, "current_pincode": profile.current_pincode,
                "permanent_address_line1": profile.permanent_address_line1, "permanent_address_line2": profile.permanent_address_line2,
                "permanent_city": profile.permanent_city, "permanent_district": profile.permanent_district,
                "permanent_state": profile.permanent_state, "permanent_pincode": profile.permanent_pincode,
                "date_of_joining": profile.date_of_joining, "designation": profile.designation,
                "employee_type": profile.employee_type, "bank_account_number": profile.bank_account_number,
                "pan_number": profile.pan_number, "staff_role": profile.staff_role, "status": profile.status,
                "profile_picture": profile.profile_picture.url if profile.profile_picture else None,
                "assigned_responsibilities": profile.assigned_responsibilities,
            }

        elif usergroup == 'Management':
            profile = ManagementProfile.objects.filter(user=user).first()
            if not profile:
                return Response({"detail": "Management profile not found."}, status=status.HTTP_404_NOT_FOUND)
            profile_data = {
                "user": {"username": user.username, "email": user.email, "first_name": user.first_name, "last_name": user.last_name},
                "role": usergroup, "tenant": tenant_name,
                "employee_id": profile.employee_id,
                "department": profile.department.name if profile.department else None,
                "middle_name": profile.middle_name, "date_of_birth": profile.date_of_birth,
                "gender": profile.gender, "aadhaar_number": profile.aadhaar_number,
                "emergency_contact_name": profile.emergency_contact_name,
                "emergency_contact_relationship": profile.emergency_contact_relationship,
                "emergency_contact_phone": profile.emergency_contact_phone,
                "contact_number": profile.contact_number,
                "current_address_line1": profile.current_address_line1, "current_address_line2": profile.current_address_line2,
                "current_city": profile.current_city, "current_district": profile.current_district,
                "current_state": profile.current_state, "current_pincode": profile.current_pincode,
                "permanent_address_line1": profile.permanent_address_line1, "permanent_address_line2": profile.permanent_address_line2,
                "permanent_city": profile.permanent_city, "permanent_district": profile.permanent_district,
                "permanent_state": profile.permanent_state, "permanent_pincode": profile.permanent_pincode,
                "date_of_joining": profile.date_of_joining, "designation": profile.designation,
                "employee_type": profile.employee_type, "bank_account_number": profile.bank_account_number,
                "pan_number": profile.pan_number, "staff_role": profile.staff_role, "status": profile.status,
                "profile_picture": profile.profile_picture.url if profile.profile_picture else None,
                "assigned_responsibilities": profile.assigned_responsibilities,
                "office_location_details": profile.office_location_details,
            }

        elif usergroup == 'Administrator':
            profile = AdministratorProfile.objects.filter(user=user).first()
            if not profile:
                return Response({"detail": "Administrator profile not found."}, status=status.HTTP_404_NOT_FOUND)
            profile_data = {
                "user": {"username": user.username, "email": user.email, "first_name": user.first_name, "last_name": user.last_name},
                "role": usergroup, "tenant": tenant_name,
                "employee_id": profile.employee_id,
                "department": profile.department.name if profile.department else None,
                "middle_name": profile.middle_name, "date_of_birth": profile.date_of_birth,
                "gender": profile.gender, "aadhaar_number": profile.aadhaar_number,
                "emergency_contact_name": profile.emergency_contact_name,
                "emergency_contact_relationship": profile.emergency_contact_relationship,
                "emergency_contact_phone": profile.emergency_contact_phone,
                "contact_number": profile.contact_number,
                "current_address_line1": profile.current_address_line1, "current_address_line2": profile.current_address_line2,
                "current_city": profile.current_city, "current_district": profile.current_district,
                "current_state": profile.current_state, "current_pincode": profile.current_pincode,
                "permanent_address_line1": profile.permanent_address_line1, "permanent_address_line2": profile.permanent_address_line2,
                "permanent_city": profile.permanent_city, "permanent_district": profile.permanent_district,
                "permanent_state": profile.permanent_state, "permanent_pincode": profile.permanent_pincode,
                "date_of_joining": profile.date_of_joining, "designation": profile.designation,
                "employee_type": profile.employee_type, "bank_account_number": profile.bank_account_number,
                "pan_number": profile.pan_number, "staff_role": profile.staff_role, "status": profile.status,
                "profile_picture": profile.profile_picture.url if profile.profile_picture else None,
                "assigned_responsibilities": profile.assigned_responsibilities,
            }

        elif usergroup == 'Department Head':
            profile = DepartmentHeadProfile.objects.filter(user=user).first()
            if not profile:
                return Response({"detail": "Department Head profile not found."}, status=status.HTTP_404_NOT_FOUND)
            profile_data = {
                "user": {"username": user.username, "email": user.email, "first_name": user.first_name, "last_name": user.last_name},
                "role": usergroup, "tenant": tenant_name,
                "employee_id": profile.employee_id,
                "department": profile.department.name if profile.department else None,
                "middle_name": profile.middle_name, "date_of_birth": profile.date_of_birth,
                "gender": profile.gender, "aadhaar_number": profile.aadhaar_number,
                "emergency_contact_name": profile.emergency_contact_name,
                "emergency_contact_relationship": profile.emergency_contact_relationship,
                "emergency_contact_phone": profile.emergency_contact_phone,
                "contact_number": profile.contact_number,
                "current_address_line1": profile.current_address_line1, "current_address_line2": profile.current_address_line2,
                "current_city": profile.current_city, "current_district": profile.current_district,
                "current_state": profile.current_state, "current_pincode": profile.current_pincode,
                "permanent_address_line1": profile.permanent_address_line1, "permanent_address_line2": profile.permanent_address_line2,
                "permanent_city": profile.permanent_city, "permanent_district": profile.permanent_district,
                "permanent_state": profile.permanent_state, "permanent_pincode": profile.permanent_pincode,
                "date_of_joining": profile.date_of_joining, "designation": profile.designation,
                "employee_type": profile.employee_type, "bank_account_number": profile.bank_account_number,
                "pan_number": profile.pan_number, "staff_role": profile.staff_role, "status": profile.status,
                "profile_picture": profile.profile_picture.url if profile.profile_picture else None,
            }

        elif is_saas_admin(user):
            # SaaS Admin has no profile record in tenant — return basic user info
            profile_data = {
                "user": {"username": user.username, "email": user.email, "first_name": user.first_name, "last_name": user.last_name},
                "role": "SaaS Admin",
                "is_superuser": True,
                "tenant": tenant_name,
            }

        else:
            return Response({"detail": "User group not recognized."}, status=status.HTTP_400_BAD_REQUEST)

        profile_data["tenant_logo"] = tenant_logo
        return Response(profile_data, status=status.HTTP_200_OK)


# ─────────────────────────────────────────────────────────────────────────────
# Hierarchical Approval Views
# ─────────────────────────────────────────────────────────────────────────────

def get_user_profile_by_user(user):
    """Helper to get the profile object for any user based on their group."""
    group = get_user_group(user)
    if group == 'student': return getattr(user, 'student_profile', None)
    if group == 'Faculty': return getattr(user, 'teaching_staff_profile', None)
    if group == 'Support Staff': return getattr(user, 'non_teaching_staff_profile', None)
    if group == 'Management': return getattr(user, 'management_profile', None)
    if group == 'Administrator': return getattr(user, 'administrator_profile', None)
    if group == 'Department Head': return getattr(user, 'department_head_profile', None)
    return None

class PendingApprovalsView(APIView):
    """
    List all users pending approval based on the requester's permissions.
    Hierarchy:
    - Admin/Management: See all pending HODs, Faculty, and Support.
    - HOD: See pending Faculty and Support in their own department.
    """
    permission_classes = [IsAuthenticated, IsNotStudent]

    def get(self, request):
        user = request.user
        user_group = get_user_group(user)
        is_admin = is_saas_admin(user) or user_group in ('Management', 'Administrator')
        is_hod = user_group == 'Department Head'
        
        hod_dept = None
        if is_hod:
            hod_profile = getattr(user, 'department_head_profile', None)
            if hod_profile:
                hod_dept = hod_profile.department

        pending_users = []

        # Helper to format user data
        def format_pending(profile, role):
            return {
                "user_id": profile.user.id,
                "username": profile.user.username,
                "email": profile.user.email,
                "full_name": profile.user.get_full_name(),
                "role": role,
                "department": profile.department.name if hasattr(profile, 'department') and profile.department else None,
                "employee_id": getattr(profile, 'employee_id', None),
                "date_joined": profile.user.date_joined
            }

        # 1. If Admin: Collect everything pending
        if is_admin:
            for p in DepartmentHeadProfile.objects.filter(status='pending'):
                pending_users.append(format_pending(p, 'Department Head'))
            for p in TeachingStaffProfile.objects.filter(status='pending'):
                pending_users.append(format_pending(p, 'Faculty'))
            for p in NonTeachingStaffProfile.objects.filter(status='pending'):
                pending_users.append(format_pending(p, 'Support Staff'))

        # 2. If HOD: Collect Faculty and Support in their department
        elif is_hod and hod_dept:
            for p in TeachingStaffProfile.objects.filter(status='pending', department=hod_dept):
                pending_users.append(format_pending(p, 'Faculty'))
            for p in NonTeachingStaffProfile.objects.filter(status='pending', department=hod_dept):
                pending_users.append(format_pending(p, 'Support Staff'))
        
        else:
            return Response({"detail": "You do not have permission to view pending approvals."}, status=status.HTTP_403_FORBIDDEN)

        return Response(pending_users, status=status.HTTP_200_OK)


class ApproveUserView(APIView):
    """
    Approve or Reject a pending user registration.
    - HOD: Approved by Admin.
    - Faculty: Approved by HOD.
    - Support Staff: Approved by Admin or HOD.
    """
    permission_classes = [IsAuthenticated, IsNotStudent]

    def post(self, request):
        target_user_id = request.data.get('user_id')
        action = request.data.get('action') # 'approve' or 'reject'
        
        if not target_user_id or action not in ('approve', 'reject'):
            return Response({"error": "user_id and action ('approve'/'reject') are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            target_user = User.objects.get(id=target_user_id)
        except User.DoesNotExist:
            return Response({"error": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        target_group = get_user_group(target_user)
        target_profile = get_user_profile_by_user(target_user)

        if not target_profile or target_profile.status != 'pending':
            return Response({"error": "User is not in a pending state."}, status=status.HTTP_400_BAD_REQUEST)

        # Requester info
        requester = request.user
        req_group = get_user_group(requester)
        is_admin = is_saas_admin(requester) or req_group in ('Management', 'Administrator')
        is_hod = req_group == 'Department Head'
        
        hod_dept = None
        if is_hod:
            hod_profile = getattr(requester, 'department_head_profile', None)
            if hod_profile:
                hod_dept = hod_profile.department

        # Hierarchy Enforcement
        authorized = False
        
        if target_group == 'Department Head':
            # HOD needs from Admin
            if is_admin:
                authorized = True
        
        elif target_group == 'Faculty':
            # Faculty from HOD
            if is_hod and target_profile.department == hod_dept:
                authorized = True
            elif is_admin: # Admins can always override
                authorized = True
        
        elif target_group == 'Support Staff':
            # Support from Admin or HOD
            if is_admin:
                authorized = True
            elif is_hod and target_profile.department == hod_dept:
                authorized = True
        
        if not authorized:
            return Response(
                {"error": f"You do not have permission to {action} this '{target_group}' user."},
                status=status.HTTP_403_FORBIDDEN
            )

        # Perform Action
        if action == 'approve':
            target_profile.status = 'active'
            msg = f"User {target_user.username} has been approved."
        else:
            target_profile.status = 'rejected'
            msg = f"User {target_user.username} has been rejected."
        
        target_profile.save()
        return Response({"message": msg, "status": target_profile.status}, status=status.HTTP_200_OK)


class CollegeEmployeesListView(APIView):
    """
    List all non-student, non-superuser users in the current tenant schema.
    Only accessible by College Admins (Management or Administrator).
    """
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def get(self, request):
        from django.contrib.auth.models import User
        # Exclude students and superusers
        employees = User.objects.exclude(groups__name='student').exclude(is_superuser=True)
        data = []
        for e in employees:
            group_name = e.groups.first().name if e.groups.exists() else "No Role"
            data.append({
                "id": e.id,
                "username": e.username,
                "email": e.email,
                "first_name": e.first_name,
                "last_name": e.last_name,
                "role": group_name
            })
        return Response(data, status=status.HTTP_200_OK)


class UserPermissionsDetailView(APIView):
    """
    Retrieve or update direct permissions for a specific employee.
    Only accessible by College Admins.
    """
    permission_classes = [IsAuthenticated, IsCollegeAdmin]

    def get(self, request, user_id):
        from django.contrib.auth.models import User
        try:
            user = User.objects.exclude(groups__name='student').exclude(is_superuser=True).get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)

        # Get direct user permissions codenames
        direct_perms = list(user.user_permissions.values_list('codename', flat=True))
        return Response({"permissions": direct_perms}, status=status.HTTP_200_OK)

    def post(self, request, user_id):
        from django.contrib.auth.models import User, Permission
        try:
            user = User.objects.exclude(groups__name='student').exclude(is_superuser=True).get(id=user_id)
        except User.DoesNotExist:
            return Response({"error": "Employee not found."}, status=status.HTTP_404_NOT_FOUND)

        permissions_list = request.data.get('permissions', [])
        # Clear current direct permissions and assign new ones
        user.user_permissions.clear()
        for perm_codename in permissions_list:
            try:
                # Retrieve permission from database by codename
                perm = Permission.objects.get(codename=perm_codename)
                user.user_permissions.add(perm)
            except Permission.DoesNotExist:
                pass

        return Response({"message": "Permissions updated successfully."}, status=status.HTTP_200_OK)


class ActiveTenantSettingsView(APIView):
    """
    GET  /api/tenant/settings/       — Get active tenant details (College Admin / Management)
    PATCH /api/tenant/settings/      — Update active tenant details (logo, name, email, SMTP, ERP, etc.)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from django.db import connection
        tenant = getattr(connection, 'tenant', None)
        if not tenant or not getattr(tenant, 'pk', None) or tenant.schema_name == 'public':
            return Response({"error": "No tenant context found."}, status=status.HTTP_400_BAD_REQUEST)
        
        from tenants.serializers import TenantListSerializer
        serializer = TenantListSerializer(tenant)
        return Response(serializer.data)

    def patch(self, request):
        from django.db import connection
        user = request.user
        usergroup = get_user_group(user)
        if usergroup not in ['Management', 'Administrator']:
            return Response({"error": "Only college administrators can update settings."}, status=status.HTTP_403_FORBIDDEN)

        tenant = getattr(connection, 'tenant', None)
        if not tenant or not getattr(tenant, 'pk', None) or tenant.schema_name == 'public':
            return Response({"error": "No tenant context found."}, status=status.HTTP_400_BAD_REQUEST)

        from tenants.serializers import TenantUpdateSerializer
        serializer = TenantUpdateSerializer(tenant, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

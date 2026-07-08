# ── Standard Library Imports ──────────────────────────────────────────────────
import datetime
import math
import random
import uuid

# ── Django Core Imports ──────────────────────────────────────────────────────
from django.contrib.auth.models import User
from django.core.cache import cache
from django.core.mail import send_mail
from django.db import connection, transaction
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_exempt

# ── Third-Party Framework Imports ─────────────────────────────────────────────
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, permissions, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView

# ── Local App-Specific Imports ────────────────────────────────────────────────
from ..models.profile import (
    AdministratorProfile,
    DepartmentHeadProfile,
    ManagementProfile,
    NonTeachingStaffProfile,
    StudentProfile,
    TeachingStaffProfile,
)
from ..demo_guard import IsNotDemoTenant, demo_block_response, is_demo_tenant
from ..permissions import (
    CanCreateCollegeAdmin,
    DepartmentExistsForUserCreation,
    IsCollegeAdmin,
    IsFacultyOrAbove,
    IsNotStudent,
    IsSaaSAdmin,
    IsSaaSOrCollegeAdmin,
    get_user_group,
    is_college_admin,
    is_saas_admin,
)
from ..serializers import (
    LogoutSerializer,
    MyTokenObtainPairSerializer,
    UserRegistrationSerializer,
)
from ..utils import mask_sensitive_field


@method_decorator(csrf_exempt, name='dispatch')
class MyObtainTokenPairView(TokenObtainPairView):
    serializer_class = MyTokenObtainPairSerializer


class VerifyTokenView(APIView):
    permission_classes = [AllowAny]

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

        # Only auto-activate student profiles on verification; staff/faculty profiles
        # must remain 'pending' until explicitly approved by an Admin or HOD.
        user_group = get_user_group(user)
        if user_group == 'student':
            profile = get_user_profile_by_user(user)
            if profile:
                profile.status = 'active'
                profile.save()
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


class StudentOnboardRequestOTPView(APIView):
    """
    Onboarding: Request a 6-digit OTP for pre-created student accounts.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        # ── Auto-tenant routing by email domain ──
        if connection.schema_name == 'public':
            if '@' not in email:
                return Response({"error": "A valid email address is required."}, status=status.HTTP_400_BAD_REQUEST)
            email_domain = email.split('@')[-1]
            
            from tenants.models import Tenant
            target_tenant = Tenant.objects.filter(permitted_email_domain=email_domain).first()
            if not target_tenant:
                return Response(
                    {"error": f"No college registration is configured for the email domain '@{email_domain}'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            connection.set_tenant(target_tenant)

        # Verify that the user (with student role) exists in this tenant schema
        user = User.objects.filter(email=email).first()
        if not user or not hasattr(user, 'student_profile'):
            return Response(
                {"error": "This email is not pre-registered. Please contact your college administrator."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Generate 6-digit OTP
        otp_code = str(random.randint(100000, 999999))
        cache.set(f"onboard_otp_{email}", otp_code, timeout=600)

        # Send Email with HTML template
        try:
            from django.core.mail import EmailMultiAlternatives
            from django.template.loader import render_to_string

            context = {'otp_code': otp_code}
            html_content = render_to_string('emails/student_onboarding_otp.html', context)
            text_content = f"Welcome to CampusNexus. Your verification code is: {otp_code}"

            msg = EmailMultiAlternatives(
                subject="Verify your CampusNexus Account",
                body=text_content,
                from_email=None,  # Uses DEFAULT_FROM_EMAIL from settings
                to=[email]
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send()

            return Response({"message": "OTP sent successfully to your college email."}, status=status.HTTP_200_OK)
        except Exception as e:
            # Fallback to plain text if rendering/SMTP fails
            try:
                send_mail(
                    "Verify your CampusNexus Account",
                    f"Welcome to CampusNexus. Your verification code is: {otp_code}",
                    None,
                    [email]
                )
                return Response({"message": "OTP sent successfully to your college email (text fallback)."}, status=status.HTTP_200_OK)
            except Exception as ex:
                return Response(
                    {"error": f"Failed to send email. Please check configuration. Detail: {str(ex)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )


class StudentOnboardVerifyPasswordView(APIView):
    """
    Onboarding: Verify OTP, set new password, and log user in (returning JWT token).
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        otp_provided = request.data.get('otp', '').strip()
        password = request.data.get('password', '')
        confirm_password = request.data.get('confirm_password', '')

        if not email or not otp_provided:
            return Response({"error": "Email and OTP are required."}, status=status.HTTP_400_BAD_REQUEST)
        if not password or not confirm_password:
            return Response({"error": "Password and confirmation are required."}, status=status.HTTP_400_BAD_REQUEST)
        if password != confirm_password:
            return Response({"error": "Passwords do not match."}, status=status.HTTP_400_BAD_REQUEST)

        # ── Auto-tenant routing by email domain ──
        if connection.schema_name == 'public':
            if '@' not in email:
                return Response({"error": "A valid email address is required."}, status=status.HTTP_400_BAD_REQUEST)
            email_domain = email.split('@')[-1]
            
            from tenants.models import Tenant
            target_tenant = Tenant.objects.filter(permitted_email_domain=email_domain).first()
            if not target_tenant:
                return Response(
                    {"error": f"No college registration is configured for the email domain '@{email_domain}'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            connection.set_tenant(target_tenant)

        if is_demo_tenant():
            return demo_block_response()

        # Verify OTP
        cached_otp = cache.get(f"onboard_otp_{email}")
        if not cached_otp or cached_otp != otp_provided:
            return Response({"error": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)

        # Fetch student user
        user = User.objects.filter(email=email).first()
        if not user or not hasattr(user, 'student_profile'):
            return Response({"error": "Student profile not found."}, status=status.HTTP_404_NOT_FOUND)

        student_profile = user.student_profile

        # Update Password and Activate User
        user.set_password(password)
        user.is_active = True
        user.save()

        # Under DPDP Act: Update General Consent Flags during onboarding
        from django.utils import timezone
        student_profile.consent_given = True
        student_profile.consent_timestamp = timezone.now()
        student_profile.consent_version = 'v1.0'
        student_profile.save(update_fields=['consent_given', 'consent_timestamp', 'consent_version'])

        # Cleanup OTP cache
        cache.delete(f"onboard_otp_{email}")

        # Automatically log the student in and return JWT tokens for seamless access
        from rest_framework_simplejwt.tokens import RefreshToken
        refresh = RefreshToken.for_user(user)
        refresh['tenant_schema'] = connection.schema_name

        return Response({
            "message": "Onboarding completed successfully! Welcome to CampusNexus.",
            "access": str(refresh.access_token),
            "refresh": str(refresh),
            "email": user.email,
            "username": user.username,
            "role": "student"
        }, status=status.HTTP_200_OK)


class ForgotPasswordRequestOTPView(APIView):
    """
    Password Recovery: Step 1: Send a password reset OTP over college email.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        if not email:
            return Response({"error": "Email is required."}, status=status.HTTP_400_BAD_REQUEST)

        # ── Auto-tenant routing by email domain ──
        if connection.schema_name == 'public':
            if '@' not in email:
                return Response({"error": "A valid email address is required."}, status=status.HTTP_400_BAD_REQUEST)
            email_domain = email.split('@')[-1]
            
            from tenants.models import Tenant
            target_tenant = Tenant.objects.filter(permitted_email_domain=email_domain).first()
            if not target_tenant:
                return Response(
                    {"error": f"No college registration is configured for the email domain '@{email_domain}'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            connection.set_tenant(target_tenant)

        if is_demo_tenant():
            return demo_block_response()

        # Check if the user exists
        user = User.objects.filter(email=email).first()
        if not user:
            return Response(
                {"error": "No user account exists with this email address."},
                status=status.HTTP_404_NOT_FOUND
            )

        # Generate 6-digit OTP
        otp_code = str(random.randint(100000, 999999))
        cache.set(f"forgot_otp_{email}", otp_code, timeout=600)

        # Send Email
        try:
            from django.core.mail import EmailMultiAlternatives
            from django.template.loader import render_to_string

            context = {'otp_code': otp_code}
            html_content = render_to_string('emails/forgot_password_otp.html', context)
            text_content = f"CampusNexus Password Reset verification code: {otp_code}"

            msg = EmailMultiAlternatives(
                subject="Reset your CampusNexus Password",
                body=text_content,
                from_email=None,
                to=[email]
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send()

            return Response({"message": "Password reset OTP sent to your email."}, status=status.HTTP_200_OK)
        except Exception as e:
            try:
                send_mail(
                    "Reset your CampusNexus Password",
                    f"CampusNexus Password Reset verification code: {otp_code}",
                    None,
                    [email]
                )
                return Response({"message": "Password reset OTP sent to your email (fallback)."}, status=status.HTTP_200_OK)
            except Exception as ex:
                return Response(
                    {"error": f"Failed to send email. Detail: {str(ex)}"},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )


class ForgotPasswordVerifyOTPView(APIView):
    """
    Password Recovery: Step 2: Verify OTP and return a temporary single-use Reset Token.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        otp_provided = request.data.get('otp', '').strip()

        if not email or not otp_provided:
            return Response({"error": "Email and OTP are required."}, status=status.HTTP_400_BAD_REQUEST)

        # ── Auto-tenant routing by email domain ──
        if connection.schema_name == 'public':
            if '@' not in email:
                return Response({"error": "A valid email address is required."}, status=status.HTTP_400_BAD_REQUEST)
            email_domain = email.split('@')[-1]
            
            from tenants.models import Tenant
            target_tenant = Tenant.objects.filter(permitted_email_domain=email_domain).first()
            if not target_tenant:
                return Response(
                    {"error": f"No college registration is configured for the email domain '@{email_domain}'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            connection.set_tenant(target_tenant)

        if is_demo_tenant():
            return demo_block_response()

        # Check OTP
        cached_otp = cache.get(f"forgot_otp_{email}")
        if not cached_otp or cached_otp != otp_provided:
            return Response({"error": "Invalid or expired OTP."}, status=status.HTTP_400_BAD_REQUEST)

        # Generate a secure single-use reset token
        reset_token = uuid.uuid4().hex
        cache.set(f"reset_token_{email}", reset_token, timeout=600)
        cache.delete(f"forgot_otp_{email}")

        return Response({
            "message": "OTP verified successfully. You can now set your new password.",
            "reset_token": reset_token
        }, status=status.HTTP_200_OK)


class ForgotPasswordResetView(APIView):
    """
    Password Recovery: Step 3: Complete password reset using the token.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        reset_token = request.data.get('reset_token', '').strip()
        password = request.data.get('password', '')
        confirm_password = request.data.get('confirm_password', '')

        if not email or not reset_token or not password or not confirm_password:
            return Response({"error": "All parameters (email, reset_token, password, confirm_password) are required."}, status=status.HTTP_400_BAD_REQUEST)
        if password != confirm_password:
            return Response({"error": "Passwords do not match."}, status=status.HTTP_400_BAD_REQUEST)

        # ── Auto-tenant routing by email domain ──
        if connection.schema_name == 'public':
            if '@' not in email:
                return Response({"error": "A valid email address is required."}, status=status.HTTP_400_BAD_REQUEST)
            email_domain = email.split('@')[-1]
            
            from tenants.models import Tenant
            target_tenant = Tenant.objects.filter(permitted_email_domain=email_domain).first()
            if not target_tenant:
                return Response(
                    {"error": f"No college registration is configured for the email domain '@{email_domain}'."},
                    status=status.HTTP_400_BAD_REQUEST
                )
            connection.set_tenant(target_tenant)

        if is_demo_tenant():
            return demo_block_response()

        # Verify the reset token
        cached_token = cache.get(f"reset_token_{email}")
        if not cached_token or cached_token != reset_token:
            return Response({"error": "Invalid, expired, or compromised reset token."}, status=status.HTTP_400_BAD_REQUEST)

        # Get User
        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "User account not found."}, status=status.HTTP_404_NOT_FOUND)

        # Update Password
        user.set_password(password)
        user.save()

        # Cleanup token cache
        cache.delete(f"reset_token_{email}")

        return Response({"message": "Password reset completed successfully. You can now log in with your new password."}, status=status.HTTP_200_OK)



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

        if request.query_params.get('count_only') == 'true':
            return Response({"count": ManagementProfile.objects.count()}, status=status.HTTP_200_OK)

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

    def put(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group != 'Management':
            return Response({"detail": "You do not have permission to edit management profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        employee_id = request.data.get('id') or request.data.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = ManagementProfile.objects.filter(employee_id=employee_id).first()
            if not profile:
                profile = ManagementProfile.objects.get(id=employee_id)
        except (ManagementProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Management profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        profile_field_names = [
            'middle_name', 'date_of_birth', 'gender', 'aadhaar_number',
            'emergency_contact_name', 'emergency_contact_relationship', 'emergency_contact_phone',
            'contact_number', 'current_address_line1', 'current_address_line2',
            'current_city', 'current_district', 'current_state', 'current_pincode',
            'permanent_address_line1', 'permanent_address_line2', 'permanent_city',
            'permanent_district', 'permanent_state', 'permanent_pincode',
            'date_of_joining', 'designation', 'employee_type',
            'bank_account_number', 'pan_number', 'staff_role', 'status',
            'assigned_responsibilities', 'office_location_details'
        ]
        return helper_update_employee_profile(profile, request, profile_field_names)

    def delete(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group != 'Management':
            return Response({"detail": "You do not have permission to delete management profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        employee_id = request.query_params.get('id') or request.query_params.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = ManagementProfile.objects.filter(employee_id=employee_id).first()
            if not profile:
                profile = ManagementProfile.objects.get(id=employee_id)
        except (ManagementProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Management profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        return helper_delete_employee_profile(profile)


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

        if request.query_params.get('count_only') == 'true':
            return Response({"count": AdministratorProfile.objects.count()}, status=status.HTTP_200_OK)

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

    def put(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response({"detail": "You do not have permission to edit administrator profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        employee_id = request.data.get('id') or request.data.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = AdministratorProfile.objects.filter(employee_id=employee_id).first()
            if not profile:
                profile = AdministratorProfile.objects.get(id=employee_id)
        except (AdministratorProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Administrator profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        profile_field_names = [
            'middle_name', 'date_of_birth', 'gender', 'aadhaar_number',
            'emergency_contact_name', 'emergency_contact_relationship', 'emergency_contact_phone',
            'contact_number', 'current_address_line1', 'current_address_line2',
            'current_city', 'current_district', 'current_state', 'current_pincode',
            'permanent_address_line1', 'permanent_address_line2', 'permanent_city',
            'permanent_district', 'permanent_state', 'permanent_pincode',
            'date_of_joining', 'designation', 'employee_type',
            'bank_account_number', 'pan_number', 'staff_role', 'status',
            'assigned_responsibilities'
        ]
        return helper_update_employee_profile(profile, request, profile_field_names)

    def delete(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response({"detail": "You do not have permission to delete administrator profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        employee_id = request.query_params.get('id') or request.query_params.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = AdministratorProfile.objects.filter(employee_id=employee_id).first()
            if not profile:
                profile = AdministratorProfile.objects.get(id=employee_id)
        except (AdministratorProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Administrator profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        return helper_delete_employee_profile(profile)


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

        if request.query_params.get('count_only') == 'true':
            return Response({"count": TeachingStaffProfile.objects.count()}, status=status.HTTP_200_OK)

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

    def put(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response({"detail": "You do not have permission to edit teaching staff profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        employee_id = request.data.get('id') or request.data.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = TeachingStaffProfile.objects.filter(employee_id=employee_id).first()
            if not profile:
                profile = TeachingStaffProfile.objects.get(id=employee_id)
        except (TeachingStaffProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Faculty profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        profile_field_names = [
            'middle_name', 'date_of_birth', 'gender', 'blood_group', 'aadhaar_number', 'nationality',
            'emergency_contact_name', 'emergency_contact_relationship', 'emergency_contact_phone',
            'contact_number', 'alternate_phone_number', 'current_address_line1', 'current_address_line2',
            'current_city', 'current_district', 'current_state', 'current_pincode',
            'permanent_address_line1', 'permanent_address_line2', 'permanent_city',
            'permanent_district', 'permanent_state', 'permanent_pincode',
            'date_of_joining', 'designation', 'qualifications', 'specializations',
            'experience_years', 'employee_type', 'bank_account_number', 'pan_number',
            'epf_esi_details', 'staff_role', 'status', 'office_room_number',
            'research_interests', 'publications_link', 'replacement_availability_preferences'
        ]
        return helper_update_employee_profile(profile, request, profile_field_names)

    def delete(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response({"detail": "You do not have permission to delete teaching staff profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        employee_id = request.query_params.get('id') or request.query_params.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = TeachingStaffProfile.objects.filter(employee_id=employee_id).first()
            if not profile:
                profile = TeachingStaffProfile.objects.get(id=employee_id)
        except (TeachingStaffProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Faculty profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        return helper_delete_employee_profile(profile)


class StudentUserProfileView(APIView):
    """
    View all Student profiles.
    Students cannot list other students — only Faculty and above can.
    """
    permission_classes = [IsAuthenticated, IsFacultyOrAbove]

    def get(self, request):
        if request.query_params.get('count_only') == 'true':
            return Response({"count": StudentProfile.objects.count()}, status=status.HTTP_200_OK)

        student_profiles = StudentProfile.objects.all().select_related('user', 'department')
        
        user = request.user
        is_admin = is_saas_admin(user) or get_user_group(user) in ('Management', 'Administrator')

        search_query = request.query_params.get('search')
        if search_query:
            from django.db.models import Q
            student_profiles = student_profiles.filter(
                Q(student_id__icontains=search_query) |
                Q(user__username__icontains=search_query) |
                Q(user__first_name__icontains=search_query) |
                Q(user__last_name__icontains=search_query) |
                Q(user__email__icontains=search_query) |
                Q(department__name__icontains=search_query) |
                Q(contact_number__icontains=search_query)
            )

        # Get pagination parameters
        page = request.query_params.get('page')
        page_size = request.query_params.get('page_size')

        total_count = student_profiles.count()

        try:
            page = int(page) if page else 1
            page_size = int(page_size) if page_size else 10
        except ValueError:
            page = 1
            page_size = 10
        
        start = (page - 1) * page_size
        end = start + page_size
        student_profiles = student_profiles[start:end]

        result = []
        for stud in student_profiles:
            result.append({
                "id": stud.id,
                "user": {
                    "username": stud.user.username, "email": stud.user.email,
                    "first_name": stud.user.first_name, "last_name": stud.user.last_name
                },
                "role": "Student",
                "student_id": stud.student_id,
                "department": stud.department.name if stud.department else None,
                "department_id": stud.department.id if stud.department else None,
                "middle_name": stud.middle_name, "date_of_birth": stud.date_of_birth,
                "gender": stud.gender, "blood_group": stud.blood_group,
                "aadhaar_number": stud.aadhaar_number if is_admin else mask_sensitive_field(stud.aadhaar_number), "nationality": stud.nationality,
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
        return Response({
            "total_count": total_count,
            "page": page,
            "page_size": page_size,
            "results": result
        }, status=status.HTTP_200_OK)

    def put(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group not in ('Management', 'Administrator', 'Department Head'):
            return Response({"detail": "You do not have permission to edit student profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        student_id = request.data.get('id') or request.data.get('student_id')
        if not student_id:
            return Response({"error": "Student profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = StudentProfile.objects.filter(student_id=student_id).first()
            if not profile:
                profile = StudentProfile.objects.get(id=student_id)
        except (StudentProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Student profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        if group == 'Department Head' and not is_saas_admin(user):
            hod_profile = getattr(user, 'departmenthead_profile', None)
            if not hod_profile or hod_profile.department != profile.department:
                return Response({"detail": "You can only edit student profiles from your own department."}, status=status.HTTP_403_FORBIDDEN)

        user_data = request.data.get('user', {})
        django_user = profile.user

        new_email = user_data.get('email')
        new_username = user_data.get('username')
        identity_changing = (new_email and new_email != django_user.email) or \
            (new_username and new_username != django_user.username)
        if identity_changing and is_demo_tenant():
            return demo_block_response()

        if new_email and new_email != django_user.email:
            if User.objects.filter(email=new_email).exclude(id=django_user.id).exists():
                return Response({"error": "A user with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)
            django_user.email = new_email

        if new_username and new_username != django_user.username:
            if User.objects.filter(username=new_username).exclude(id=django_user.id).exists():
                return Response({"error": "A user with this username already exists."}, status=status.HTTP_400_BAD_REQUEST)
            django_user.username = new_username
            
        if 'first_name' in user_data:
            django_user.first_name = user_data['first_name']
        if 'last_name' in user_data:
            django_user.last_name = user_data['last_name']

        # Synchronize Django User is_active status with frontend edits
        if 'is_active' in user_data:
            is_act = user_data['is_active']
            django_user.is_active = (is_act.lower() == 'true') if isinstance(is_act, str) else bool(is_act)
        elif 'is_active' in request.data:
            is_act = request.data['is_active']
            django_user.is_active = (is_act.lower() == 'true') if isinstance(is_act, str) else bool(is_act)
        elif 'status' in request.data:
            django_user.is_active = (request.data['status'].lower() == 'active')

        django_user.save()

        profile_field_names = [
            'middle_name', 'contact_number', 'date_of_birth', 'gender', 'blood_group',
            'aadhaar_number', 'nationality', 'emergency_contact_name',
            'emergency_contact_relationship', 'emergency_contact_phone', 'alternate_phone_number',
            'current_address_line1', 'current_address_line2', 'current_city',
            'current_district', 'current_state', 'current_pincode',
            'permanent_address_line1', 'permanent_address_line2', 'permanent_city',
            'permanent_district', 'permanent_state', 'permanent_pincode',
            'religion', 'category', 'disability_status', 'disability_details',
            'admission_date', 'admission_number', 'batch_academic_year', 'current_semester_year',
            'section_division', 'previous_school_college', 'tenth_marksheet_percentage',
            'twelfth_marksheet_percentage', 'biometric_id', 'hostel_transport_details',
            'scholarship_fee_concession_details', 'medical_conditions_allergies',
            'extracurricular_interests', 'status'
        ]
        
        for field in profile_field_names:
            if field in request.data:
                val = request.data[field]
                # Parse frontend string values for boolean and nullable fields
                if field == 'disability_status' and isinstance(val, str):
                    if val.lower() == 'true':
                        val = True
                    elif val.lower() == 'false':
                        val = False
                    elif val.lower() in ('none', 'null', ''):
                        val = None
                elif field in ('date_of_birth', 'admission_date') and val in ('', 'null', 'None'):
                    val = None
                elif field in ('tenth_marksheet_percentage', 'twelfth_marksheet_percentage') and val in ('', 'null', 'None'):
                    val = None
                setattr(profile, field, val)
                
        dept_id = request.data.get('department_id')
        if dept_id:
            from ..models.department import Department
            try:
                profile.department = Department.objects.get(id=dept_id)
            except Department.DoesNotExist:
                return Response({"error": "Department not found."}, status=status.HTTP_400_BAD_REQUEST)
                
        profile.save()
        return Response({"message": "Student profile updated successfully."}, status=status.HTTP_200_OK)

    def delete(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response({"detail": "You do not have permission to delete student profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        student_id = request.query_params.get('id') or request.query_params.get('student_id')
        if not student_id:
            return Response({"error": "Student profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = StudentProfile.objects.filter(student_id=student_id).first()
            if not profile:
                profile = StudentProfile.objects.get(id=student_id)
        except (StudentProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Student profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        django_user = profile.user
        django_user.delete()
        
        return Response({"message": "Student profile deleted successfully."}, status=status.HTTP_200_OK)


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

        if request.query_params.get('count_only') == 'true':
            return Response({"count": DepartmentHeadProfile.objects.count()}, status=status.HTTP_200_OK)

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

    def put(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response({"detail": "You do not have permission to edit department head profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        employee_id = request.data.get('id') or request.data.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = DepartmentHeadProfile.objects.filter(employee_id=employee_id).first()
            if not profile:
                profile = DepartmentHeadProfile.objects.get(id=employee_id)
        except (DepartmentHeadProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Department Head profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        profile_field_names = [
            'middle_name', 'date_of_birth', 'gender', 'aadhaar_number',
            'emergency_contact_name', 'emergency_contact_relationship', 'emergency_contact_phone',
            'contact_number', 'current_address_line1', 'current_address_line2',
            'current_city', 'current_district', 'current_state', 'current_pincode',
            'permanent_address_line1', 'permanent_address_line2', 'permanent_city',
            'permanent_district', 'permanent_state', 'permanent_pincode',
            'date_of_joining', 'designation', 'employee_type',
            'bank_account_number', 'pan_number', 'staff_role', 'status'
        ]
        return helper_update_employee_profile(profile, request, profile_field_names)

    def delete(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response({"detail": "You do not have permission to delete department head profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        employee_id = request.query_params.get('id') or request.query_params.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = DepartmentHeadProfile.objects.filter(employee_id=employee_id).first()
            if not profile:
                profile = DepartmentHeadProfile.objects.get(id=employee_id)
        except (DepartmentHeadProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Department Head profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        return helper_delete_employee_profile(profile)


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

        if request.query_params.get('count_only') == 'true':
            return Response({"count": NonTeachingStaffProfile.objects.count()}, status=status.HTTP_200_OK)

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

    def put(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response({"detail": "You do not have permission to edit support staff profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        employee_id = request.data.get('id') or request.data.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = NonTeachingStaffProfile.objects.filter(employee_id=employee_id).first()
            if not profile:
                profile = NonTeachingStaffProfile.objects.get(id=employee_id)
        except (NonTeachingStaffProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Support Staff profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        profile_field_names = [
            'middle_name', 'date_of_birth', 'gender', 'aadhaar_number',
            'emergency_contact_name', 'emergency_contact_relationship', 'emergency_contact_phone',
            'contact_number', 'current_address_line1', 'current_address_line2',
            'current_city', 'current_district', 'current_state', 'current_pincode',
            'permanent_address_line1', 'permanent_address_line2', 'permanent_city',
            'permanent_district', 'permanent_state', 'permanent_pincode',
            'date_of_joining', 'designation', 'employee_type',
            'bank_account_number', 'pan_number', 'staff_role', 'status',
            'assigned_responsibilities'
        ]
        return helper_update_employee_profile(profile, request, profile_field_names)

    def delete(self, request):
        user = request.user
        group = get_user_group(user)
        if not is_saas_admin(user) and group not in ('Management', 'Administrator'):
            return Response({"detail": "You do not have permission to delete support staff profiles."}, status=status.HTTP_403_FORBIDDEN)
            
        employee_id = request.query_params.get('id') or request.query_params.get('employee_id')
        if not employee_id:
            return Response({"error": "Employee profile id is required."}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            profile = NonTeachingStaffProfile.objects.filter(employee_id=employee_id).first()
            if not profile:
                profile = NonTeachingStaffProfile.objects.get(id=employee_id)
        except (NonTeachingStaffProfile.DoesNotExist, ValueError, TypeError):
            return Response({"error": "Support Staff profile not found."}, status=status.HTTP_404_NOT_FOUND)
            
        return helper_delete_employee_profile(profile)


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
                "aadhaar_number": mask_sensitive_field(profile.aadhaar_number), "nationality": profile.nationality,
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
                "bank_account_number": mask_sensitive_field(profile.bank_account_number), "pan_number": mask_sensitive_field(profile.pan_number),
                "epf_esi_details": profile.epf_esi_details, "staff_role": profile.staff_role, "status": profile.status,
                "profile_picture": profile.profile_picture.url if profile.profile_picture else None,
                "office_room_number": profile.office_room_number, "research_interests": profile.research_interests,
                "publications_link": profile.publications_link,
                "replacement_availability_preferences": profile.replacement_availability_preferences,
            }
            # Mask Aadhaar on profile_data
            profile_data["aadhaar_number"] = mask_sensitive_field(profile.aadhaar_number)

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
                "employee_type": profile.employee_type, "bank_account_number": mask_sensitive_field(profile.bank_account_number),
                "pan_number": mask_sensitive_field(profile.pan_number), "staff_role": profile.staff_role, "status": profile.status,
                "profile_picture": profile.profile_picture.url if profile.profile_picture else None,
                "assigned_responsibilities": profile.assigned_responsibilities,
            }
            # Mask Aadhaar
            profile_data["aadhaar_number"] = mask_sensitive_field(profile.aadhaar_number)

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
                "employee_type": profile.employee_type, "bank_account_number": mask_sensitive_field(profile.bank_account_number),
                "pan_number": mask_sensitive_field(profile.pan_number), "staff_role": profile.staff_role, "status": profile.status,
                "profile_picture": profile.profile_picture.url if profile.profile_picture else None,
                "assigned_responsibilities": profile.assigned_responsibilities,
            }
            # Mask Aadhaar
            profile_data["aadhaar_number"] = mask_sensitive_field(profile.aadhaar_number)

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
                "employee_type": profile.employee_type, "bank_account_number": mask_sensitive_field(profile.bank_account_number),
                "pan_number": mask_sensitive_field(profile.pan_number), "staff_role": profile.staff_role, "status": profile.status,
                "profile_picture": profile.profile_picture.url if profile.profile_picture else None,
            }
            # Mask Aadhaar
            profile_data["aadhaar_number"] = mask_sensitive_field(profile.aadhaar_number)

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

        # Retrieve consent status from local profile variables safely
        try:
            profile_obj = locals().get('profile', None)
            if profile_obj and hasattr(profile_obj, 'consent_given'):
                profile_data["consent_given"] = profile_obj.consent_given
            else:
                profile_data["consent_given"] = True
        except Exception:
            profile_data["consent_given"] = True

        profile_data["tenant_logo"] = tenant_logo
        return Response(profile_data, status=status.HTTP_200_OK)

    def put(self, request):
        user = request.user
        profile = get_user_profile_by_user(user)
        
        if not profile and not is_saas_admin(user):
            return Response({"detail": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)

        if profile:
            contact_number = request.data.get('contact_number')
            if contact_number is not None:
                profile.contact_number = contact_number
                
            alternate_phone_number = request.data.get('alternate_phone_number')
            if alternate_phone_number is not None and hasattr(profile, 'alternate_phone_number'):
                profile.alternate_phone_number = alternate_phone_number
                
            profile.save()

        user_data = request.data.get('user', {})
        if isinstance(user_data, dict):
            first_name = user_data.get('first_name')
            if first_name is not None:
                user.first_name = first_name
            last_name = user_data.get('last_name')
            if last_name is not None:
                user.last_name = last_name
            user.save()

        return Response({"message": "Profile updated successfully."}, status=status.HTTP_200_OK)



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

def helper_update_employee_profile(profile, request, profile_field_names):
    user_data = request.data.get('user', {})
    django_user = profile.user

    new_email = user_data.get('email')
    new_username = user_data.get('username')
    identity_changing = (new_email and new_email != django_user.email) or \
        (new_username and new_username != django_user.username)
    if identity_changing and is_demo_tenant():
        return demo_block_response()

    if new_email and new_email != django_user.email:
        if User.objects.filter(email=new_email).exclude(id=django_user.id).exists():
            return Response({"error": "A user with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)
        django_user.email = new_email

    if new_username and new_username != django_user.username:
        if User.objects.filter(username=new_username).exclude(id=django_user.id).exists():
            return Response({"error": "A user with this username already exists."}, status=status.HTTP_400_BAD_REQUEST)
        django_user.username = new_username
        
    if 'first_name' in user_data:
        django_user.first_name = user_data['first_name']
    if 'last_name' in user_data:
        django_user.last_name = user_data['last_name']

    if 'is_active' in user_data:
        is_act = user_data['is_active']
        django_user.is_active = (is_act.lower() == 'true') if isinstance(is_act, str) else bool(is_act)
    elif 'is_active' in request.data:
        is_act = request.data['is_active']
        django_user.is_active = (is_act.lower() == 'true') if isinstance(is_act, str) else bool(is_act)
    elif 'status' in request.data:
        django_user.is_active = (request.data['status'].lower() == 'active')

    django_user.save()

    for field in profile_field_names:
        if field in request.data:
            val = request.data[field]
            if field in ('date_of_birth', 'date_of_joining') and val in ('', 'null', 'None'):
                val = None
            elif field == 'experience_years' and val in ('', 'null', 'None'):
                val = None
            setattr(profile, field, val)

    dept_id = request.data.get('department_id')
    if dept_id and hasattr(profile, 'department'):
        from ..models.department import Department
        try:
            profile.department = Department.objects.get(id=dept_id)
        except Department.DoesNotExist:
            return Response({"error": "Department not found."}, status=status.HTTP_400_BAD_REQUEST)

    profile.save()
    return Response({"message": f"{profile.__class__.__name__} updated successfully."}, status=status.HTTP_200_OK)

def helper_delete_employee_profile(profile):
    django_user = profile.user
    django_user.delete()
    return Response({"message": f"{profile.__class__.__name__} deleted successfully."}, status=status.HTTP_200_OK)


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
            target_user.is_active = True
            msg = f"User {target_user.username} has been approved."
        else:
            target_profile.status = 'rejected'
            target_user.is_active = False
            msg = f"User {target_user.username} has been rejected."
        
        target_user.save()
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
        # prefetch_related avoids one extra groups query per employee (N+1)
        employees = User.objects.exclude(groups__name='student').exclude(is_superuser=True).prefetch_related('groups')
        data = []
        for e in employees:
            employee_groups = e.groups.all()
            group_name = employee_groups[0].name if employee_groups else "No Role"
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

    Restricted to College Admins: this payload includes SMTP and ERP credentials
    (email_smtp_password, erp_auth_token), which must not be exposed to Faculty/Students.
    """
    permission_classes = [IsAuthenticated, IsCollegeAdmin, IsNotDemoTenant]

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
        tenant = getattr(connection, 'tenant', None)
        if not tenant or not getattr(tenant, 'pk', None) or tenant.schema_name == 'public':
            return Response({"error": "No tenant context found."}, status=status.HTTP_400_BAD_REQUEST)

        from tenants.serializers import TenantUpdateSerializer
        serializer = TenantUpdateSerializer(tenant, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GuardianConsentApprovalView(APIView):
    """
    Public endpoint for parent/guardian consent approval of minor registrations.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        email = request.data.get('email', '').strip().lower()
        student_id = request.data.get('student_id', '').strip()
        guardian_email = request.data.get('guardian_email', '').strip().lower()
        action = request.data.get('action', 'approve').strip().lower()

        if not email or not student_id or not guardian_email:
            return Response({"error": "email, student_id, and guardian_email are required."}, status=status.HTTP_400_BAD_REQUEST)

        # ── Auto-tenant routing by student email domain ──
        if connection.schema_name == 'public':
            email_domain = email.split('@')[-1]
            from tenants.models import Tenant
            target_tenant = Tenant.objects.filter(permitted_email_domain=email_domain).first()
            if target_tenant:
                connection.set_tenant(target_tenant)

        profile = StudentProfile.objects.filter(
            user__email=email,
            student_id=student_id,
            parent_guardian_email=guardian_email
        ).first()

        if not profile:
            return Response({"error": "No student profile found with the provided details."}, status=status.HTTP_404_NOT_FOUND)

        if profile.status != 'pending_guardian':
            return Response({"error": f"Student registration status is '{profile.status}', not pending guardian consent."}, status=status.HTTP_400_BAD_REQUEST)

        if action == 'approve':
            profile.guardian_consent_given = True
            profile.status = 'active'
            profile.save()
            
            # Record in AuditLog
            from ..models.audit import AuditLog
            AuditLog.objects.create(
                user=None,
                action='UPDATE',
                model_name='StudentProfile',
                object_id=str(profile.pk),
                object_repr=f"Guardian approved consent for {profile.user.username}",
                changes={"status": {"old": "pending_guardian", "new": "active"}, "guardian_consent_given": {"old": False, "new": True}},
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                endpoint=request.path[:500]
            )
            return Response({"message": "Guardian consent successfully verified. Student account is now active."}, status=status.HTTP_200_OK)
        else:
            profile.status = 'rejected'
            profile.save()
            return Response({"message": "Student registration rejected by guardian."}, status=status.HTTP_200_OK)


class UserDataErasureView(APIView):
    """
    Scrubs all user PII data, deletes biometric face templates, and deactivates the user account
    in compliance with Section 12 (Right to Erasure) of the DPDP Act, 2023.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        group = get_user_group(user)
        profile = get_user_profile_by_user(user)

        if not profile:
            return Response({"error": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)

        # 1. Delete biometric face templates (if student)
        if group == 'student':
            from ..models.face_embedding import FaceEmbedding
            embeddings = FaceEmbedding.objects.filter(student=profile)
            for emb in embeddings:
                if emb.image:
                    try:
                        emb.image.delete(save=False)
                    except Exception:
                        pass
                emb.delete()
            
            # Nullify student PII
            profile.aadhaar_number = None
            profile.middle_name = None
            profile.contact_number = None
            profile.alternate_phone_number = None
            profile.current_address_line1 = None
            profile.current_address_line2 = None
            profile.permanent_address_line1 = None
            profile.permanent_address_line2 = None
            profile.parent_guardian_name = None
            profile.parent_guardian_email = None
            profile.medical_conditions_allergies = None
            profile.status = 'deleted'
            profile.save()

        elif group == 'Faculty':
            profile.aadhaar_number = None
            profile.pan_number = None
            profile.bank_account_number = None
            profile.contact_number = None
            profile.alternate_phone_number = None
            profile.current_address_line1 = None
            profile.current_address_line2 = None
            profile.permanent_address_line1 = None
            profile.permanent_address_line2 = None
            profile.status = 'deleted'
            profile.save()

        elif group in ('Support Staff', 'Management', 'Administrator', 'Department Head'):
            profile.aadhaar_number = None
            profile.pan_number = None
            profile.bank_account_number = None
            profile.contact_number = None
            profile.current_address_line1 = None
            profile.permanent_address_line1 = None
            profile.status = 'deleted'
            profile.save()

        # 2. Deactivate Django auth user
        user.email = f"deleted_{user.id}@campusflow.invalid"
        user.first_name = "Deleted"
        user.last_name = "User"
        user.is_active = False
        user.save()

        # Record in AuditLog
        from ..models.audit import AuditLog
        AuditLog.objects.create(
            user=None,
            action='DELETE',
            model_name='User',
            object_id=str(user.id),
            object_repr=f"User requested data erasure (DPDP Compliance)",
            changes={"is_active": {"old": True, "new": False}, "status": {"old": "active", "new": "deleted"}},
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            endpoint=request.path[:500]
        )

        return Response({"message": "Your personal data has been successfully erased, and your account has been deactivated in compliance with DPDP Act, 2023."}, status=status.HTTP_200_OK)


class UserWithdrawConsentView(APIView):
    """
    Allows a user to withdraw consent under Section 6 of the DPDP Act.
    This locks the account and sets status to pending until consent is re-granted.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        profile = get_user_profile_by_user(user)

        if not profile:
            return Response({"error": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)

        profile.consent_given = False
        profile.consent_timestamp = None
        profile.status = 'pending'
        profile.save()

        from ..models.audit import AuditLog
        AuditLog.objects.create(
            user=user,
            action='UPDATE',
            model_name=profile.__class__.__name__,
            object_id=str(profile.pk),
            object_repr=f"User withdrew privacy consent",
            changes={"consent_given": {"old": True, "new": False}, "status": {"old": "active", "new": "pending"}},
            ip_address=request.META.get('REMOTE_ADDR'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
            endpoint=request.path[:500]
        )

        return Response({"message": "Consent successfully withdrawn. Your account has been locked."}, status=status.HTTP_200_OK)


class UserGrantConsentView(APIView):
    """
    Allows a user to grant data privacy consent under the DPDP Act.
    If the account was locked (pending status) due to consent withdrawal,
    this re-activates it.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        profile = get_user_profile_by_user(user)

        if not profile:
            return Response({"error": "Profile not found."}, status=status.HTTP_404_NOT_FOUND)

        if not getattr(profile, 'consent_given', False):
            profile.consent_given = True
            from django.utils import timezone
            profile.consent_timestamp = timezone.now()
            profile.consent_version = 'v1.0'
            
            # Re-activate user status if pending
            if getattr(profile, 'status', None) == 'pending':
                profile.status = 'active'
                
            profile.save()

            from ..models.audit import AuditLog
            AuditLog.objects.create(
                user=user,
                action='UPDATE',
                model_name=profile.__class__.__name__,
                object_id=str(profile.pk),
                object_repr="User granted privacy consent",
                changes={"consent_given": {"old": False, "new": True}, "status": {"old": "pending", "new": "active"}},
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
                endpoint=request.path[:500]
            )
            return Response({"message": "Consent successfully registered and account activated."}, status=status.HTTP_200_OK)
        
        return Response({"message": "Consent already given."}, status=status.HTTP_200_OK)

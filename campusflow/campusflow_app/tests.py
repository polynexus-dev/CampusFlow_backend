from django.contrib.auth.models import User, Group
from django.urls import reverse
from rest_framework import status
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from .models.profile import StudentProfile
from .models.department import Department
from rest_framework_simplejwt.tokens import RefreshToken
import datetime
from django.core.cache import cache

class DictCache:
    def __init__(self):
        self.data = {}
    def get(self, key, default=None):
        return self.data.get(key, default)
    def set(self, key, value, timeout=None):
        self.data[key] = value
    def delete(self, key):
        self.data.pop(key, None)

class DPDPComplianceTests(TenantTestCase):
    def setUp(self):
        super().setUp()
        from unittest.mock import patch
        self.cache_patcher = patch('campusflow_app.views.users.cache')
        self.mock_cache = self.cache_patcher.start()
        self.dict_cache = DictCache()
        self.mock_cache.get.side_effect = self.dict_cache.get
        self.mock_cache.set.side_effect = self.dict_cache.set
        self.mock_cache.delete.side_effect = self.dict_cache.delete

        self.tenant.permitted_email_domain = 'test.com'
        self.tenant.save()
        
        with schema_context(self.tenant.schema_name):
            Group.objects.get_or_create(name='student')
            self.dept = Department.objects.create(name="Computer Science", code="CS")

    def tearDown(self):
        self.cache_patcher.stop()
        super().tearDown()

    def test_student_registration_requires_consent(self):
        url = reverse('student_registration')
        with schema_context(self.tenant.schema_name):
            dept_id = self.dept.id
        data = {
            'username': 'teststudent1',
            'email': 'student1@test.com',
            'password': 'Password123',
            'password2': 'Password123',
            'role': 'student',
            'student_id': 'STU999',
            'program_enrolled_in_id': 'BTech',
            'department_id': dept_id,
            'date_of_birth': '2005-01-01',
            'consent_given': False,
        }
        response = self.client.post(url, data, format='json')
        if response.status_code != status.HTTP_400_BAD_REQUEST:
            print("FAILED consent test:", response.status_code, response.data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('consent_given', response.data)

    def test_student_registration_minor_requires_guardian(self):
        url = reverse('student_registration')
        with schema_context(self.tenant.schema_name):
            dept_id = self.dept.id
        data = {
            'username': 'minorstudent',
            'email': 'minor@test.com',
            'password': 'Password123',
            'password2': 'Password123',
            'role': 'student',
            'student_id': 'STU998',
            'program_enrolled_in_id': 'BTech',
            'department_id': dept_id,
            'date_of_birth': '2012-01-01',
            'consent_given': True,
        }
        response = self.client.post(url, data, format='json')
        if response.status_code != status.HTTP_400_BAD_REQUEST:
            print("FAILED minor requires guardian test:", response.status_code, response.data)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('parent_guardian_name', response.data)

    def test_student_registration_minor_success(self):
        url = reverse('student_registration')
        with schema_context(self.tenant.schema_name):
            dept_id = self.dept.id
        data = {
            'username': 'minorstudent2',
            'email': 'minor2@test.com',
            'password': 'Password123',
            'password2': 'Password123',
            'role': 'student',
            'student_id': 'STU997',
            'program_enrolled_in_id': 'BTech',
            'department_id': dept_id,
            'date_of_birth': '2012-01-01',
            'consent_given': True,
            'parent_guardian_name': 'John Doe',
            'parent_guardian_email': 'johndoe@test.com',
        }
        response = self.client.post(url, data, format='json')
        if response.status_code != status.HTTP_201_CREATED:
            print("FAILED minor success test:", response.status_code, response.data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        with schema_context(self.tenant.schema_name):
            profile = StudentProfile.objects.get(student_id='STU997')
            self.assertEqual(profile.status, 'pending_guardian')
            self.assertFalse(profile.guardian_consent_given)

    def test_student_registration_adult_success(self):
        url = reverse('student_registration')
        with schema_context(self.tenant.schema_name):
            dept_id = self.dept.id
        data = {
            'username': 'adultstudent',
            'email': 'adult@test.com',
            'password': 'Password123',
            'password2': 'Password123',
            'role': 'student',
            'student_id': 'STU996',
            'program_enrolled_in_id': 'BTech',
            'department_id': dept_id,
            'date_of_birth': '2000-01-01',
            'consent_given': True,
        }
        response = self.client.post(url, data, format='json')
        if response.status_code != status.HTTP_201_CREATED:
            print("FAILED adult success test:", response.status_code, response.data)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        with schema_context(self.tenant.schema_name):
            profile = StudentProfile.objects.get(student_id='STU996')
            self.assertEqual(profile.status, 'active')

    def test_guardian_consent_approval(self):
        with schema_context(self.tenant.schema_name):
            student_user = User.objects.create_user(
                username='minorstu3', email='minor3@test.com', password='Password123'
            )
            profile = StudentProfile.objects.create(
                user=student_user,
                student_id='STU995',
                department=self.dept,
                date_of_birth=datetime.date(2012, 1, 1),
                consent_given=True,
                parent_guardian_name='Jane Doe',
                parent_guardian_email='janedoe@test.com',
                status='pending_guardian'
            )

        url = reverse('guardian_consent')
        data = {
            'email': 'minor3@test.com',
            'student_id': 'STU995',
            'guardian_email': 'janedoe@test.com',
            'action': 'approve',
        }
        response = self.client.post(url, data, format='json')
        if response.status_code != status.HTTP_200_OK:
            print("FAILED guardian consent approval:", response.status_code, response.data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        with schema_context(self.tenant.schema_name):
            profile.refresh_from_db()
            self.assertEqual(profile.status, 'active')
            self.assertTrue(profile.guardian_consent_given)

    def test_profile_masking(self):
        with schema_context(self.tenant.schema_name):
            student_user = User.objects.create_user(
                username='stu_mask_test', email='masktest@test.com', password='Password123'
            )
            # Assign student group
            student_user.groups.add(Group.objects.get(name='student'))
            profile = StudentProfile.objects.create(
                user=student_user,
                student_id='STU994',
                department=self.dept,
                aadhaar_number='123456789012',
                status='active'
            )
            token = RefreshToken.for_user(student_user)
            token['tenant_schema'] = self.tenant.schema_name

        url = reverse('user_profile')
        response = self.client.get(
            url, 
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
            format='json'
        )
        if response.status_code != status.HTTP_200_OK:
            print("FAILED profile masking:", response.status_code, response.data)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['aadhaar_number'], '********9012')

    def test_face_registration_requires_consent(self):
        with schema_context(self.tenant.schema_name):
            student_user = User.objects.create_user(
                username='stu_face_test', email='facetest@test.com', password='Password123'
            )
            student_user.groups.add(Group.objects.get(name='student'))
            profile = StudentProfile.objects.create(
                user=student_user,
                student_id='STU993',
                department=self.dept,
                status='active'
            )
            token = RefreshToken.for_user(student_user)
            token['tenant_schema'] = self.tenant.schema_name

        url = reverse('register-face')
        data = {
            'front': 'dummy',
            'left': 'dummy',
            'right': 'dummy',
        }
        response = self.client.post(
            url,
            data,
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Biometric consent is required', response.data['error'])

    def test_forgot_password_flow(self):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username='forgot_user', email='forgot@test.com', password='OldPassword123'
            )

        # Step 1: Request OTP
        url_req = reverse('forgot_password_request_otp')
        response_req = self.client.post(url_req, {'email': 'forgot@test.com'}, format='json')
        self.assertEqual(response_req.status_code, status.HTTP_200_OK)

        # Retrieve cached OTP
        otp_code = self.dict_cache.get("forgot_otp_forgot@test.com")
        self.assertIsNotNone(otp_code)

        # Step 2: Verify OTP
        url_ver = reverse('forgot_password_verify_otp')
        response_ver = self.client.post(url_ver, {'email': 'forgot@test.com', 'otp': otp_code}, format='json')
        self.assertEqual(response_ver.status_code, status.HTTP_200_OK)
        reset_token = response_ver.data['reset_token']
        self.assertIsNotNone(reset_token)

        # Step 3: Reset Password
        url_reset = reverse('forgot_password_reset')
        reset_data = {
            'email': 'forgot@test.com',
            'reset_token': reset_token,
            'password': 'NewPassword123!',
            'confirm_password': 'NewPassword123!'
        }
        response_reset = self.client.post(url_reset, reset_data, format='json')
        self.assertEqual(response_reset.status_code, status.HTTP_200_OK)

        # Verify password is changed
        with schema_context(self.tenant.schema_name):
            db_user = User.objects.get(email='forgot@test.com')
            self.assertTrue(db_user.check_password('NewPassword123!'))



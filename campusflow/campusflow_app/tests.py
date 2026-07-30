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

    def test_user_profile_put_update(self):
        with schema_context(self.tenant.schema_name):
            student_user = User.objects.create_user(
                username='stu_update_test', email='updatetest@test.com', password='Password123'
            )
            student_user.groups.add(Group.objects.get(name='student'))
            profile = StudentProfile.objects.create(
                user=student_user,
                student_id='STU992',
                department=self.dept,
                contact_number='1234567890',
                status='active'
            )
            token = RefreshToken.for_user(student_user)
            token['tenant_schema'] = self.tenant.schema_name

        url = reverse('user_profile')
        
        # Test PUT updating contact_number
        data = {
            'contact_number': '0987654321',
            'user': {
                'first_name': 'UpdatedFirst',
                'last_name': 'UpdatedLast'
            }
        }
        import json
        response = self.client.put(
            url,
            json.dumps(data),
            content_type='application/json',
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        with schema_context(self.tenant.schema_name):
            profile.refresh_from_db()
            self.assertEqual(profile.contact_number, '0987654321')
            student_user.refresh_from_db()
            self.assertEqual(student_user.first_name, 'UpdatedFirst')
            self.assertEqual(student_user.last_name, 'UpdatedLast')





class AcademicCalendarTests(TenantTestCase):
    """
    Covers the AcademicYear/Term spine: the July-June derivation, lazy
    provisioning on first read, the single-current-term invariant, and the
    endpoint that replaces hardcoded semester strings in the frontend.
    """

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ('student', 'Management'):
                Group.objects.get_or_create(name=role)

    def _admin_token(self):
        """A Management user — IsSaaSOrCollegeAdmin passes for this group."""
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username='cal_admin', email='cal_admin@test.com', password='pw12345!'
            )
            user.groups.add(Group.objects.get(name='Management'))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    def _student_token(self):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username='cal_student', email='cal_student@test.com', password='pw12345!'
            )
            user.groups.add(Group.objects.get(name='student'))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    # -- derivation ---------------------------------------------------

    def test_academic_year_derivation_straddles_july_boundary(self):
        """July starts a new year; January-June still belongs to the previous July."""
        from .services.academics import derive_academic_year

        self.assertEqual(derive_academic_year(datetime.date(2025, 7, 1))[0], '2025-2026')
        self.assertEqual(derive_academic_year(datetime.date(2025, 12, 31))[0], '2025-2026')
        self.assertEqual(derive_academic_year(datetime.date(2026, 1, 1))[0], '2025-2026')
        self.assertEqual(derive_academic_year(datetime.date(2026, 6, 30))[0], '2025-2026')
        # One day later rolls over.
        self.assertEqual(derive_academic_year(datetime.date(2026, 7, 1))[0], '2026-2027')

    # -- lazy provisioning --------------------------------------------

    def test_current_term_provisions_calendar_on_first_read(self):
        """An empty tenant gets a year and both terms created on first call."""
        from .models.academics import AcademicYear, Term
        from .services.academics import get_current_term

        with schema_context(self.tenant.schema_name):
            self.assertEqual(AcademicYear.objects.count(), 0)
            self.assertEqual(Term.objects.count(), 0)

            term = get_current_term()

            self.assertIsNotNone(term)
            self.assertEqual(AcademicYear.objects.count(), 1)
            self.assertEqual(Term.objects.count(), 2)
            self.assertTrue(term.is_current)
            self.assertTrue(term.academic_year.is_current)
            # The flagged term must be the one actually containing today.
            self.assertTrue(term.start_date <= datetime.date.today() <= term.end_date)

    def test_current_term_is_idempotent(self):
        """Repeat calls must not create duplicate years or terms."""
        from .models.academics import AcademicYear, Term
        from .services.academics import get_current_term

        with schema_context(self.tenant.schema_name):
            first = get_current_term()
            second = get_current_term()
            self.assertEqual(first.pk, second.pk)
            self.assertEqual(AcademicYear.objects.count(), 1)
            self.assertEqual(Term.objects.count(), 2)

    # -- the single-current invariant ---------------------------------

    def test_only_one_term_can_be_current(self):
        """
        set_current_term must move the flag, not violate uniq_current_term. This
        is the constraint that would break a naive save() ordering.
        """
        from .models.academics import Term
        from .services.academics import get_current_term, set_current_term

        with schema_context(self.tenant.schema_name):
            current = get_current_term()
            other = Term.objects.exclude(pk=current.pk).first()
            self.assertIsNotNone(other)

            set_current_term(other)

            self.assertEqual(Term.objects.filter(is_current=True).count(), 1)
            self.assertEqual(Term.objects.get(is_current=True).pk, other.pk)

    def test_explicit_current_term_overrides_date_matching(self):
        """
        An administrator choice wins even when its dates have passed — a college
        whose session runs late must not have the term silently reset.
        """
        from .models.academics import AcademicYear, Term
        from .services.academics import get_current_term, set_current_term

        with schema_context(self.tenant.schema_name):
            get_current_term()  # provision
            old_year = AcademicYear.objects.create(
                name='2019-2020',
                start_date=datetime.date(2019, 7, 1),
                end_date=datetime.date(2020, 6, 30),
            )
            stale = Term.objects.create(
                academic_year=old_year, name='Odd Semester', sequence=1,
                start_date=datetime.date(2019, 7, 1), end_date=datetime.date(2019, 12, 31),
            )
            set_current_term(stale)

            resolved = get_current_term()
            self.assertEqual(resolved.pk, stale.pk)

    # -- endpoint behaviour -------------------------------------------

    def test_current_term_endpoint_never_404s_and_exposes_flat_aliases(self):
        """
        The endpoint Exams.jsx calls instead of hardcoding a semester string. The
        flat aliases let callers write straight into the legacy free-text Exam
        fields during the transition.
        """
        token = self._student_token()
        response = self.client.get(
            reverse('current-term'),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('semester', response.data)
        self.assertIn('academic_year_name', response.data)
        self.assertTrue(response.data['term']['is_current'])
        # Alias must agree with the nested object, not drift from it.
        self.assertEqual(response.data['semester'], response.data['term']['name'])

    def test_creating_a_year_creates_its_terms(self):
        token = self._admin_token()
        response = self.client.post(
            reverse('academic-year-list'),
            {'name': '2030-2031'},
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(len(response.data['terms']), 2)
        # Dates derived from the name when not supplied.
        self.assertEqual(response.data['start_date'], '2030-07-01')
        self.assertEqual(response.data['end_date'], '2031-06-30')

    def test_term_end_date_must_follow_start_date(self):
        from .models.academics import AcademicYear

        token = self._admin_token()
        with schema_context(self.tenant.schema_name):
            year = AcademicYear.objects.create(
                name='2031-2032',
                start_date=datetime.date(2031, 7, 1),
                end_date=datetime.date(2032, 6, 30),
            )
        response = self.client.post(
            reverse('term-list'),
            {
                'academic_year_id': year.id, 'name': 'Backwards Term', 'sequence': 1,
                'start_date': '2031-12-31', 'end_date': '2031-07-01',
            },
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_academic_year_name_rejected_with_400_not_500(self):
        """IntegrityError must surface as a clean validation error."""
        token = self._admin_token()
        payload = {'name': '2032-2033'}
        first = self.client.post(
            reverse('academic-year-list'), payload,
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        second = self.client.post(
            reverse('academic-year-list'), payload,
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(second.status_code, status.HTTP_400_BAD_REQUEST)

    def test_students_can_read_but_not_write_the_calendar(self):
        token = self._student_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}

        self.assertEqual(
            self.client.get(reverse('academic-year-list'), format='json', **auth).status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            self.client.post(
                reverse('academic-year-list'), {'name': '2040-2041'}, format='json', **auth
            ).status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_current_term_cannot_be_deleted(self):
        """Deleting the current term would leave the system with no answer again."""
        from .services.academics import get_current_term

        token = self._admin_token()
        with schema_context(self.tenant.schema_name):
            term = get_current_term()

        response = self.client.delete(
            reverse('term-detail', args=[term.id]),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_academics_is_granted_without_a_subscription_or_admin_action(self):
        """
        The calendar is foundational, so an existing tenant must see it with no
        subscription change and no admin ticking a checkbox. This holds because
        'academics' is in ROLE_DEFAULT_MODULES but deliberately NOT in
        PREMIUM_MODULES, so MyAllowedModulesView re-adds it even when the
        persisted allowed_modules list is empty.
        """
        from .models.module_permissions import TenantModulePermission

        self.tenant.subscribed_modules = []
        self.tenant.save()

        with schema_context(self.tenant.schema_name):
            # Simulate an existing tenant whose stored permissions predate this module.
            TenantModulePermission.objects.update_or_create(
                group_name='Management', defaults={'allowed_modules': []}
            )

        token = self._admin_token()
        response = self.client.get(
            reverse('user-allowed-modules'),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('academics', response.data['allowed_modules'])

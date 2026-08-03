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
        The calendar and curriculum are foundational, so an existing tenant must
        see them with no subscription change and no admin ticking a checkbox.
        This holds because both are in ROLE_DEFAULT_MODULES but deliberately NOT
        in PREMIUM_MODULES, so MyAllowedModulesView re-adds them even when the
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
        self.assertIn('curriculum', response.data['allowed_modules'])
        self.assertIn('transcript', response.data['allowed_modules'])


class CurriculumStructureTests(TenantTestCase):
    """
    Covers the curriculum spine: the Course unique-constraint swap (the risky part
    of this change), PROTECT on department, regulation inheritance via batch, and
    the configurable grading scheme.
    """

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ('student', 'Management'):
                Group.objects.get_or_create(name=role)
            self.dept = Department.objects.create(name="Computer Science", code="CS")

    def _admin_token(self):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username='cur_admin', email='cur_admin@test.com', password='pw12345!'
            )
            user.groups.add(Group.objects.get(name='Management'))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    def _spine(self):
        """Program + two regulations + a batch, the minimum useful structure."""
        from .models.academics import Batch, Program, Regulation
        from .services.academics import get_default_grading_scheme

        scheme = get_default_grading_scheme()
        program = Program.objects.create(
            name="B.Tech Computer Science", code="BTCSE", department=self.dept,
        )
        reg_2021 = Regulation.objects.create(
            program=program, code="R2021", effective_from_year=2021, grading_scheme=scheme,
        )
        reg_2023 = Regulation.objects.create(
            program=program, code="R2023", effective_from_year=2023, grading_scheme=scheme,
        )
        batch = Batch.objects.create(
            program=program, regulation=reg_2023, admission_year=2023, name="2023-2027",
        )
        return program, reg_2021, reg_2023, batch

    # -- the constraint swap ------------------------------------------

    def test_same_course_code_allowed_across_regulations(self):
        """
        The whole point of the swap. Two regulations must each be able to define
        CS301 with different credits — impossible under the old global unique.
        """
        from .models.course import Course

        with schema_context(self.tenant.schema_name):
            _, reg_2021, reg_2023, _ = self._spine()

            old = Course.objects.create(
                course_code="CS301", course_name="Data Structures",
                department=self.dept, regulation=reg_2021,
                semester_number=3, credits=4,
            )
            new = Course.objects.create(
                course_code="CS301", course_name="Data Structures & Algorithms",
                department=self.dept, regulation=reg_2023,
                semester_number=3, credits=3,
            )
            self.assertNotEqual(old.pk, new.pk)
            self.assertEqual(Course.objects.filter(course_code="CS301").count(), 2)

    def test_same_course_code_rejected_within_one_regulation(self):
        from django.db import IntegrityError, transaction
        from .models.course import Course

        with schema_context(self.tenant.schema_name):
            _, _, reg_2023, _ = self._spine()
            Course.objects.create(
                course_code="CS302", course_name="Operating Systems",
                department=self.dept, regulation=reg_2023, credits=4,
            )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Course.objects.create(
                        course_code="CS302", course_name="OS Duplicate",
                        department=self.dept, regulation=reg_2023, credits=4,
                    )

    def test_legacy_courses_keep_global_uniqueness(self):
        """
        Pre-spine rows have regulation=NULL. Postgres treats NULLs as distinct, so
        the composite unique alone would let them duplicate freely — the partial
        constraint is what preserves today's behaviour.
        """
        from django.db import IntegrityError, transaction
        from .models.course import Course

        with schema_context(self.tenant.schema_name):
            Course.objects.create(
                course_code="LEGACY101", course_name="Legacy Course", department=self.dept,
            )
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Course.objects.create(
                        course_code="LEGACY101", course_name="Another Legacy",
                        department=self.dept,
                    )

    def test_department_with_courses_cannot_be_deleted(self):
        """Was CASCADE — deleting a department silently destroyed its courses."""
        from django.db.models import ProtectedError
        from .models.course import Course

        with schema_context(self.tenant.schema_name):
            Course.objects.create(
                course_code="CS999", course_name="Protected Course", department=self.dept,
            )
            with self.assertRaises(ProtectedError):
                self.dept.delete()

    # -- grading scheme ----------------------------------------------

    def test_default_grading_scheme_is_provisioned_and_idempotent(self):
        from .models.grading import GradeBand, GradingScheme
        from .services.academics import get_default_grading_scheme

        with schema_context(self.tenant.schema_name):
            self.assertEqual(GradingScheme.objects.count(), 0)

            first = get_default_grading_scheme()
            self.assertTrue(first.is_default)
            self.assertEqual(first.bands.count(), 8)

            second = get_default_grading_scheme()
            self.assertEqual(first.pk, second.pk)
            self.assertEqual(GradingScheme.objects.count(), 1)
            self.assertEqual(GradeBand.objects.count(), 8)

    def test_grade_bands_leave_no_gap_between_letters(self):
        """
        A band ending at 89 and the next starting at 90 would leave 89.5 ungraded.
        Every whole and half percentage from 0 to 100 must resolve to a letter.
        """
        from decimal import Decimal
        from .services.academics import get_default_grading_scheme

        with schema_context(self.tenant.schema_name):
            scheme = get_default_grading_scheme()
            for tenth in range(0, 1001):
                pct = Decimal(tenth) / 10
                band = scheme.band_for_percentage(pct)
                self.assertIsNotNone(band, f"{pct}% falls into no grade band")

            self.assertEqual(scheme.band_for_percentage(Decimal('89.5')).letter, 'A+')
            self.assertEqual(scheme.band_for_percentage(Decimal('90')).letter, 'O')
            self.assertEqual(scheme.band_for_percentage(Decimal('39.99')).letter, 'F')
            self.assertFalse(scheme.band_for_percentage(Decimal('20')).is_pass)

    def test_only_one_grading_scheme_can_be_default(self):
        from django.db import IntegrityError, transaction
        from .models.grading import GradingScheme
        from .services.academics import get_default_grading_scheme

        with schema_context(self.tenant.schema_name):
            get_default_grading_scheme()
            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    GradingScheme.objects.create(name="Rival Default", is_default=True)

    def test_regulation_falls_back_to_default_grading_scheme(self):
        from .models.academics import Program, Regulation
        from .services.academics import get_default_grading_scheme

        with schema_context(self.tenant.schema_name):
            default = get_default_grading_scheme()
            program = Program.objects.create(
                name="B.Tech Mechanical", code="BTMECH", department=self.dept,
            )
            regulation = Regulation.objects.create(
                program=program, code="R2020", effective_from_year=2020, grading_scheme=None,
            )
            self.assertEqual(regulation.effective_grading_scheme.pk, default.pk)

    # -- regulation inheritance --------------------------------------

    def test_student_regulation_comes_from_batch_unless_overridden(self):
        """
        A cohort must not be able to split across schemes by accident, so the
        batch is the source of truth. The per-student override exists only for a
        student who failed and re-joined under a newer scheme.
        """
        with schema_context(self.tenant.schema_name):
            _, reg_2021, reg_2023, batch = self._spine()

            user = User.objects.create_user(username='stu_reg', email='stu_reg@test.com')
            student = StudentProfile.objects.create(
                user=user, student_id='STU-REG-1', department=self.dept, batch=batch,
            )
            self.assertEqual(student.effective_regulation.pk, reg_2023.pk)

            student.regulation = reg_2021
            student.save()
            self.assertEqual(student.effective_regulation.pk, reg_2021.pk)

    def test_batch_rejects_a_regulation_from_another_program(self):
        """Silently grading a cohort against another programme's scheme is unrecoverable."""
        from .models.academics import Program, Regulation

        token = self._admin_token()
        with schema_context(self.tenant.schema_name):
            program_a, _, _, _ = self._spine()
            program_b = Program.objects.create(
                name="B.Tech Civil", code="BTCIVIL", department=self.dept,
            )
            foreign_reg = Regulation.objects.create(
                program=program_b, code="RCIVIL", effective_from_year=2023,
            )

        response = self.client.post(
            reverse('batch-list'),
            {
                'program_id': program_a.id, 'regulation_id': foreign_reg.id,
                'admission_year': 2026,
            },
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('different program', str(response.data.get('error', '')))

    # -- sections -----------------------------------------------------

    def test_sections_are_scoped_per_semester(self):
        """
        Section A must be able to exist in several semesters of one batch, because
        colleges re-cut sections when electives begin. Only a repeat within the
        same semester is a clash.
        """
        from django.db import IntegrityError, transaction
        from .models.academics import Section

        with schema_context(self.tenant.schema_name):
            _, _, _, batch = self._spine()

            Section.objects.create(batch=batch, name="A", semester_number=1)
            Section.objects.create(batch=batch, name="A", semester_number=5)
            Section.objects.create(batch=batch, name="C", semester_number=5)
            self.assertEqual(Section.objects.filter(batch=batch).count(), 3)

            with self.assertRaises(IntegrityError):
                with transaction.atomic():
                    Section.objects.create(batch=batch, name="A", semester_number=5)

    # -- API ----------------------------------------------------------

    def test_program_and_batch_creation_via_api_derives_batch_name(self):
        token = self._admin_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}

        program_res = self.client.post(
            reverse('program-list'),
            {'name': 'B.Tech Electronics', 'code': 'btece', 'department_id': self.dept.id,
             'duration_years': 4},
            format='json', **auth,
        )
        self.assertEqual(program_res.status_code, status.HTTP_201_CREATED)
        # Codes are normalised to upper case.
        self.assertEqual(program_res.data['code'], 'BTECE')

        reg_res = self.client.post(
            reverse('regulation-list'),
            {'program_id': program_res.data['id'], 'code': 'R2024', 'effective_from_year': 2024},
            format='json', **auth,
        )
        self.assertEqual(reg_res.status_code, status.HTTP_201_CREATED)
        # A regulation is never left ungradeable.
        self.assertIsNotNone(reg_res.data['grading_scheme_id'])

        batch_res = self.client.post(
            reverse('batch-list'),
            {'program_id': program_res.data['id'], 'regulation_id': reg_res.data['id'],
             'admission_year': 2024},
            format='json', **auth,
        )
        self.assertEqual(batch_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(batch_res.data['name'], '2024-2028')

    def test_duplicate_program_code_rejected_with_400_not_500(self):
        token = self._admin_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}
        payload = {'name': 'Duplicate Program', 'code': 'DUP1', 'department_id': self.dept.id}

        self.assertEqual(
            self.client.post(reverse('program-list'), payload, format='json', **auth).status_code,
            status.HTTP_201_CREATED,
        )
        self.assertEqual(
            self.client.post(reverse('program-list'), payload, format='json', **auth).status_code,
            status.HTTP_400_BAD_REQUEST,
        )

    def test_regulation_courses_endpoint_totals_only_credit_bearing_courses(self):
        """
        Mandatory non-credit courses appear on a transcript but must not inflate
        the credit total used for graduation checks.
        """
        from .models.course import Course

        token = self._admin_token()
        with schema_context(self.tenant.schema_name):
            _, _, reg_2023, _ = self._spine()
            Course.objects.create(
                course_code="CS401", course_name="Compilers", department=self.dept,
                regulation=reg_2023, semester_number=1, credits=4,
            )
            Course.objects.create(
                course_code="CS402", course_name="Networks", department=self.dept,
                regulation=reg_2023, semester_number=1, credits=3,
            )
            Course.objects.create(
                course_code="MC403", course_name="Environmental Science", department=self.dept,
                regulation=reg_2023, semester_number=1, credits=0,
                course_type="mandatory_nc", is_credit_bearing=False,
            )

        response = self.client.get(
            reverse('regulation-courses', args=[reg_2023.id]),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data['results']), 3)
        self.assertEqual(response.data['total_credits'], 7.0)

    def test_course_list_still_returns_a_bare_array(self):
        """
        Assignments.jsx and Exams.jsx both do `setCourses(res.data || [])`. Wrapping
        this response in {"results": ...} would silently empty both dropdowns, so
        the array shape is part of the contract.
        """
        from .models.course import Course

        token = self._admin_token()
        with schema_context(self.tenant.schema_name):
            Course.objects.create(
                course_code="SHAPE1", course_name="Shape Check", department=self.dept,
            )

        response = self.client.get(
            reverse('course-list-create'),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
            format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsInstance(response.data, list)
        self.assertIn('credits', response.data[0])

    def test_course_credits_can_be_set_and_updated(self):
        token = self._admin_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}
        with schema_context(self.tenant.schema_name):
            _, _, reg_2023, _ = self._spine()

        created = self.client.post(
            reverse('course-list-create'),
            {
                'course_code': 'cs501', 'course_name': 'Machine Learning',
                'department_id': self.dept.id, 'regulation_id': reg_2023.id,
                'semester_number': 5, 'credits': 3, 'lecture_hours': 3,
                'tutorial_hours': 0, 'practical_hours': 2, 'course_type': 'core',
            },
            format='json', **auth,
        )
        self.assertEqual(created.status_code, status.HTTP_201_CREATED)
        self.assertEqual(created.data['course']['credits'], 3.0)
        self.assertEqual(created.data['course']['course_code'], 'CS501')
        self.assertEqual(created.data['course']['total_contact_hours'], 5)

        # Django's test Client.put defaults to application/octet-stream, unlike
        # post, so the content type must be explicit or DRF answers 415.
        import json
        updated = self.client.put(
            reverse('course-detail', args=[created.data['id']]),
            json.dumps({'credits': 4}),
            content_type='application/json', **auth,
        )
        self.assertEqual(updated.status_code, status.HTTP_200_OK)
        self.assertEqual(updated.data['credits'], 4.0)

    def test_locked_regulation_freezes_credits_but_allows_renaming(self):
        """
        Once transcripts are issued, re-weighting a course would silently move
        every SGPA computed from it. Renaming is harmless and stays allowed.
        """
        from .models.course import Course

        token = self._admin_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}
        with schema_context(self.tenant.schema_name):
            _, _, reg_2023, _ = self._spine()
            course = Course.objects.create(
                course_code="CS601", course_name="Locked Course", department=self.dept,
                regulation=reg_2023, semester_number=6, credits=4,
            )
            reg_2023.is_locked = True
            reg_2023.save()

        import json
        blocked = self.client.put(
            reverse('course-detail', args=[course.id]),
            json.dumps({'credits': 2}),
            content_type='application/json', **auth,
        )
        self.assertEqual(blocked.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('locked', str(blocked.data.get('error', '')).lower())

        allowed = self.client.put(
            reverse('course-detail', args=[course.id]),
            json.dumps({'course_name': 'Renamed Safely'}),
            content_type='application/json', **auth,
        )
        self.assertEqual(allowed.status_code, status.HTTP_200_OK)
        self.assertEqual(allowed.data['course_name'], 'Renamed Safely')
        self.assertEqual(allowed.data['credits'], 4.0)

    def test_course_api_duplicate_guard_is_regulation_scoped(self):
        """The guard must mirror the DB constraints, not the old global unique."""
        token = self._admin_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}
        with schema_context(self.tenant.schema_name):
            _, reg_2021, reg_2023, _ = self._spine()

        payload = {
            'course_code': 'CS777', 'course_name': 'Shared Code',
            'department_id': self.dept.id, 'credits': 3,
        }
        first = self.client.post(
            reverse('course-list-create'), {**payload, 'regulation_id': reg_2021.id},
            format='json', **auth,
        )
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)

        # Same code, different regulation — must be allowed.
        second = self.client.post(
            reverse('course-list-create'), {**payload, 'regulation_id': reg_2023.id},
            format='json', **auth,
        )
        self.assertEqual(second.status_code, status.HTTP_201_CREATED)

        # Same code, same regulation — must be rejected cleanly.
        third = self.client.post(
            reverse('course-list-create'), {**payload, 'regulation_id': reg_2023.id},
            format='json', **auth,
        )
        self.assertEqual(third.status_code, status.HTTP_400_BAD_REQUEST)


class AcademicBackfillTests(TenantTestCase):
    """
    Covers the parallel-run cutover for the four legacy free-text StudentProfile
    fields: the FK->string save() mirror, the backfill_student_academics
    management command (including the cases the design specifically calls out
    — course-name-in-program-field, ambiguous matches, mixed academic-year vs
    batch-span formats), the roster resolver's OR-fallback, and the
    verify_academic_backfill gate.
    """

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            Group.objects.get_or_create(name='student')
            self.dept = Department.objects.create(name="Computer Science", code="CS")

    def _spine(self, duration_years=4):
        from .models.academics import Batch, Program, Regulation
        from .services.academics import get_default_grading_scheme

        scheme = get_default_grading_scheme()
        program = Program.objects.create(
            name="B.Tech Computer Science", code="BTCSE", short_name="B.Tech CS",
            department=self.dept, duration_years=duration_years,
        )
        regulation = Regulation.objects.create(
            program=program, code="R2021", effective_from_year=2018,
            effective_to_year=2030, grading_scheme=scheme,
        )
        return program, regulation

    def _make_student(self, **overrides):
        defaults = dict(
            student_id=f"STU-{StudentProfile.objects.count() + 1}",
            department=self.dept,
        )
        defaults.update(overrides)
        user = User.objects.create_user(
            username=f"stu{StudentProfile.objects.count() + 1}",
            email=f"stu{StudentProfile.objects.count() + 1}@test.com",
        )
        return StudentProfile.objects.create(user=user, **defaults)

    # -- the save() mirror ---------------------------------------------

    def test_fk_to_string_mirror_populates_on_save(self):
        from .models.academics import Batch, Section

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            batch = Batch.objects.create(
                program=program, regulation=regulation, admission_year=2023, name="2023-2027",
            )
            section = Section.objects.create(batch=batch, semester_number=3, name="A")

            student = self._make_student(
                batch=batch, section=section, current_semester_number=3,
            )
            student.refresh_from_db()

            self.assertEqual(student.program_enrolled_in, "B.Tech CS")
            self.assertEqual(student.batch_academic_year, "2023-2027")
            self.assertEqual(student.current_semester_year, "Semester 3")
            self.assertEqual(student.section_division, "A")

    def test_mirror_leaves_unbackfilled_strings_untouched(self):
        """A student with no FKs set yet must not have their legacy strings
        touched by an unrelated save() — only setting the FK should change them."""
        with schema_context(self.tenant.schema_name):
            student = self._make_student(
                program_enrolled_in="Some Legacy Value", batch_academic_year="2020-2024",
            )
            student.locked_device_id = "device-123"
            student.save()
            student.refresh_from_db()

            self.assertEqual(student.program_enrolled_in, "Some Legacy Value")
            self.assertEqual(student.batch_academic_year, "2020-2024")

    def test_update_fields_is_widened_when_the_fk_is_named(self):
        """
        A well-behaved caller that names the FK it changed in update_fields
        must still get the mirrored string written — without widening, that
        write would be silently dropped from the UPDATE statement.
        """
        from .models.academics import Batch

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            batch = Batch.objects.create(
                program=program, regulation=regulation, admission_year=2024, name="2024-2028",
            )
            student = self._make_student(current_semester_number=1)

            student.batch = batch
            student.current_semester_number = 2
            student.save(update_fields=["batch", "current_semester_number"])
            student.refresh_from_db()

            self.assertEqual(student.current_semester_year, "Semester 2")
            self.assertEqual(student.batch_academic_year, "2024-2028")

    def test_narrow_save_does_not_clobber_a_directly_set_legacy_string(self):
        """
        The bug this test exists to prevent: views/promotion.py sets
        current_semester_year/section_division/batch_academic_year directly
        and saves with update_fields naming exactly those three strings —
        NOT current_semester_number/batch/section, since promotion does not
        yet touch the FKs at all. If the mirror recomputed those strings
        unconditionally from the student's stale, unrelated FK values, it
        would silently revert promotion's write back to the pre-promotion
        semester on this very save.
        """
        from .models.academics import Batch

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            batch = Batch.objects.create(
                program=program, regulation=regulation, admission_year=2024, name="2024-2028",
            )
            # Already backfilled to semester 3 — this FK is now stale relative
            # to the promotion below, which only ever touches the strings.
            student = self._make_student(batch=batch, current_semester_number=3)

            student.current_semester_year = "Semester 4"
            student.section_division = "B"
            student.batch_academic_year = "2024-2028"
            student.save(update_fields=["current_semester_year", "section_division", "batch_academic_year"])
            student.refresh_from_db()

            self.assertEqual(student.current_semester_year, "Semester 4")
            self.assertEqual(student.section_division, "B")
            # The stale FK itself is untouched by this save, as expected —
            # only promotion's own eventual FK-aware rewrite (a later PR)
            # would advance it.
            self.assertEqual(student.current_semester_number, 3)

    # -- backfill: dry-run vs real ---------------------------------------

    def test_backfill_dry_run_writes_nothing(self):
        """
        The whole point of --dry-run: it must not create a Batch or Section as
        a side effect of resolving them, not just skip the final StudentProfile
        update. A naive implementation that only gates the bulk_update call
        would still leave real Batch/Section rows behind.
        """
        from django.core.management import call_command
        from .models.academics import Batch, Program, Regulation, Section

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            self._make_student(
                program_enrolled_in="B.Tech CS", batch_academic_year="2022-2026",
                current_semester_year="Semester 5", section_division="A",
            )

            call_command(
                "backfill_student_academics", tenant=self.tenant.schema_name, dry_run=True
            )

            student = StudentProfile.objects.get()
            self.assertIsNone(student.batch_id)
            self.assertIsNone(student.program_id)
            self.assertEqual(Batch.objects.count(), 0)
            self.assertEqual(Section.objects.count(), 0)

    def test_backfill_resolves_program_batch_section_semester(self):
        from django.core.management import call_command
        from .models.academics import Batch

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            self._make_student(
                program_enrolled_in="B.Tech CS", batch_academic_year="2022-2026",
                current_semester_year="Semester 5", section_division="B",
            )

            call_command("backfill_student_academics", tenant=self.tenant.schema_name)

            student = StudentProfile.objects.get()
            self.assertEqual(student.program_id, program.id)
            self.assertEqual(student.current_semester_number, 5)
            self.assertIsNotNone(student.batch_id)
            self.assertEqual(student.batch.admission_year, 2022)
            self.assertIsNotNone(student.section_id)
            self.assertEqual(student.section.name, "B")
            self.assertEqual(student.section.semester_number, 5)

    def test_backfill_is_idempotent(self):
        from django.core.management import call_command
        from .models.academics import Batch

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            self._make_student(
                program_enrolled_in="B.Tech CS", batch_academic_year="2022-2026",
                current_semester_year="Semester 5", section_division="B",
            )

            call_command("backfill_student_academics", tenant=self.tenant.schema_name)
            call_command("backfill_student_academics", tenant=self.tenant.schema_name)

            self.assertEqual(Batch.objects.filter(program=program, admission_year=2022).count(), 1)

    def test_backfill_does_not_reassign_a_student_who_already_has_a_batch(self):
        """
        Re-running after new Programs are created must only pick up newly
        resolvable students, never touch one that already has a batch (which
        may include a deliberate manual override).
        """
        from django.core.management import call_command
        from .models.academics import Batch

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            existing_batch = Batch.objects.create(
                program=program, regulation=regulation, admission_year=2019, name="2019-2023",
            )
            student = self._make_student(
                batch=existing_batch, program_enrolled_in="Something Else Entirely",
            )

            call_command("backfill_student_academics", tenant=self.tenant.schema_name)

            student.refresh_from_db()
            self.assertEqual(student.batch_id, existing_batch.id)

    # -- the cases the design specifically calls out ---------------------

    def test_program_field_holding_a_course_name_falls_back_to_sole_department_program(self):
        """
        seed_large_users.py:349 sets program_enrolled_in to a course name, not a
        program. Must not be mapped to a Program matching that name (there is
        none), but IS allowed to fall back to the department's only program.
        """
        from django.core.management import call_command
        from .models.course import Course

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            Course.objects.create(
                course_code="MATH101", course_name="Mathematics 101", department=self.dept,
            )
            self._make_student(program_enrolled_in="Mathematics 101")

            call_command("backfill_student_academics", tenant=self.tenant.schema_name)

            student = StudentProfile.objects.get()
            self.assertEqual(student.program_id, program.id)

    def test_ambiguous_program_text_stays_unresolved(self):
        """Two programs fuzzy-matching the same free text must not guess."""
        from django.core.management import call_command
        from .models.academics import Program

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            Program.objects.create(
                name="B.Tech Computer Science (Honours)", code="BTCSEH",
                short_name="B.Tech CS", department=self.dept,
            )
            self._make_student(program_enrolled_in="B.Tech CS")

            call_command("backfill_student_academics", tenant=self.tenant.schema_name)

            student = StudentProfile.objects.get()
            self.assertIsNone(student.program_id)

    def test_academic_year_shaped_value_not_treated_as_batch_for_multi_year_program(self):
        """
        '2024-2025' in batch_academic_year is a 1-year span. For a 4-year
        program that is not a valid admission cohort and must be left
        unresolved rather than silently misfiled as a 1-year batch.
        """
        from django.core.management import call_command

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine(duration_years=4)
            self._make_student(
                program_enrolled_in="B.Tech CS", batch_academic_year="2024-2025",
            )

            call_command("backfill_student_academics", tenant=self.tenant.schema_name)

            student = StudentProfile.objects.get()
            self.assertEqual(student.program_id, program.id)
            self.assertIsNone(student.batch_id)

    def test_academic_year_shaped_value_accepted_as_batch_for_one_year_program(self):
        """The same shape IS a valid batch span for a genuine one-year program."""
        from django.core.management import call_command

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine(duration_years=1)
            self._make_student(
                program_enrolled_in="B.Tech CS", batch_academic_year="2024-2025",
            )

            call_command("backfill_student_academics", tenant=self.tenant.schema_name)

            student = StudentProfile.objects.get()
            self.assertIsNotNone(student.batch_id)
            self.assertEqual(student.batch.admission_year, 2024)

    def test_ambiguous_regulation_leaves_batch_unresolved(self):
        """Two regulations both covering the admission year must not let the
        backfill silently guess which curriculum the cohort actually followed."""
        from django.core.management import call_command
        from .models.academics import Regulation
        from .services.academics import get_default_grading_scheme

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            Regulation.objects.create(
                program=program, code="R2022", effective_from_year=2018,
                effective_to_year=2030, grading_scheme=get_default_grading_scheme(),
            )
            self._make_student(
                program_enrolled_in="B.Tech CS", batch_academic_year="2022-2026",
            )

            call_command("backfill_student_academics", tenant=self.tenant.schema_name)

            student = StudentProfile.objects.get()
            self.assertEqual(student.program_id, program.id)
            self.assertIsNone(student.batch_id)

    # -- the roster resolver ----------------------------------------------

    def test_roster_resolver_ors_fk_and_legacy_string_per_dimension(self):
        """
        The whole point of the resolver: a partially-backfilled tenant (some
        students carry only the FK, some only the string) must not silently
        drop either group.
        """
        from .services.academic_roster import resolve_student_roster
        from .models.academics import Batch

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            batch = Batch.objects.create(
                program=program, regulation=regulation, admission_year=2022, name="2022-2026",
            )
            backfilled = self._make_student(batch=batch)
            legacy_only = self._make_student(batch_academic_year="2022-2026")
            unrelated = self._make_student(batch_academic_year="2019-2023")

            qs, diagnostics = resolve_student_roster(
                batch_id=batch.id, legacy_batch="2022-2026",
            )

            ids = set(qs.values_list("id", flat=True))
            self.assertIn(backfilled.id, ids)
            self.assertIn(legacy_only.id, ids)
            self.assertNotIn(unrelated.id, ids)
            self.assertEqual(diagnostics["matched"], 2)
            self.assertEqual(diagnostics["resolved_by_fk"], 1)
            self.assertEqual(diagnostics["unresolved_by_fk"], 1)

    def test_roster_resolver_string_only_scope_reports_everyone_unresolved_by_fk(self):
        """If the caller never supplies an FK criterion for a dimension, a
        future FK-only query could not express that filter at all — every
        matched student is, correctly, 'unresolved by FK'."""
        from .services.academic_roster import resolve_student_roster

        with schema_context(self.tenant.schema_name):
            self._make_student(batch_academic_year="2021-2025")
            self._make_student(batch_academic_year="2021-2025")

            _, diagnostics = resolve_student_roster(legacy_batch="2021-2025")

            self.assertEqual(diagnostics["matched"], 2)
            self.assertEqual(diagnostics["resolved_by_fk"], 0)
            self.assertEqual(diagnostics["unresolved_by_fk"], 2)

    def test_roster_resolver_treats_empty_string_fk_as_unset(self):
        """
        Form fields commonly arrive as "" rather than omitted entirely (e.g. a
        cleared frontend <select>). Q(batch_id="") against an integer column
        would raise or silently match nothing — either way, not the same as
        "this dimension is unfiltered," which is what an empty string from a
        real caller (Fees.jsx's bulk-generate payload) actually means.
        """
        from .services.academic_roster import resolve_student_roster

        with schema_context(self.tenant.schema_name):
            self._make_student(batch_academic_year="2021-2025")

            # Must not raise, and must behave exactly as if batch_id were
            # omitted — i.e. still match via the legacy string alone.
            qs, diagnostics = resolve_student_roster(
                batch_id="", legacy_batch="2021-2025",
            )

            self.assertEqual(diagnostics["matched"], 1)
            self.assertEqual(diagnostics["unresolved_by_fk"], 1)

    # -- verify_academic_backfill ------------------------------------------

    def test_verify_passes_on_a_clean_backfill(self):
        from django.core.management import call_command

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            self._make_student(
                program_enrolled_in="B.Tech CS", batch_academic_year="2022-2026",
                current_semester_year="Semester 5", section_division="B",
            )
            call_command("backfill_student_academics", tenant=self.tenant.schema_name)

        # Must not raise.
        call_command("verify_academic_backfill", tenant=self.tenant.schema_name)

    def test_verify_fails_when_section_does_not_belong_to_students_batch(self):
        """
        Simulates data that could not arise from backfill_student_academics
        itself (which only ever assigns a section within the batch it just
        resolved) — proving the gate actually catches a real violation and
        is not just trivially passing.
        """
        from django.core.management import CommandError, call_command
        from .models.academics import Batch, Section

        with schema_context(self.tenant.schema_name):
            program, regulation = self._spine()
            batch_a = Batch.objects.create(
                program=program, regulation=regulation, admission_year=2020, name="2020-2024",
            )
            batch_b = Batch.objects.create(
                program=program, regulation=regulation, admission_year=2021, name="2021-2025",
            )
            section_of_b = Section.objects.create(batch=batch_b, semester_number=1, name="A")
            self._make_student(batch=batch_a, section=section_of_b)

        with self.assertRaises(CommandError):
            call_command("verify_academic_backfill", tenant=self.tenant.schema_name)


class BulkInvoiceRosterTests(TenantTestCase):
    """
    Covers the money path: BulkGenerateInvoicesView cut over to
    resolve_student_roster, the auto-derivation of a legacy string from a
    structured filter, the 409/force gate, and the concurrent-write guard now
    backed by a real DB constraint instead of a racy .exists() check.
    """

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            Group.objects.get_or_create(name='Management')
            self.dept = Department.objects.create(name="Computer Science", code="CS")

    def _admin_token(self):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username='fees_admin', email='fees_admin@test.com', password='pw12345!'
            )
            user.groups.add(Group.objects.get(name='Management'))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    def _spine(self):
        from .models.academics import Batch, Program, Regulation
        from .services.academics import get_default_grading_scheme

        scheme = get_default_grading_scheme()
        program = Program.objects.create(
            name="B.Tech Computer Science", code="BTCSE", short_name="B.Tech CS",
            department=self.dept,
        )
        regulation = Regulation.objects.create(
            program=program, code="R2021", effective_from_year=2018,
            effective_to_year=2030, grading_scheme=scheme,
        )
        batch = Batch.objects.create(
            program=program, regulation=regulation, admission_year=2022, name="2022-2026",
        )
        return program, regulation, batch

    def _make_student(self, username, **overrides):
        defaults = dict(department=self.dept)
        defaults.update(overrides)
        user = User.objects.create_user(username=username, email=f"{username}@test.com")
        return StudentProfile.objects.create(
            user=user, student_id=f"STU-{username}", **defaults
        )

    def _make_fee_structure(self, **overrides):
        from .models.fees import FeeCategory, FeeStructure, FeeStructureItem

        structure = FeeStructure.objects.create(name="Tuition 2026", **overrides)
        category, _ = FeeCategory.objects.get_or_create(name="Tuition Fee")
        FeeStructureItem.objects.create(fee_structure=structure, category=category, amount=50000)
        return structure

    # -- resolver cutover: OR-fallback ---------------------------------

    def test_bulk_generate_bills_both_backfilled_and_legacy_only_students(self):
        """
        The whole point of the cutover: a partially-backfilled tenant must not
        silently under-bill. One student matches only via FK, one only via the
        legacy string — both must be billed.
        """
        with schema_context(self.tenant.schema_name):
            program, regulation, batch = self._spine()
            structure = self._make_fee_structure()

            backfilled = self._make_student("stu_fk", batch=batch)
            legacy_only = self._make_student("stu_legacy", batch_academic_year="2022-2026")
            unrelated = self._make_student("stu_other", batch_academic_year="2019-2023")

        token = self._admin_token()
        response = self.client.post(
            reverse('fee-invoice-bulk-generate'),
            {
                "fee_structure_id": structure.id, "due_date": "2026-08-01",
                "batch_id": batch.id, "force": True,
            },
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["generated"], 2)

        with schema_context(self.tenant.schema_name):
            from .models.fees import StudentFeeInvoice
            billed_ids = set(StudentFeeInvoice.objects.filter(fee_structure=structure)
                              .values_list("student_id", flat=True))
            self.assertIn(backfilled.user_id, billed_ids)
            self.assertIn(legacy_only.user_id, billed_ids)
            self.assertNotIn(unrelated.user_id, billed_ids)

    # -- the 409/force gate ---------------------------------------------

    def test_structured_filter_with_unbackfilled_students_returns_409_without_force(self):
        with schema_context(self.tenant.schema_name):
            program, regulation, batch = self._spine()
            structure = self._make_fee_structure()
            self._make_student("stu_fk2", batch=batch)
            self._make_student("stu_legacy2", batch_academic_year="2022-2026")

        token = self._admin_token()
        response = self.client.post(
            reverse('fee-invoice-bulk-generate'),
            {"fee_structure_id": structure.id, "due_date": "2026-08-01", "batch_id": batch.id},
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_409_CONFLICT)
        self.assertEqual(response.data["unresolved_students_in_scope"], 1)
        self.assertEqual(response.data["matched"], 2)

        with schema_context(self.tenant.schema_name):
            from .models.fees import StudentFeeInvoice
            self.assertEqual(StudentFeeInvoice.objects.filter(fee_structure=structure).count(), 0)

    def test_force_true_proceeds_past_the_409_and_bills_everyone_matched(self):
        with schema_context(self.tenant.schema_name):
            program, regulation, batch = self._spine()
            structure = self._make_fee_structure()
            self._make_student("stu_fk3", batch=batch)
            self._make_student("stu_legacy3", batch_academic_year="2022-2026")

        token = self._admin_token()
        response = self.client.post(
            reverse('fee-invoice-bulk-generate'),
            {
                "fee_structure_id": structure.id, "due_date": "2026-08-01",
                "batch_id": batch.id, "force": True,
            },
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["generated"], 2)

    def test_legacy_only_request_never_gated_regardless_of_backfill_state(self):
        """
        Today's existing frontend sends only legacy string filters. That golden
        path must keep working with no force flag required, even though every
        matched student is technically 'unresolved by fk' — there is no FK
        criterion in play, so nothing is actually at risk of under-billing.
        """
        with schema_context(self.tenant.schema_name):
            program, regulation, batch = self._spine()
            structure = self._make_fee_structure()
            self._make_student("stu_legacy4", batch_academic_year="2022-2026")

        token = self._admin_token()
        response = self.client.post(
            reverse('fee-invoice-bulk-generate'),
            {
                "fee_structure_id": structure.id, "due_date": "2026-08-01",
                "batch_academic_year": "2022-2026",
            },
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["generated"], 1)

    def test_no_students_matched_returns_400(self):
        with schema_context(self.tenant.schema_name):
            structure = self._make_fee_structure()

        token = self._admin_token()
        response = self.client.post(
            reverse('fee-invoice-bulk-generate'),
            {
                "fee_structure_id": structure.id, "due_date": "2026-08-01",
                "batch_academic_year": "no-such-batch",
            },
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    # -- double-invoice guard now backed by a DB constraint --------------

    def test_duplicate_invoice_for_same_student_and_structure_is_rejected(self):
        from django.db import IntegrityError, transaction as db_transaction
        from .models.fees import StudentFeeInvoice

        with schema_context(self.tenant.schema_name):
            structure = self._make_fee_structure()
            student = self._make_student("stu_dup")
            StudentFeeInvoice.objects.create(
                student=student.user, fee_structure=structure, due_date="2026-08-01",
                total_amount=50000,
            )
            with self.assertRaises(IntegrityError):
                with db_transaction.atomic():
                    StudentFeeInvoice.objects.create(
                        student=student.user, fee_structure=structure, due_date="2026-08-01",
                        total_amount=50000,
                    )

    def test_re_running_bulk_generate_skips_already_invoiced_students(self):
        with schema_context(self.tenant.schema_name):
            program, regulation, batch = self._spine()
            structure = self._make_fee_structure()
            self._make_student("stu_rerun", batch=batch)

        token = self._admin_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}
        payload = {"fee_structure_id": structure.id, "due_date": "2026-08-01", "batch_id": batch.id, "force": True}

        first = self.client.post(reverse('fee-invoice-bulk-generate'), payload, format='json', **auth)
        self.assertEqual(first.data["generated"], 1)

        second = self.client.post(reverse('fee-invoice-bulk-generate'), payload, format='json', **auth)
        self.assertEqual(second.data["generated"], 0)
        self.assertEqual(second.data["skipped"], 1)

    def test_manual_ad_hoc_invoices_without_a_fee_structure_are_unrestricted(self):
        """fee_structure is nullable for manual invoices; the uniqueness
        constraint must not accidentally cap a student to one such invoice."""
        from .models.fees import StudentFeeInvoice

        with schema_context(self.tenant.schema_name):
            student = self._make_student("stu_manual")
            StudentFeeInvoice.objects.create(
                student=student.user, fee_structure=None, due_date="2026-08-01", total_amount=1000,
            )
            StudentFeeInvoice.objects.create(
                student=student.user, fee_structure=None, due_date="2026-09-01", total_amount=2000,
            )
            self.assertEqual(
                StudentFeeInvoice.objects.filter(student=student.user, fee_structure__isnull=True).count(), 2
            )

    # -- FeeStructure serializer exposes the new FK fields ----------------

    def test_fee_structure_api_accepts_and_returns_structured_fields(self):
        with schema_context(self.tenant.schema_name):
            program, regulation, batch = self._spine()

        token = self._admin_token()
        response = self.client.post(
            reverse('fee-structure-list'),
            {
                "name": "Structured Fee", "department": self.dept.id,
                "program": program.id, "batch": batch.id, "semester_number": 3,
                "items": [],
            },
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["program"], program.id)
        self.assertEqual(response.data["batch_name"], "2022-2026")


class CreditWeightedResultTests(TenantTestCase):
    """
    Covers the credit engine: compute_course_award, compute_term_gradesheet,
    compute_cgpa, publish_term_results, the publish/transcript endpoints, and
    bootstrap_offerings_from_exams. This is the highest-novelty code in the
    whole academic spine, so the emphasis is on the arithmetic and the
    idempotency/frozen-once-published invariants, not just the happy path.
    """

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ('student', 'Management', 'Department Head'):
                Group.objects.get_or_create(name=role)
            self.dept = Department.objects.create(name="Computer Science", code="CS")

    def _admin_token(self, role='Management'):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username=f'grading_{role.lower().replace(" ", "_")}_{User.objects.count()}',
                email=f'grading_{User.objects.count()}@test.com', password='pw12345!',
            )
            user.groups.add(Group.objects.get(name=role))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    def _spine(self, credits=4):
        from .models.academics import Batch, Program, Regulation
        from .models.course import Course
        from .services.academics import get_current_term, get_default_grading_scheme

        scheme = get_default_grading_scheme()
        program = Program.objects.create(
            name="B.Tech Computer Science", code="BTCSE", short_name="B.Tech CS",
            department=self.dept,
        )
        regulation = Regulation.objects.create(
            program=program, code="R2021", effective_from_year=2018,
            effective_to_year=2030, grading_scheme=scheme,
        )
        batch = Batch.objects.create(
            program=program, regulation=regulation, admission_year=2022, name="2022-2026",
        )
        course = Course.objects.create(
            course_code="CS301", course_name="Data Structures", department=self.dept,
            regulation=regulation, semester_number=3, credits=credits,
        )
        term = get_current_term()
        return program, regulation, batch, course, term

    def _make_student(self, username, batch=None, **overrides):
        user = User.objects.create_user(username=username, email=f"{username}@test.com")
        return StudentProfile.objects.create(
            user=user, student_id=f"STU-{username}", department=self.dept,
            batch=batch, **overrides
        )

    def _make_offering(self, course, term, batch):
        from .models.offerings import CourseOffering
        return CourseOffering.objects.create(course=course, term=term, batch=batch)

    def _register(self, student, offering, **overrides):
        from .models.offerings import StudentCourseRegistration
        defaults = dict(term=offering.term)
        defaults.update(overrides)
        return StudentCourseRegistration.objects.create(student=student, offering=offering, **defaults)

    def _exam_type(self, code, name=None):
        from .models.exam import ExamType
        obj, _ = ExamType.objects.get_or_create(code=code, defaults={"name": name or code})
        return obj

    def _make_exam(self, course, term, exam_type, total_marks=100, passing_marks=40, published=True, **overrides):
        from .models.exam import Exam
        defaults = dict(
            name=f"{course.course_code} Exam", exam_type=exam_type, department=self.dept,
            course=course, date="2026-11-01", start_time="09:00", end_time="12:00",
            total_marks=total_marks, passing_marks=passing_marks, term=term,
            results_published=published,
        )
        defaults.update(overrides)
        return Exam.objects.create(**defaults)

    def _make_result(self, exam, student, marks):
        from .models.result import StudentExamResult
        return StudentExamResult.objects.create(exam=exam, student=student, marks_obtained=marks)

    # -- compute_course_award ---------------------------------------------

    def test_compute_course_award_from_a_single_published_exam(self):
        from .services.grading import compute_course_award

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine(credits=4)
            offering = self._make_offering(course, term, batch)
            student = self._make_student("stu_award1", batch=batch)
            registration = self._register(student, offering)

            exam_type = self._exam_type("END", "End Semester")
            exam = self._make_exam(course, term, exam_type, total_marks=100, passing_marks=40)
            self._make_result(exam, student, marks=85)

            award = compute_course_award(registration)

            self.assertIsNotNone(award)
            self.assertEqual(award.percentage, 85)
            self.assertEqual(award.grade_letter, "A+")  # 80-89.99 band
            self.assertEqual(award.credits, 4)
            self.assertEqual(award.credit_points, 4 * award.grade_points)
            self.assertTrue(award.is_pass)
            self.assertTrue(award.counts_in_gpa)

    def test_compute_course_award_returns_none_without_published_results(self):
        from .services.grading import compute_course_award

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            offering = self._make_offering(course, term, batch)
            student = self._make_student("stu_award2", batch=batch)
            registration = self._register(student, offering)

            exam_type = self._exam_type("END2", "End Semester")
            exam = self._make_exam(course, term, exam_type, published=False)
            self._make_result(exam, student, marks=85)

            self.assertIsNone(compute_course_award(registration))

    def test_compute_course_award_combines_multiple_exams(self):
        from .services.grading import compute_course_award

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            offering = self._make_offering(course, term, batch)
            student = self._make_student("stu_award3", batch=batch)
            registration = self._register(student, offering)

            mid_type = self._exam_type("MID3", "Mid Term")
            # Must be exactly "END" (or FINAL/SEM/ESE) — the split heuristic
            # matches an exact set of end-semester codes, not a prefix, and
            # correctly refuses to split against an unrecognised code like
            # "END3" (caught by this test itself on first write).
            end_type = self._exam_type("END", "End Semester")
            mid = self._make_exam(course, term, mid_type, total_marks=50, passing_marks=20)
            end = self._make_exam(course, term, end_type, total_marks=100, passing_marks=40)
            self._make_result(mid, student, marks=40)
            self._make_result(end, student, marks=70)

            award = compute_course_award(registration)

            from decimal import Decimal

            self.assertEqual(award.total_marks, 110)
            self.assertEqual(award.max_marks, 150)
            # Decimal, not float: award.percentage is computed from Decimal
            # arithmetic throughout, and Decimal('73.33') != float 73.33 due
            # to binary floating-point imprecision — compare like-for-like.
            self.assertEqual(award.percentage, round(Decimal(110) / Decimal(150) * 100, 2))
            # Exactly two component types, one unambiguously "end semester" —
            # the split must resolve.
            self.assertEqual(award.internal_marks, 40)
            self.assertEqual(award.external_marks, 70)

    def test_internal_external_split_not_attempted_when_ambiguous(self):
        """Three distinct component types: don't guess which is 'external'."""
        from .services.grading import compute_course_award

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            offering = self._make_offering(course, term, batch)
            student = self._make_student("stu_award4", batch=batch)
            registration = self._register(student, offering)

            for i, code in enumerate(["Q1", "Q2", "END4"]):
                et = self._exam_type(code, code)
                exam = self._make_exam(course, term, et, total_marks=20, passing_marks=8)
                self._make_result(exam, student, marks=15)

            award = compute_course_award(registration)

            self.assertIsNone(award.internal_marks)
            self.assertIsNone(award.external_marks)
            self.assertEqual(award.total_marks, 45)  # combined total still computed

    def test_non_credit_bearing_course_award_does_not_count_in_gpa(self):
        from .services.grading import compute_course_award

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            course.is_credit_bearing = False
            course.save()
            offering = self._make_offering(course, term, batch)
            student = self._make_student("stu_award5", batch=batch)
            registration = self._register(student, offering)

            exam_type = self._exam_type("END5")
            exam = self._make_exam(course, term, exam_type)
            self._make_result(exam, student, marks=90)

            award = compute_course_award(registration)
            self.assertFalse(award.counts_in_gpa)

    # -- compute_term_gradesheet -------------------------------------------

    def test_term_gradesheet_sgpa_is_credit_weighted(self):
        from .models.grading import CourseGradeAward
        from .services.grading import compute_term_gradesheet

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course_a, term = self._spine(credits=4)
            course_b = self._make_second_course(regulation, credits=2)
            student = self._make_student("stu_sheet1", batch=batch, current_semester_number=3)

            offering_a = self._make_offering(course_a, term, batch)
            offering_b = self._make_offering(course_b, term, batch)
            reg_a = self._register(student, offering_a)
            reg_b = self._register(student, offering_b)

            # 4 credits at 9 points, 2 credits at 7 points -> (36+14)/6 = 8.33
            self._save_award(reg_a, grade_points=9, credits=4, is_pass=True, counts_in_gpa=True)
            self._save_award(reg_b, grade_points=7, credits=2, is_pass=True, counts_in_gpa=True)

            sheet = compute_term_gradesheet(student, term)

            from decimal import Decimal

            self.assertEqual(sheet.credits_registered, 6)
            self.assertEqual(sheet.credits_earned, 6)
            # Decimal, not float: sheet.sgpa is Decimal arithmetic throughout.
            self.assertEqual(sheet.sgpa, round(Decimal(4 * 9 + 2 * 7) / Decimal(6), 2))
            self.assertEqual(sheet.backlog_count, 0)
            self.assertEqual(sheet.result_status, "pass")

    def test_term_gradesheet_reports_fail_with_a_backlog(self):
        from .services.grading import compute_term_gradesheet

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            student = self._make_student("stu_sheet2", batch=batch)
            offering = self._make_offering(course, term, batch)
            reg = self._register(student, offering)
            self._save_award(reg, grade_points=0, credits=4, is_pass=False, counts_in_gpa=True)

            sheet = compute_term_gradesheet(student, term)
            self.assertEqual(sheet.backlog_count, 1)
            self.assertEqual(sheet.result_status, "fail")

    def test_term_gradesheet_incomplete_with_no_awards(self):
        from .services.grading import compute_term_gradesheet

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            student = self._make_student("stu_sheet3", batch=batch)

            sheet = compute_term_gradesheet(student, term)
            self.assertEqual(sheet.result_status, "incomplete")
            self.assertIsNone(sheet.sgpa)

    # -- compute_cgpa -------------------------------------------------------

    def test_cgpa_uses_latest_attempt_for_a_repeated_course(self):
        """
        Policy choice pinned by this test: a course with a failed first
        attempt and a passed supplementary attempt must count the LATEST
        attempt for grade-point math, and credits_earned must still count it
        as earned (any passing attempt qualifies).
        """
        from .services.grading import compute_cgpa

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine(credits=4)
            student = self._make_student("stu_cgpa1", batch=batch)
            offering = self._make_offering(course, term, batch)

            reg1 = self._register(student, offering, attempt_number=1)
            self._save_award(reg1, grade_points=0, credits=4, is_pass=False,
                              counts_in_gpa=True, attempt_number=1, published=True)

            reg2 = self._register(student, offering, attempt_number=2, attempt_type="supplementary")
            self._save_award(reg2, grade_points=6, credits=4, is_pass=True,
                              counts_in_gpa=True, attempt_number=2, published=True)

            summary = compute_cgpa(student)

            self.assertEqual(summary.cgpa, 6)  # only the latest attempt's points count
            self.assertEqual(summary.credits_earned, 4)
            self.assertEqual(summary.active_backlog_count, 0)

    def test_cgpa_only_counts_published_awards(self):
        from .services.grading import compute_cgpa

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine(credits=4)
            student = self._make_student("stu_cgpa2", batch=batch)
            offering = self._make_offering(course, term, batch)
            reg = self._register(student, offering)
            self._save_award(reg, grade_points=8, credits=4, is_pass=True,
                              counts_in_gpa=True, published=False)

            summary = compute_cgpa(student)
            self.assertIsNone(summary.cgpa)
            self.assertEqual(summary.credits_earned, 0)

    # -- publish_term_results: the orchestration --------------------------

    def test_publish_term_results_creates_awards_and_refreshes_cgpa(self):
        from .services.grading import publish_term_results

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine(credits=3)
            student = self._make_student("stu_pub1", batch=batch, current_semester_number=3)
            offering = self._make_offering(course, term, batch)
            self._register(student, offering)

            exam_type = self._exam_type("ENDPUB1")
            exam = self._make_exam(course, term, exam_type, total_marks=100, passing_marks=40)
            self._make_result(exam, student, marks=72)

            result = publish_term_results(term)

            self.assertEqual(result["awards_created"], 1)
            self.assertEqual(result["students_affected"], 1)

            from .models.grading import CourseGradeAward, StudentAcademicSummary, TermGradeSheet
            award = CourseGradeAward.objects.get(student=student, term=term)
            self.assertTrue(award.is_published)
            sheet = TermGradeSheet.objects.get(student=student, term=term)
            self.assertTrue(sheet.is_published)
            summary = StudentAcademicSummary.objects.get(student=student)
            self.assertIsNotNone(summary.cgpa)

    def test_publish_term_results_is_safe_to_call_twice(self):
        """
        Re-running publish must not touch an already-published award — this is
        the 'frozen once published' invariant. A second call with no new exam
        results should create zero new awards.
        """
        from .services.grading import publish_term_results

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            student = self._make_student("stu_pub2", batch=batch)
            offering = self._make_offering(course, term, batch)
            self._register(student, offering)
            exam_type = self._exam_type("ENDPUB2")
            exam = self._make_exam(course, term, exam_type)
            self._make_result(exam, student, marks=60)

            first = publish_term_results(term)
            second = publish_term_results(term)

            self.assertEqual(first["awards_created"], 1)
            self.assertEqual(second["awards_created"], 0)

            from .models.grading import CourseGradeAward
            self.assertEqual(CourseGradeAward.objects.filter(student=student, term=term).count(), 1)

    # -- HTTP: publish endpoint ---------------------------------------------

    def test_publish_endpoint_requires_hod_or_above(self):
        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()

        token = self._admin_token(role='student')
        # A plain student has no group matching IsHMOrAbove; use a raw token
        # without adding to any privileged group to exercise the 403 path.
        with schema_context(self.tenant.schema_name):
            plain_user = User.objects.create_user(username='plain_user', email='plain@test.com')
            plain_token = RefreshToken.for_user(plain_user)
            plain_token['tenant_schema'] = self.tenant.schema_name

        response = self.client.post(
            reverse('publish-term-results', args=[term.id]),
            HTTP_AUTHORIZATION=f'Bearer {plain_token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_publish_endpoint_404_for_unknown_term(self):
        token = self._admin_token()
        response = self.client.post(
            reverse('publish-term-results', args=[999999]),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    # -- HTTP: transcript endpoint -------------------------------------------

    def test_student_can_view_their_own_transcript(self):
        from .services.grading import publish_term_results

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            student = self._make_student("stu_transcript1", batch=batch, current_semester_number=3)
            offering = self._make_offering(course, term, batch)
            self._register(student, offering)
            exam_type = self._exam_type("ENDT1")
            exam = self._make_exam(course, term, exam_type)
            self._make_result(exam, student, marks=77)
            publish_term_results(term)

            student.user.groups.add(Group.objects.get(name='student'))
            token = RefreshToken.for_user(student.user)
            token['tenant_schema'] = self.tenant.schema_name

        response = self.client.get(
            reverse('my-transcript'),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["terms"]), 1)
        self.assertIsNotNone(response.data["cgpa"])

    def test_student_cannot_view_another_students_transcript(self):
        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            student_a = self._make_student("stu_transcript_a", batch=batch)
            student_b = self._make_student("stu_transcript_b", batch=batch)
            student_a.user.groups.add(Group.objects.get(name='student'))
            token = RefreshToken.for_user(student_a.user)
            token['tenant_schema'] = self.tenant.schema_name

        response = self.client.get(
            reverse('student-transcript', args=[student_b.id]),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    # -- bootstrap_offerings_from_exams -------------------------------------

    def test_bootstrap_creates_offering_and_registrations_from_exam_results(self):
        from django.core.management import call_command
        from .models.offerings import CourseOffering, StudentCourseRegistration

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            s1 = self._make_student("stu_boot1", batch=batch)
            s2 = self._make_student("stu_boot2", batch=batch)
            exam_type = self._exam_type("BOOT1")
            exam = self._make_exam(course, term, exam_type)
            self._make_result(exam, s1, marks=50)
            self._make_result(exam, s2, marks=60)

            call_command("bootstrap_offerings_from_exams", tenant=self.tenant.schema_name)

            offering = CourseOffering.objects.get(course=course, term=term, batch=batch)
            self.assertEqual(
                StudentCourseRegistration.objects.filter(offering=offering).count(), 2
            )

    def test_bootstrap_skips_exam_whose_results_span_multiple_batches(self):
        from django.core.management import call_command
        from .models.academics import Batch
        from .models.offerings import CourseOffering

        with schema_context(self.tenant.schema_name):
            program, regulation, batch_a, course, term = self._spine()
            batch_b = Batch.objects.create(
                program=program, regulation=regulation, admission_year=2021, name="2021-2025",
            )
            s1 = self._make_student("stu_boot3", batch=batch_a)
            s2 = self._make_student("stu_boot4", batch=batch_b)
            exam_type = self._exam_type("BOOT2")
            exam = self._make_exam(course, term, exam_type)
            self._make_result(exam, s1, marks=50)
            self._make_result(exam, s2, marks=55)

            call_command("bootstrap_offerings_from_exams", tenant=self.tenant.schema_name)

            self.assertEqual(CourseOffering.objects.filter(course=course, term=term).count(), 0)

    def test_bootstrap_dry_run_creates_nothing(self):
        from django.core.management import call_command
        from .models.offerings import CourseOffering

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            student = self._make_student("stu_boot5", batch=batch)
            exam_type = self._exam_type("BOOT3")
            exam = self._make_exam(course, term, exam_type)
            self._make_result(exam, student, marks=65)

            call_command(
                "bootstrap_offerings_from_exams", tenant=self.tenant.schema_name, dry_run=True,
            )

            self.assertEqual(CourseOffering.objects.count(), 0)

    def test_bootstrap_resolves_term_from_legacy_strings_when_fk_unset(self):
        from django.core.management import call_command
        from .models.offerings import CourseOffering

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            student = self._make_student("stu_boot6", batch=batch)
            exam_type = self._exam_type("BOOT4")
            # No exam.term set — only the legacy strings, matching a legacy exam
            # created before Exam.term existed. term is passed as a keyword
            # here (not positionally) specifically so it can be overridden to
            # None — passing it both ways raises TypeError.
            exam = self._make_exam(
                course, exam_type=exam_type,
                term=None, academic_year=term.academic_year.name,
                semester=f"Semester {1 if term.sequence == 1 else 2}",
            )
            self._make_result(exam, student, marks=70)

            call_command("bootstrap_offerings_from_exams", tenant=self.tenant.schema_name)

            offering = CourseOffering.objects.filter(course=course, batch=batch).first()
            self.assertIsNotNone(offering)
            self.assertEqual(offering.term_id, term.id)

    # -- recompute_academic_records ------------------------------------------

    def test_recompute_requires_include_published_to_touch_a_published_award(self):
        from django.core.management import call_command
        from .models.grading import CourseGradeAward
        from .services.grading import publish_term_results

        with schema_context(self.tenant.schema_name):
            program, regulation, batch, course, term = self._spine()
            student = self._make_student("stu_recompute1", batch=batch)
            offering = self._make_offering(course, term, batch)
            self._register(student, offering)
            exam_type = self._exam_type("RECOMP1")
            exam = self._make_exam(course, term, exam_type, total_marks=100, passing_marks=40)
            self._make_result(exam, student, marks=50)
            publish_term_results(term)

            original = CourseGradeAward.objects.get(student=student, term=term)
            original_grade = original.grade_letter

            # A correction lands after publish: marks are revised upward.
            from .models.result import StudentExamResult
            StudentExamResult.objects.filter(exam=exam, student=student).update(marks_obtained=95)

            call_command("recompute_academic_records", tenant=self.tenant.schema_name, term=term.id)
            unchanged = CourseGradeAward.objects.get(student=student, term=term)
            self.assertEqual(unchanged.grade_letter, original_grade)

            call_command(
                "recompute_academic_records", tenant=self.tenant.schema_name, term=term.id,
                include_published=True,
            )
            corrected = CourseGradeAward.objects.get(student=student, term=term)
            self.assertEqual(corrected.grade_letter, "O")  # 95% -> the 90-100 band
            self.assertEqual(CourseGradeAward.objects.filter(student=student, term=term).count(), 1)

    # -- helpers for the tests above ----------------------------------------

    def _make_second_course(self, regulation, credits):
        from .models.course import Course
        return Course.objects.create(
            course_code="CS302", course_name="Algorithms", department=self.dept,
            regulation=regulation, semester_number=3, credits=credits,
        )

    def _save_award(self, registration, *, grade_points, credits, is_pass, counts_in_gpa,
                     attempt_number=1, published=True):
        from .models.grading import CourseGradeAward
        from .services.academics import get_default_grading_scheme

        scheme = get_default_grading_scheme()
        return CourseGradeAward.objects.create(
            registration=registration, student=registration.student, term=registration.term,
            credits=credits, grade_letter="X", grade_points=grade_points,
            credit_points=credits * grade_points, is_pass=is_pass, counts_in_gpa=counts_in_gpa,
            grading_scheme=scheme, attempt_number=attempt_number,
            is_published=published,
        )


class OutcomeBasedEducationTests(TenantTestCase):
    """
    Covers PR-6: ProgramOutcome/CourseOutcome/POCOMapping constraints, the
    course-outcome snapshot into Exam.question_structure at paper-sync time,
    and the generalised StudentTopicPerformanceView loop — including the
    independent-tagging fix (a CO-only-tagged question must not be dropped
    just because it lacks a topic tag).
    """

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ('student', 'Management'):
                Group.objects.get_or_create(name=role)
            self.dept = Department.objects.create(name="Computer Science", code="CS")

    def _admin_token(self):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username=f'outcomes_admin_{User.objects.count()}',
                email=f'outcomes_admin_{User.objects.count()}@test.com', password='pw12345!',
            )
            user.groups.add(Group.objects.get(name='Management'))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    def _program_and_course(self):
        from .models.academics import Program, Regulation
        from .models.course import Course
        from .services.academics import get_default_grading_scheme

        program = Program.objects.create(
            name="B.Tech Computer Science", code="BTCSE", department=self.dept,
        )
        regulation = Regulation.objects.create(
            program=program, code="R2021", effective_from_year=2018,
            grading_scheme=get_default_grading_scheme(),
        )
        course = Course.objects.create(
            course_code="CS301", course_name="Data Structures", department=self.dept,
            regulation=regulation, semester_number=3, credits=4,
        )
        return program, course

    def _student(self, username):
        user = User.objects.create_user(username=username, email=f"{username}@test.com")
        from .models.profile import StudentProfile as SP
        return SP.objects.create(user=user, student_id=f"STU-{username}", department=self.dept)

    def _teaching_staff(self, username):
        user = User.objects.create_user(username=username, email=f"{username}@test.com")
        from .models.profile import TeachingStaffProfile
        return TeachingStaffProfile.objects.create(
            user=user, employee_id=f"EMP-{username}", department=self.dept,
        )

    # -- model constraints --------------------------------------------------

    def test_course_outcome_code_unique_per_course_not_globally(self):
        """The same CO code ('CO1') must be reusable across different
        courses — codes are meaningful only within their own course."""
        from .models.outcomes import CourseOutcome
        from .models.course import Course

        with schema_context(self.tenant.schema_name):
            program, course_a = self._program_and_course()
            course_b = Course.objects.create(
                course_code="CS302", course_name="Algorithms", department=self.dept,
                regulation=course_a.regulation, semester_number=3, credits=3,
            )
            CourseOutcome.objects.create(course=course_a, code="CO1", statement="Understand X")
            # Must NOT raise — same code, different course.
            CourseOutcome.objects.create(course=course_b, code="CO1", statement="Understand Y")
            self.assertEqual(CourseOutcome.objects.filter(code="CO1").count(), 2)

    def test_course_outcome_code_rejected_within_same_course(self):
        from django.db import IntegrityError, transaction as db_transaction
        from .models.outcomes import CourseOutcome

        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()
            CourseOutcome.objects.create(course=course, code="CO1", statement="Understand X")
            with self.assertRaises(IntegrityError):
                with db_transaction.atomic():
                    CourseOutcome.objects.create(course=course, code="CO1", statement="Duplicate")

    def test_po_co_mapping_unique_pair(self):
        from django.db import IntegrityError, transaction as db_transaction
        from .models.outcomes import CourseOutcome, POCOMapping, ProgramOutcome

        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()
            co = CourseOutcome.objects.create(course=course, code="CO1", statement="X")
            po = ProgramOutcome.objects.create(program=program, code="PO1", statement="Y")
            POCOMapping.objects.create(course_outcome=co, program_outcome=po, strength=2)
            with self.assertRaises(IntegrityError):
                with db_transaction.atomic():
                    POCOMapping.objects.create(course_outcome=co, program_outcome=po, strength=3)

    # -- paper_sync snapshot resolution chain --------------------------------

    def test_sync_snapshots_course_outcome_from_question_override(self):
        from .models.question_bank import ExamQuestion, Question, SyllabusTopic
        from .models.outcomes import CourseOutcome
        from .models.exam import Exam, ExamType
        from .services.paper_sync import sync_question_structure

        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()
            topic = SyllabusTopic.objects.create(course=course, name="Unit 1")
            co_topic = CourseOutcome.objects.create(course=course, code="CO1", statement="Topic-level")
            co_question = CourseOutcome.objects.create(course=course, code="CO2", statement="Question override")
            topic.course_outcome = co_topic
            topic.save()

            question = Question.objects.create(
                course=course, topic=topic, text="Explain X", marks=10,
                course_outcome=co_question,  # overrides the topic's CO
            )
            exam_type = ExamType.objects.create(name="Mid", code="SYNCMID1")
            exam = Exam.objects.create(
                name="Sync Test Exam", exam_type=exam_type, department=self.dept, course=course,
                date="2026-11-01", start_time="09:00", end_time="12:00",
            )
            ExamQuestion.objects.create(
                exam=exam, question=question, question_label="Q1",
                question_text_snapshot=question.text, marks=10, topic=topic,
            )

            sync_question_structure(exam)
            exam.refresh_from_db()

            self.assertEqual(exam.question_structure["Q1"]["topic"], "Unit 1")
            # The question's own CO wins over the topic's.
            self.assertEqual(exam.question_structure["Q1"]["course_outcome"], "CO2")

    def test_sync_falls_back_to_topic_course_outcome(self):
        from .models.question_bank import ExamQuestion, Question, SyllabusTopic
        from .models.outcomes import CourseOutcome
        from .models.exam import Exam, ExamType
        from .services.paper_sync import sync_question_structure

        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()
            topic = SyllabusTopic.objects.create(course=course, name="Unit 2")
            co_topic = CourseOutcome.objects.create(course=course, code="CO1", statement="Topic-level")
            topic.course_outcome = co_topic
            topic.save()

            question = Question.objects.create(course=course, topic=topic, text="Explain Y", marks=10)
            exam_type = ExamType.objects.create(name="Mid", code="SYNCMID2")
            exam = Exam.objects.create(
                name="Sync Fallback Exam", exam_type=exam_type, department=self.dept, course=course,
                date="2026-11-01", start_time="09:00", end_time="12:00",
            )
            ExamQuestion.objects.create(
                exam=exam, question=question, question_label="Q1",
                question_text_snapshot=question.text, marks=10, topic=topic,
            )

            sync_question_structure(exam)
            exam.refresh_from_db()

            self.assertEqual(exam.question_structure["Q1"]["course_outcome"], "CO1")

    def test_sync_never_guesses_when_untagged(self):
        from .models.question_bank import ExamQuestion, Question
        from .models.exam import Exam, ExamType
        from .services.paper_sync import sync_question_structure

        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()
            question = Question.objects.create(course=course, text="Untagged", marks=10)
            exam_type = ExamType.objects.create(name="Mid", code="SYNCMID3")
            exam = Exam.objects.create(
                name="Untagged Exam", exam_type=exam_type, department=self.dept, course=course,
                date="2026-11-01", start_time="09:00", end_time="12:00",
            )
            ExamQuestion.objects.create(
                exam=exam, question=question, question_label="Q1",
                question_text_snapshot=question.text, marks=10,
            )

            sync_question_structure(exam)
            exam.refresh_from_db()

            self.assertIsNone(exam.question_structure["Q1"]["course_outcome"])
            self.assertIsNone(exam.question_structure["Q1"]["topic"])

    # -- validate_question_structure accepts the new key ---------------------

    def test_validate_question_structure_accepts_course_outcome_string(self):
        from .views.exam import validate_question_structure

        self.assertIsNone(validate_question_structure(
            {"Q1": {"marks": 10, "topic": "Unit 1", "course_outcome": "CO1"}}
        ))
        error = validate_question_structure({"Q1": {"marks": 10, "course_outcome": 123}})
        self.assertIsNotNone(error)
        self.assertIn("course_outcome", error)

    # -- StudentTopicPerformanceView: the generalised loop --------------------

    def _evaluated_paper(self, course, student, question_structure, question_scores):
        from .models.valuation import ScannedPaper, ValuationSession
        from .models.exam import Exam, ExamType
        from django.utils import timezone

        exam_type = ExamType.objects.create(name="Mid", code=f"PROG{ScannedPaper.objects.count()}")
        exam = Exam.objects.create(
            name="Progress Exam", exam_type=exam_type, department=self.dept, course=course,
            date="2026-11-01", start_time="09:00", end_time="12:00",
            question_structure=question_structure,
        )
        evaluator = self._teaching_staff(f"eval{ScannedPaper.objects.count()}")
        session = ValuationSession.objects.create(exam=exam, evaluator=evaluator)
        return ScannedPaper.objects.create(
            session=session, student=student, scanned_file_url="s3://x",
            status="Evaluated", evaluated_at=timezone.now(), question_scores=question_scores,
        )

    def test_topic_performance_endpoint_reports_both_topics_and_course_outcomes(self):
        from .models.outcomes import CourseOutcome

        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()
            CourseOutcome.objects.create(
                course=course, code="CO1", statement="X", target_attainment_percent=50,
            )
            student = self._student("stu_prog1")
            self._evaluated_paper(
                course, student,
                question_structure={"Q1": {"marks": 10, "topic": "Unit 1", "course_outcome": "CO1"}},
                question_scores={"Q1": 8},
            )
            student.user.groups.add(Group.objects.get(name='student'))
            token = RefreshToken.for_user(student.user)
            token['tenant_schema'] = self.tenant.schema_name

        response = self.client.get(
            reverse('analytics-student-topic-performance'),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["topics"]), 1)
        self.assertEqual(response.data["topics"][0]["topic"], "Unit 1")
        self.assertEqual(len(response.data["course_outcomes"]), 1)
        co = response.data["course_outcomes"][0]
        self.assertEqual(co["code"], "CO1")
        self.assertEqual(co["percentage"], 80.0)
        self.assertTrue(co["meets_target"])  # 80% >= 50% target

    def test_topic_performance_includes_co_only_tagged_question_without_a_topic(self):
        """
        The bug an earlier draft of the loop would have had: a question
        carrying a course_outcome but no topic must still be counted toward
        course_outcomes, not silently dropped by the topic-untagged branch.
        """
        from .models.outcomes import CourseOutcome

        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()
            CourseOutcome.objects.create(course=course, code="CO9", statement="No topic")
            student = self._student("stu_prog2")
            self._evaluated_paper(
                course, student,
                question_structure={"Q1": {"marks": 10, "topic": None, "course_outcome": "CO9"}},
                question_scores={"Q1": 6},
            )
            student.user.groups.add(Group.objects.get(name='student'))
            token = RefreshToken.for_user(student.user)
            token['tenant_schema'] = self.tenant.schema_name

        response = self.client.get(
            reverse('analytics-student-topic-performance'),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # No topic tag at all -> topics stays empty, but course_outcomes must
        # still have the CO-tagged entry.
        self.assertEqual(len(response.data["topics"]), 0)
        self.assertEqual(len(response.data["course_outcomes"]), 1)
        self.assertEqual(response.data["course_outcomes"][0]["code"], "CO9")
        self.assertEqual(response.data["untagged_marks_excluded"], 6)

    def test_topic_performance_does_not_conflate_same_co_code_across_courses(self):
        from .models.course import Course
        from .models.outcomes import CourseOutcome

        with schema_context(self.tenant.schema_name):
            program, course_a = self._program_and_course()
            course_b = Course.objects.create(
                course_code="CS399", course_name="Other Course", department=self.dept,
                regulation=course_a.regulation, semester_number=3, credits=3,
            )
            CourseOutcome.objects.create(course=course_a, code="CO1", statement="A", target_attainment_percent=90)
            CourseOutcome.objects.create(course=course_b, code="CO1", statement="B", target_attainment_percent=10)
            student = self._student("stu_prog3")
            self._evaluated_paper(
                course_a, student,
                question_structure={"Q1": {"marks": 10, "course_outcome": "CO1"}},
                question_scores={"Q1": 5},
            )
            self._evaluated_paper(
                course_b, student,
                question_structure={"Q1": {"marks": 10, "course_outcome": "CO1"}},
                question_scores={"Q1": 5},
            )
            student.user.groups.add(Group.objects.get(name='student'))
            token = RefreshToken.for_user(student.user)
            token['tenant_schema'] = self.tenant.schema_name

        response = self.client.get(
            reverse('analytics-student-topic-performance'),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}', format='json',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Two separate CO1 entries — one per course — not merged into one.
        self.assertEqual(len(response.data["course_outcomes"]), 2)
        targets = sorted(c["target_attainment_percent"] for c in response.data["course_outcomes"])
        self.assertEqual(targets, [10.0, 90.0])

    # -- CRUD endpoints --------------------------------------------------------

    def test_create_program_outcome_and_course_outcome_and_mapping(self):
        token = self._admin_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}
        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()

        po_res = self.client.post(
            reverse('program-outcome-list', args=[program.id]),
            {"code": "PO1", "statement": "Engineering knowledge"}, format='json', **auth,
        )
        self.assertEqual(po_res.status_code, status.HTTP_201_CREATED)

        co_res = self.client.post(
            reverse('course-outcome-list', args=[course.id]),
            {"code": "CO1", "statement": "Apply data structures"}, format='json', **auth,
        )
        self.assertEqual(co_res.status_code, status.HTTP_201_CREATED)

        mapping_res = self.client.post(
            reverse('po-co-mapping-list', args=[co_res.data["id"]]),
            {"program_outcome_id": po_res.data["id"], "strength": 3}, format='json', **auth,
        )
        self.assertEqual(mapping_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(mapping_res.data["strength"], 3)

    def test_mapping_rejects_program_outcome_from_a_different_program(self):
        from .models.academics import Program

        token = self._admin_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}
        with schema_context(self.tenant.schema_name):
            program_a, course = self._program_and_course()
            program_b = Program.objects.create(
                name="B.Tech Mechanical", code="BTMECH", department=self.dept,
            )
            from .models.outcomes import CourseOutcome, ProgramOutcome
            co = CourseOutcome.objects.create(course=course, code="CO1", statement="X")
            foreign_po = ProgramOutcome.objects.create(program=program_b, code="PO1", statement="Y")

        response = self.client.post(
            reverse('po-co-mapping-list', args=[co.id]),
            {"program_outcome_id": foreign_po.id}, format='json', **auth,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_syllabus_topic_and_question_accept_course_outcome_id(self):
        token = self._admin_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}
        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()
            from .models.outcomes import CourseOutcome
            co = CourseOutcome.objects.create(course=course, code="CO1", statement="X")

        topic_res = self.client.post(
            reverse('syllabus-topic-list', args=[course.id]),
            {"name": "Unit 1", "course_outcome_id": co.id}, format='json', **auth,
        )
        self.assertEqual(topic_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(topic_res.data["course_outcome_code"], "CO1")

        question_res = self.client.post(
            reverse('question-bank-list', args=[course.id]),
            {"text": "Explain", "marks": 5, "course_outcome_id": co.id}, format='json', **auth,
        )
        self.assertEqual(question_res.status_code, status.HTTP_201_CREATED)
        self.assertEqual(question_res.data["course_outcome_code"], "CO1")

    def test_question_rejects_course_outcome_from_a_different_course(self):
        from .models.course import Course

        token = self._admin_token()
        auth = {'HTTP_AUTHORIZATION': f'Bearer {token.access_token}'}
        with schema_context(self.tenant.schema_name):
            program, course_a = self._program_and_course()
            course_b = Course.objects.create(
                course_code="CS404", course_name="Other", department=self.dept,
                regulation=course_a.regulation, semester_number=4, credits=3,
            )
            from .models.outcomes import CourseOutcome
            foreign_co = CourseOutcome.objects.create(course=course_b, code="CO1", statement="X")

        response = self.client.post(
            reverse('question-bank-list', args=[course_a.id]),
            {"text": "Explain", "marks": 5, "course_outcome_id": foreign_co.id}, format='json', **auth,
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class RosterCutoverTests(TenantTestCase):
    """
    Covers the deferred PR-5 follow-up: replacing department-as-class-size
    with the real roster (CourseOffering/StudentCourseRegistration) wherever
    it's safe to do so without regressing a working default. Two call sites
    are cut over, additively:
      - notify_guardians_of_course_roster: narrows assignment notifications to
        the actual course roster, but ONLY when one exists — otherwise falls
        back to the full department, exactly matching today's behaviour.
      - ExamClassStatsView: gains enrolled_count alongside the existing
        total_students_in_department, never replacing it.
    views/exam.py's student visibility filter is deliberately NOT tightened:
    the risk of a false negative (a student can't see an exam they actually
    need to take) is categorically worse than the current false positive
    (a student sees an exam not meant for them), so the safe, over-broad
    default stays until the roster data is reliably populated tenant-wide.
    """

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ('student', 'Management', 'guardian'):
                Group.objects.get_or_create(name=role)
            self.dept = Department.objects.create(name="Computer Science", code="CS")

    def _spine(self):
        from .models.academics import Batch, Program, Regulation
        from .models.course import Course
        from .services.academics import get_current_term, get_default_grading_scheme

        program = Program.objects.create(
            name="B.Tech Computer Science", code="BTCSE", department=self.dept,
        )
        regulation = Regulation.objects.create(
            program=program, code="R2021", effective_from_year=2018,
            grading_scheme=get_default_grading_scheme(),
        )
        batch = Batch.objects.create(
            program=program, regulation=regulation, admission_year=2022, name="2022-2026",
        )
        course = Course.objects.create(
            course_code="CS301", course_name="Data Structures", department=self.dept,
            regulation=regulation, semester_number=3, credits=4,
        )
        term = get_current_term()
        return program, batch, course, term

    def _student_with_guardian(self, username):
        from .models.profile import GuardianProfile, StudentProfile as SP

        student_user = User.objects.create_user(username=username, email=f"{username}@test.com")
        student = SP.objects.create(user=student_user, student_id=f"STU-{username}", department=self.dept)

        guardian_user = User.objects.create_user(
            username=f"{username}_guardian", email=f"{username}_guardian@test.com",
        )
        guardian = GuardianProfile.objects.create(user=guardian_user, guardian_id=f"GRD-{username}")
        guardian.students.add(student)
        return student, guardian

    # -- notify_guardians_of_course_roster -----------------------------------

    def test_notifies_only_the_course_roster_when_one_exists(self):
        from .models.notification import Notification
        from .models.offerings import CourseOffering, StudentCourseRegistration
        from .services.notifications import notify_guardians_of_course_roster

        with schema_context(self.tenant.schema_name):
            program, batch, course, term = self._spine()
            on_roster, on_roster_guardian = self._student_with_guardian("roster_stu")
            not_on_roster, not_on_roster_guardian = self._student_with_guardian("other_stu")

            offering = CourseOffering.objects.create(course=course, term=term, batch=batch)
            StudentCourseRegistration.objects.create(student=on_roster, offering=offering, term=term)

            notify_guardians_of_course_roster(
                course.id, self.dept.id, title="New homework", body="due soon",
            )

            self.assertTrue(
                Notification.objects.filter(recipient=on_roster_guardian.user).exists()
            )
            self.assertFalse(
                Notification.objects.filter(recipient=not_on_roster_guardian.user).exists()
            )

    def test_falls_back_to_department_when_no_roster_exists(self):
        """
        The tenant has not bootstrapped any offering for this course — must
        not silently notify nobody. This is the regression the fallback
        exists to prevent.
        """
        from .models.notification import Notification
        from .services.notifications import notify_guardians_of_course_roster

        with schema_context(self.tenant.schema_name):
            program, batch, course, term = self._spine()
            student, guardian = self._student_with_guardian("no_roster_stu")

            notify_guardians_of_course_roster(
                course.id, self.dept.id, title="New homework", body="due soon",
            )

            self.assertTrue(Notification.objects.filter(recipient=guardian.user).exists())

    def test_assignment_creation_notifies_via_course_roster_helper(self):
        """Integration check: AssignmentListCreateView.post actually calls
        the roster-aware helper now, not the department-wide one."""
        with schema_context(self.tenant.schema_name):
            program, batch, course, term = self._spine()
            student, guardian = self._student_with_guardian("assign_stu")

            faculty_user = User.objects.create_user(username='assign_faculty', email='af@test.com')
            Group.objects.get_or_create(name='Faculty')
            faculty_user.groups.add(Group.objects.get(name='Faculty'))
            token = RefreshToken.for_user(faculty_user)
            token['tenant_schema'] = self.tenant.schema_name

        response = self.client.post(
            reverse('assignment-list-create'),
            {
                "title": "HW1", "description": "Do the thing", "due_date": "2026-12-01T23:59:00Z",
                "department_id": self.dept.id, "course_id": course.id, "notify_parents": "true",
            },
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        with schema_context(self.tenant.schema_name):
            from .models.notification import Notification
            # No roster exists for this course, so the fallback must have
            # reached the department's only student's guardian.
            self.assertTrue(Notification.objects.filter(recipient=guardian.user).exists())

    # -- ExamClassStatsView: enrolled_count is additive -----------------------

    def test_class_stats_enrolled_count_null_without_an_offering(self):
        from .models.exam import Exam, ExamType

        token = self._teacher_token()
        with schema_context(self.tenant.schema_name):
            program, batch, course, term = self._spine()
            exam_type = ExamType.objects.create(name="Mid", code="CLSSTAT1")
            exam = Exam.objects.create(
                name="Stats Exam", exam_type=exam_type, department=self.dept, course=course,
                date="2026-11-01", start_time="09:00", end_time="12:00", term=term,
            )

        response = self.client.get(
            reverse('exam-class-stats', args=[exam.id]),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.data["enrolled_count"])
        # The original field must still be present, unchanged.
        self.assertIn("total_students_in_department", response.data)

    def test_class_stats_enrolled_count_reflects_the_roster(self):
        from .models.exam import Exam, ExamType
        from .models.offerings import CourseOffering, StudentCourseRegistration

        token = self._teacher_token()
        with schema_context(self.tenant.schema_name):
            program, batch, course, term = self._spine()
            offering = CourseOffering.objects.create(course=course, term=term, batch=batch)
            for i in range(3):
                student, _ = self._student_with_guardian(f"clsstat_stu{i}")
                StudentCourseRegistration.objects.create(student=student, offering=offering, term=term)

            exam_type = ExamType.objects.create(name="Mid", code="CLSSTAT2")
            exam = Exam.objects.create(
                name="Stats Exam 2", exam_type=exam_type, department=self.dept, course=course,
                date="2026-11-01", start_time="09:00", end_time="12:00", term=term,
            )

        response = self.client.get(
            reverse('exam-class-stats', args=[exam.id]),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["enrolled_count"], 3)

    def _teacher_token(self):
        with schema_context(self.tenant.schema_name):
            Group.objects.get_or_create(name='Faculty')
            user = User.objects.create_user(
                username=f'roster_teacher_{User.objects.count()}',
                email=f'roster_teacher_{User.objects.count()}@test.com',
            )
            user.groups.add(Group.objects.get(name='Faculty'))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token


class LedgerFoundationTests(TenantTestCase):
    """P2: FinancialYear / IncomeEntry / ExpenseEntry / FixedAsset, and the
    lock-guard that makes a closed financial year append-only."""

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            Group.objects.get_or_create(name='Management')

    def _admin_token(self):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username=f'ledger_admin_{User.objects.count()}',
                email=f'ledger_admin_{User.objects.count()}@test.com', password='pw12345!',
            )
            user.groups.add(Group.objects.get(name='Management'))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    def test_fixed_asset_wdv_depreciates_over_a_year(self):
        from decimal import Decimal
        from .models.finance import FixedAsset

        with schema_context(self.tenant.schema_name):
            asset = FixedAsset.objects.create(
                name="Projector", category="IT Equipment", purchase_date=datetime.date(2024, 4, 1),
                purchase_cost=Decimal("100000.00"), depreciation_method=FixedAsset.METHOD_WDV,
                depreciation_rate_percent=Decimal("20.00"),
            )
            wdv_at_purchase = asset.written_down_value(datetime.date(2024, 4, 1))
            wdv_one_year_later = asset.written_down_value(datetime.date(2025, 4, 1))
            self.assertEqual(wdv_at_purchase, Decimal("100000.00"))
            # 20% reducing balance for 1 year -> ~80000; allow for the 365.25-day approximation.
            self.assertAlmostEqual(float(wdv_one_year_later), 80000.0, delta=500)
            self.assertLess(wdv_one_year_later, wdv_at_purchase)

    def test_fixed_asset_reads_disposal_value_after_disposal_date(self):
        from decimal import Decimal
        from .models.finance import FixedAsset

        with schema_context(self.tenant.schema_name):
            asset = FixedAsset.objects.create(
                name="Old Bus", category="Vehicle", purchase_date=datetime.date(2020, 4, 1),
                purchase_cost=Decimal("500000.00"), disposed_date=datetime.date(2025, 6, 1),
                disposal_value=Decimal("50000.00"),
            )
            self.assertEqual(asset.written_down_value(datetime.date(2026, 1, 1)), Decimal("50000.00"))

    def test_financial_year_totals_include_income_and_expense_entries(self):
        from decimal import Decimal
        from .models.finance import FinancialYear, IncomeCategory, IncomeEntry, ExpenseCategory, ExpenseEntry

        with schema_context(self.tenant.schema_name):
            fy = FinancialYear.objects.create(
                label="2025-2026", start_date=datetime.date(2025, 4, 1), end_date=datetime.date(2026, 3, 31),
                opening_cash_balance=Decimal("1000.00"), opening_bank_balance=Decimal("2000.00"),
            )
            income_cat = IncomeCategory.objects.create(name="Donation")
            IncomeEntry.objects.create(
                category=income_cat, financial_year=fy, amount=Decimal("5000.00"),
                received_date=datetime.date(2025, 6, 1),
            )
            expense_cat = ExpenseCategory.objects.create(name="Rent")
            ExpenseEntry.objects.create(
                category=expense_cat, financial_year=fy, amount=Decimal("3000.00"),
                payment_date=datetime.date(2025, 7, 1),
            )
            self.assertEqual(fy.opening_balance, Decimal("3000.00"))
            self.assertEqual(fy.total_receipts(), Decimal("5000.00"))
            self.assertEqual(fy.total_payments(), Decimal("3000.00"))
            self.assertEqual(fy.closing_balance(), Decimal("5000.00"))

    def test_close_and_carry_forward_locks_year_and_sets_next_opening_balance(self):
        from decimal import Decimal
        from .models.finance import FinancialYear

        with schema_context(self.tenant.schema_name):
            fy = FinancialYear.objects.create(
                label="2024-2025", start_date=datetime.date(2024, 4, 1), end_date=datetime.date(2025, 3, 31),
                opening_cash_balance=Decimal("1000.00"),
            )
            next_fy = FinancialYear.objects.create(
                label="2025-2026", start_date=datetime.date(2025, 4, 1), end_date=datetime.date(2026, 3, 31),
            )
            fy.close_and_carry_forward(next_fy)
            fy.refresh_from_db()
            next_fy.refresh_from_db()
            self.assertTrue(fy.is_locked)
            self.assertIsNotNone(fy.locked_at)
            self.assertEqual(next_fy.opening_bank_balance, Decimal("1000.00"))

    def test_locked_financial_year_blocks_new_fee_payment(self):
        from decimal import Decimal
        from django.utils import timezone
        from .models.finance import FinancialYear
        from .models.fees import StudentFeeInvoice

        with schema_context(self.tenant.schema_name):
            today = timezone.now().date()
            FinancialYear.objects.create(
                label="Locked FY", start_date=today - datetime.timedelta(days=30),
                end_date=today + datetime.timedelta(days=30), is_locked=True,
            )
            student = User.objects.create_user(username="fee_stu_locked", email="fee_stu_locked@test.com")
            invoice = StudentFeeInvoice.objects.create(
                student=student, due_date=timezone.now().date(), total_amount=Decimal("5000.00"),
            )
            token = self._admin_token()

        response = self.client.post(
            reverse('fee-invoice-pay', args=[invoice.id]),
            {"amount_paid": 1000, "payment_method": "cash"}, format='json',
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("locked", response.data["error"].lower())

    def test_income_entry_serializer_rejects_locked_financial_year(self):
        from .models.finance import FinancialYear, IncomeCategory

        with schema_context(self.tenant.schema_name):
            fy = FinancialYear.objects.create(
                label="2024-2025", start_date=datetime.date(2024, 4, 1), end_date=datetime.date(2025, 3, 31),
                is_locked=True,
            )
            category = IncomeCategory.objects.create(name="Grant")
            token = self._admin_token()

        response = self.client.post(
            reverse('incomeentry-list'),
            {"category": category.id, "financial_year": fy.id, "amount": 1000, "received_date": "2024-06-01"},
            format='json', HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class CAAuditPortalTests(TenantTestCase):
    """P3/P4: the CA role's access gate (AuditEngagement/IsActiveAuditor),
    the RESTRICTED_ROLE_MODULES guard on audit-portal, and the report
    endpoints themselves."""

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ('Management', 'Faculty', 'CA'):
                Group.objects.get_or_create(name=role)

    def _admin_token(self):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username=f'ca_admin_{User.objects.count()}',
                email=f'ca_admin_{User.objects.count()}@test.com', password='pw12345!',
            )
            user.groups.add(Group.objects.get(name='Management'))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    def _financial_year(self):
        from .models.finance import FinancialYear
        return FinancialYear.objects.create(
            label=f"FY-{FinancialYear.objects.count()}",
            start_date=datetime.date(2025, 4, 1), end_date=datetime.date(2026, 3, 31),
        )

    def _auditor(self, fy, access_start, access_end, revoked=False):
        from django.utils import timezone
        from .models.audit_portal import AuditorProfile, AuditEngagement

        user = User.objects.create_user(
            username=f'ca_user_{User.objects.count()}', email=f'ca_user_{User.objects.count()}@test.com',
        )
        user.groups.add(Group.objects.get(name='CA'))
        profile = AuditorProfile.objects.create(user=user, firm_name="Test & Co.")
        engagement = AuditEngagement.objects.create(
            auditor=profile, financial_year=fy, access_start=access_start, access_end=access_end,
            revoked_at=timezone.now() if revoked else None,
        )
        token = RefreshToken.for_user(user)
        token['tenant_schema'] = self.tenant.schema_name
        return profile, engagement, token

    def test_invite_auditor_creates_profile_group_and_engagement(self):
        from .models.audit_portal import AuditorProfile, AuditEngagement

        with schema_context(self.tenant.schema_name):
            fy = self._financial_year()
            token = self._admin_token()

        response = self.client.post(
            reverse('audit-portal-invite-auditor'),
            {
                "email": "auditor@camail.example", "firm_name": "ABC & Associates",
                "icai_membership_number": "123456", "financial_year_id": fy.id,
                "access_start": "2025-04-01", "access_end": "2026-06-30",
            },
            format='json', HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        with schema_context(self.tenant.schema_name):
            self.assertTrue(AuditorProfile.objects.filter(user__email="auditor@camail.example").exists())
            self.assertTrue(User.objects.get(email="auditor@camail.example").groups.filter(name='CA').exists())
            self.assertEqual(AuditEngagement.objects.filter(financial_year=fy).count(), 1)

    def test_ca_user_can_actually_log_in_and_fetch_their_profile(self):
        """
        Regression test: the shared login serializer and UserProfileView both
        hardcode a role->profile mapping for every other role. Without a 'CA'
        branch in each, a CA account is created successfully by
        InviteAuditorView but can never actually log in (login serializer
        raises "does not have an associated profile") or, if that's patched
        without also patching UserProfileView, gets a 400 "User group not
        recognized" on the very next request after login. Exercises the real
        /login/ and /user/ endpoints — not RefreshToken.for_user(), which
        would silently skip this whole code path.
        """
        from .models.audit_portal import AuditorProfile

        with schema_context(self.tenant.schema_name):
            ca_user = User.objects.create_user(
                username='ca_login_test', email='ca_login_test@example.com', password='pw12345!',
            )
            ca_user.groups.add(Group.objects.get(name='CA'))
            AuditorProfile.objects.create(user=ca_user, firm_name="Login Test & Co.")

        login_response = self.client.post(
            reverse('token_obtain_pair'),
            {"username": "ca_login_test", "password": "pw12345!"}, format='json',
        )
        self.assertEqual(login_response.status_code, status.HTTP_200_OK)
        self.assertEqual(login_response.data["roleName"], "CA")
        access_token = login_response.data["access"]

        profile_response = self.client.get(
            reverse('user_profile'), HTTP_AUTHORIZATION=f'Bearer {access_token}',
        )
        self.assertEqual(profile_response.status_code, status.HTTP_200_OK)
        self.assertEqual(profile_response.data["role"], "CA")
        self.assertEqual(profile_response.data["firm_name"], "Login Test & Co.")

    def test_active_engagement_can_view_receipts_payments_report(self):
        with schema_context(self.tenant.schema_name):
            fy = self._financial_year()
            today = datetime.date.today()
            _, engagement, token = self._auditor(
                fy, today - datetime.timedelta(days=1), today + datetime.timedelta(days=30),
            )

        response = self.client.get(
            reverse('audit-portal-receipts-payments') + f"?financial_year={fy.id}",
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["financial_year"], fy.label)
        with schema_context(self.tenant.schema_name):
            from .models.audit_portal import AuditorAccessLog
            self.assertTrue(AuditorAccessLog.objects.filter(engagement=engagement, report_type="receipts_payments").exists())

    def test_expired_engagement_is_denied(self):
        with schema_context(self.tenant.schema_name):
            fy = self._financial_year()
            today = datetime.date.today()
            _, _, token = self._auditor(
                fy, today - datetime.timedelta(days=60), today - datetime.timedelta(days=30),
            )

        response = self.client.get(
            reverse('audit-portal-receipts-payments') + f"?financial_year={fy.id}",
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_revoked_engagement_is_denied(self):
        with schema_context(self.tenant.schema_name):
            fy = self._financial_year()
            today = datetime.date.today()
            _, _, token = self._auditor(
                fy, today - datetime.timedelta(days=1), today + datetime.timedelta(days=30), revoked=True,
            )

        response = self.client.get(
            reverse('audit-portal-receipts-payments') + f"?financial_year={fy.id}",
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_engagement_for_a_different_financial_year_is_denied(self):
        with schema_context(self.tenant.schema_name):
            fy = self._financial_year()
            other_fy = self._financial_year()
            today = datetime.date.today()
            _, _, token = self._auditor(
                fy, today - datetime.timedelta(days=1), today + datetime.timedelta(days=30),
            )

        response = self.client.get(
            reverse('audit-portal-receipts-payments') + f"?financial_year={other_fy.id}",
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_xlsx_export_returns_spreadsheet_content_type(self):
        with schema_context(self.tenant.schema_name):
            fy = self._financial_year()
            today = datetime.date.today()
            _, _, token = self._auditor(
                fy, today - datetime.timedelta(days=1), today + datetime.timedelta(days=30),
            )

        response = self.client.get(
            reverse('audit-portal-receipts-payments') + f"?financial_year={fy.id}&export=xlsx",
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def test_only_ca_group_may_ever_be_granted_audit_portal_module(self):
        """RESTRICTED_ROLE_MODULES: an Admin trying to hand `audit-portal` to
        any role other than CA must have it silently stripped, even if the
        tenant has the module subscribed.

        Posted via raw json.dumps rather than format='json' — Django's plain
        test Client (unlike DRF's APIClient) doesn't actually serialize
        list-valued fields as JSON under format='json', it falls back to
        multipart encoding, which turns allowed_modules into a single string
        instead of a list by the time the view sees it.
        """
        import json as _json

        with schema_context(self.tenant.schema_name):
            self.tenant.subscribed_modules = ['audit-portal']
            self.tenant.save()
            token = self._admin_token()

        response = self.client.post(
            reverse('role-module-permissions'),
            data=_json.dumps({"group_name": "Faculty", "allowed_modules": ["audit-portal"]}),
            content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertNotIn("audit-portal", response.data["allowed_modules"])

        response = self.client.post(
            reverse('role-module-permissions'),
            data=_json.dumps({"group_name": "CA", "allowed_modules": ["audit-portal"]}),
            content_type='application/json', HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("audit-portal", response.data["allowed_modules"])

    def test_my_engagements_lists_only_the_calling_auditors_own_engagements(self):
        with schema_context(self.tenant.schema_name):
            fy = self._financial_year()
            today = datetime.date.today()
            _, engagement, token = self._auditor(
                fy, today - datetime.timedelta(days=1), today + datetime.timedelta(days=30),
            )

        response = self.client.get(
            reverse('audit-portal-my-engagements'), HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data["engagements"]), 1)
        self.assertEqual(response.data["engagements"][0]["financial_year_label"], fy.label)
        self.assertTrue(response.data["engagements"][0]["is_active"])

    def test_my_engagements_rejects_non_ca_accounts(self):
        with schema_context(self.tenant.schema_name):
            token = self._admin_token()

        response = self.client.get(
            reverse('audit-portal-my-engagements'), HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class AccreditationReportingTests(TenantTestCase):
    """P5: AISHE / AICTE / NAAC quick-win reports — pure reporting over
    existing StudentProfile/TeachingStaffProfile/Program fields."""

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            Group.objects.get_or_create(name='Management')
            self.dept = Department.objects.create(name="Mechanical", code="MECH")

    def _admin_token(self):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username=f'accred_admin_{User.objects.count()}',
                email=f'accred_admin_{User.objects.count()}@test.com', password='pw12345!',
            )
            user.groups.add(Group.objects.get(name='Management'))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    def test_aishe_annual_return_counts_students_by_category(self):
        with schema_context(self.tenant.schema_name):
            for i, category in enumerate(["OBC", "OBC", "SC", "General"]):
                u = User.objects.create_user(username=f"aishe_stu{i}", email=f"aishe_stu{i}@test.com")
                StudentProfile.objects.create(
                    user=u, student_id=f"AISHE-{i}", department=self.dept, category=category,
                )
            token = self._admin_token()

        response = self.client.get(
            reverse('compliance-center-aishe'), HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_students"], 4)
        by_category = {r["category"]: r["count"] for r in response.data["enrolment_by_category"]}
        self.assertEqual(by_category["OBC"], 2)

    def test_aicte_disclosure_computes_student_faculty_ratio(self):
        from .models.profile import TeachingStaffProfile

        with schema_context(self.tenant.schema_name):
            for i in range(10):
                u = User.objects.create_user(username=f"aicte_stu{i}", email=f"aicte_stu{i}@test.com")
                StudentProfile.objects.create(user=u, student_id=f"AICTE-{i}", department=self.dept)
            faculty_user = User.objects.create_user(username="aicte_fac1", email="aicte_fac1@test.com")
            TeachingStaffProfile.objects.create(
                user=faculty_user, employee_id="FAC-1", department=self.dept, designation="Assistant Professor",
            )
            token = self._admin_token()

        response = self.client.get(
            reverse('compliance-center-aicte'), HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["total_students"], 10)
        self.assertEqual(response.data["total_faculty"], 1)
        self.assertEqual(response.data["student_faculty_ratio"], 10.0)

    def test_aishe_xlsx_export_returns_spreadsheet(self):
        with schema_context(self.tenant.schema_name):
            token = self._admin_token()

        response = self.client.get(
            reverse('compliance-center-aishe') + "?export=xlsx",
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response["Content-Type"],
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )


class EvidenceWorkspaceTests(TenantTestCase):
    """P6: NAAC SSR/AQAR Evidence Workspace — Draft -> Submitted -> Signed Off,
    and reusing a Phase 1 ComplianceCertificate instead of re-uploading."""

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ('Faculty', 'Department Head'):
                Group.objects.get_or_create(name=role)
            self.dept = Department.objects.create(name="Civil", code="CIV")

    def _token_for(self, role):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username=f'evidence_{role.replace(" ", "")}_{User.objects.count()}',
                email=f'evidence_{User.objects.count()}@test.com',
            )
            user.groups.add(Group.objects.get(name=role))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    def _criterion_and_year(self):
        from .models.compliance import AccreditationCriterion
        from .models.finance import FinancialYear

        criterion = AccreditationCriterion.objects.create(
            body=AccreditationCriterion.BODY_NAAC, code="1.1", title="Curricular Planning",
        )
        fy = FinancialYear.objects.create(
            label=f"AY-{FinancialYear.objects.count()}",
            start_date=datetime.date(2025, 6, 1), end_date=datetime.date(2026, 5, 31),
        )
        return criterion, fy

    def test_submit_then_sign_off_workflow(self):
        from .models.compliance import EvidenceItem

        with schema_context(self.tenant.schema_name):
            criterion, fy = self._criterion_and_year()
            item = EvidenceItem.objects.create(
                criterion=criterion, department=self.dept, financial_year=fy,
                description="Board of Studies minutes",
            )
            faculty_token = self._token_for('Faculty')
            hod_token = self._token_for('Department Head')

        submit_res = self.client.post(
            reverse('evidenceitem-submit', args=[item.id]),
            HTTP_AUTHORIZATION=f'Bearer {faculty_token.access_token}',
        )
        self.assertEqual(submit_res.status_code, status.HTTP_200_OK)
        self.assertEqual(submit_res.data["evidence"]["status"], EvidenceItem.STATUS_SUBMITTED)

        # A plain Faculty member cannot sign off their own submission.
        denied_res = self.client.post(
            reverse('evidenceitem-sign-off', args=[item.id]),
            HTTP_AUTHORIZATION=f'Bearer {faculty_token.access_token}',
        )
        self.assertEqual(denied_res.status_code, status.HTTP_403_FORBIDDEN)

        signoff_res = self.client.post(
            reverse('evidenceitem-sign-off', args=[item.id]),
            HTTP_AUTHORIZATION=f'Bearer {hod_token.access_token}',
        )
        self.assertEqual(signoff_res.status_code, status.HTTP_200_OK)
        self.assertEqual(signoff_res.data["evidence"]["status"], EvidenceItem.STATUS_SIGNED_OFF)

    def test_cannot_submit_an_already_submitted_item(self):
        from .models.compliance import EvidenceItem

        with schema_context(self.tenant.schema_name):
            criterion, fy = self._criterion_and_year()
            item = EvidenceItem.objects.create(
                criterion=criterion, financial_year=fy, status=EvidenceItem.STATUS_SUBMITTED,
            )
            token = self._token_for('Faculty')

        response = self.client.post(
            reverse('evidenceitem-submit', args=[item.id]),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_evidence_item_can_reuse_an_existing_compliance_certificate(self):
        from .models.compliance import EvidenceItem, ComplianceCertificateType, ComplianceCertificate

        with schema_context(self.tenant.schema_name):
            criterion, fy = self._criterion_and_year()
            cert_type = ComplianceCertificateType.objects.create(name="Fire Safety NOC")
            cert = ComplianceCertificate.objects.create(certificate_type=cert_type)
            item = EvidenceItem.objects.create(
                criterion=criterion, financial_year=fy, linked_certificate=cert,
                description="Reused Fire NOC as evidence for infra criterion",
            )
            self.assertEqual(item.linked_certificate_id, cert.id)


class StateComplianceAndScholarshipTests(TenantTestCase):
    """Missing-module additions: state-varying certificate catalog and
    state scholarship reconciliation, next to the Fees module."""

    def test_seed_command_creates_state_varying_certificate_types(self):
        from django.core.management import call_command
        from .models.compliance import ComplianceCertificateType

        with schema_context(self.tenant.schema_name):
            call_command('seed_compliance_certificate_types')
            professional_tax = ComplianceCertificateType.objects.filter(
                name__icontains="Professional Tax",
            ).first()
            self.assertIsNotNone(professional_tax)
            self.assertTrue(professional_tax.varies_by_state)
            # Safe to re-run — second call must not create duplicates.
            call_command('seed_compliance_certificate_types')
            self.assertEqual(
                ComplianceCertificateType.objects.filter(name__icontains="Professional Tax").count(), 1,
            )

    def test_seed_command_creates_naac_and_nba_criteria(self):
        from django.core.management import call_command
        from .models.compliance import AccreditationCriterion

        with schema_context(self.tenant.schema_name):
            call_command('seed_accreditation_criteria')
            self.assertTrue(AccreditationCriterion.objects.filter(body='NAAC', code='1.1').exists())
            self.assertTrue(AccreditationCriterion.objects.filter(body='NBA', code='3').exists())

    def test_scholarship_record_reconciliation_gap(self):
        from decimal import Decimal
        from .models.finance import FinancialYear
        from .models.scholarship import StateScholarshipScheme, StudentScholarshipRecord

        with schema_context(self.tenant.schema_name):
            fy = FinancialYear.objects.create(
                label="2025-2026", start_date=datetime.date(2025, 4, 1), end_date=datetime.date(2026, 3, 31),
            )
            scheme = StateScholarshipScheme.objects.create(name="Maharashtra EBC Scholarship", state="Maharashtra")
            student = User.objects.create_user(username="scholar1", email="scholar1@test.com")
            record = StudentScholarshipRecord.objects.create(
                student=student, scheme=scheme, financial_year=fy,
                sanctioned_amount=Decimal("20000.00"), disbursed_amount=Decimal("12000.00"),
            )
            self.assertEqual(record.reconciliation_gap, Decimal("8000.00"))


class NBAAttainmentRollupTests(TenantTestCase):
    """P7 completion: class-level CO attainment and its roll-up to PO
    attainment via the CO-PO correlation matrix — the piece the original
    plan flagged as genuinely new work and the one this session added."""

    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            for role in ('Management',):
                Group.objects.get_or_create(name=role)
            self.dept = Department.objects.create(name="Electronics", code="ECE")

    def _admin_token(self):
        with schema_context(self.tenant.schema_name):
            user = User.objects.create_user(
                username=f'nba_admin_{User.objects.count()}',
                email=f'nba_admin_{User.objects.count()}@test.com', password='pw12345!',
            )
            user.groups.add(Group.objects.get(name='Management'))
            token = RefreshToken.for_user(user)
            token['tenant_schema'] = self.tenant.schema_name
        return token

    def _program_and_course(self):
        from .models.academics import Program, Regulation
        from .models.course import Course
        from .services.academics import get_default_grading_scheme

        program = Program.objects.create(name="B.Tech Electronics", code="BTECE", department=self.dept)
        regulation = Regulation.objects.create(
            program=program, code="R2021NBA", effective_from_year=2018,
            grading_scheme=get_default_grading_scheme(),
        )
        course = Course.objects.create(
            course_code="EC301", course_name="Signals & Systems", department=self.dept,
            regulation=regulation, semester_number=3, credits=4,
        )
        return program, course

    def _evaluated_paper(self, course, student, co_code, obtained, max_marks=10):
        from .models.valuation import ScannedPaper, ValuationSession
        from .models.exam import Exam, ExamType
        from .models.profile import TeachingStaffProfile
        from django.utils import timezone

        exam_type = ExamType.objects.create(name="Mid", code=f"NBA{ScannedPaper.objects.count()}")
        exam = Exam.objects.create(
            name="NBA Attainment Exam", exam_type=exam_type, department=self.dept, course=course,
            date="2026-11-01", start_time="09:00", end_time="12:00",
            question_structure={"Q1": {"marks": max_marks, "course_outcome": co_code}},
        )
        evaluator_user = User.objects.create_user(
            username=f"nba_eval{ScannedPaper.objects.count()}", email=f"nba_eval{ScannedPaper.objects.count()}@test.com",
        )
        evaluator = TeachingStaffProfile.objects.create(
            user=evaluator_user, employee_id=f"NBAEMP-{ScannedPaper.objects.count()}", department=self.dept,
        )
        session = ValuationSession.objects.create(exam=exam, evaluator=evaluator)
        return ScannedPaper.objects.create(
            session=session, student=student, scanned_file_url="s3://x",
            status="Evaluated", evaluated_at=timezone.now(), question_scores={"Q1": obtained},
        )

    def _student(self, username):
        user = User.objects.create_user(username=username, email=f"{username}@test.com")
        return StudentProfile.objects.create(user=user, student_id=f"NBA-{username}", department=self.dept)

    def test_class_level_co_attainment_and_po_rollup(self):
        from .models.outcomes import CourseOutcome, ProgramOutcome, POCOMapping
        from .services.outcome_attainment import (
            compute_course_outcome_class_attainment, compute_program_outcome_attainment,
        )

        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()
            co1 = CourseOutcome.objects.create(
                course=course, code="CO1", statement="Analyse signals",
                target_attainment_percent=50, target_student_percent=60,
            )
            co2 = CourseOutcome.objects.create(
                course=course, code="CO2", statement="Design systems",
                target_attainment_percent=50, target_student_percent=60,
            )
            po1 = ProgramOutcome.objects.create(program=program, code="PO1", statement="Engineering knowledge")
            POCOMapping.objects.create(course_outcome=co1, program_outcome=po1, strength=3)
            POCOMapping.objects.create(course_outcome=co2, program_outcome=po1, strength=1)

            # CO1: 2 of 3 students clear the 50% per-student threshold (80%, 80%, 40%).
            s1, s2, s3 = self._student("nba_s1"), self._student("nba_s2"), self._student("nba_s3")
            self._evaluated_paper(course, s1, "CO1", obtained=8)
            self._evaluated_paper(course, s2, "CO1", obtained=8)
            self._evaluated_paper(course, s3, "CO1", obtained=4)
            # CO2: none of the 3 students clear 50% (40% each).
            self._evaluated_paper(course, s1, "CO2", obtained=4)
            self._evaluated_paper(course, s2, "CO2", obtained=4)
            self._evaluated_paper(course, s3, "CO2", obtained=4)

            co_results = compute_course_outcome_class_attainment(course.id)
            co1_result = next(r for r in co_results if r["code"] == "CO1")
            co2_result = next(r for r in co_results if r["code"] == "CO2")

            self.assertEqual(co1_result["students_considered"], 3)
            self.assertEqual(co1_result["students_meeting_target"], 2)
            self.assertAlmostEqual(co1_result["class_percent_meeting_target"], 66.67, delta=0.1)
            self.assertTrue(co1_result["attained"])  # 66.67% >= 60% target_student_percent

            self.assertEqual(co2_result["students_meeting_target"], 0)
            self.assertEqual(co2_result["class_percent_meeting_target"], 0.0)
            self.assertFalse(co2_result["attained"])

            po_results = compute_program_outcome_attainment(program.id)
            po1_result = next(r for r in po_results if r["code"] == "PO1")
            # Weighted by strength: (66.67*3 + 0*1) / (3+1) = 50.0
            self.assertAlmostEqual(po1_result["attainment_percent"], 50.0, delta=0.1)
            self.assertEqual(len(po1_result["contributing_course_outcomes"]), 2)

    def test_program_outcome_attainment_endpoint_and_csv_export(self):
        from .models.outcomes import CourseOutcome, ProgramOutcome, POCOMapping

        with schema_context(self.tenant.schema_name):
            program, course = self._program_and_course()
            co1 = CourseOutcome.objects.create(
                course=course, code="CO1", statement="X", target_attainment_percent=50, target_student_percent=50,
            )
            po1 = ProgramOutcome.objects.create(program=program, code="PO1", statement="Y")
            POCOMapping.objects.create(course_outcome=co1, program_outcome=po1, strength=2)
            student = self._student("nba_endpoint_stu")
            self._evaluated_paper(course, student, "CO1", obtained=9)
            token = self._admin_token()

        response = self.client.get(
            reverse('program-outcome-attainment', args=[program.id]),
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        po1_data = next(r for r in response.data["program_outcomes"] if r["code"] == "PO1")
        self.assertEqual(po1_data["attainment_percent"], 100.0)

        csv_response = self.client.get(
            reverse('program-outcome-attainment', args=[program.id]) + "?export=csv",
            HTTP_AUTHORIZATION=f'Bearer {token.access_token}',
        )
        self.assertEqual(csv_response.status_code, status.HTTP_200_OK)
        self.assertEqual(csv_response["Content-Type"], "text/csv")

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

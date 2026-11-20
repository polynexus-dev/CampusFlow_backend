"""
Gap closure Phase 1 (Docs/college_gap_closure_plan.md):
  1.0 multi-source CO attainment (services/co_evidence.py)
  1.1 certificates & ID cards
  1.2 rubrics
  1.3 LMS content library
"""
import datetime
from decimal import Decimal

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from django_tenants.test.cases import TenantTestCase
from django_tenants.utils import schema_context
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from .models import (
    AcademicYear, Assignment, AssignmentSubmission, Batch, ClearanceDesk, Course, CourseOffering,
    CourseOutcome, Department, Program, Regulation, Term,
)
from .models.certificates import CertificateTemplate, IssuedCertificate
from .models.lms import CourseModule, LearningResource, ResourceView
from .models.offerings import StudentCourseRegistration
from .models.profile import StudentProfile, TeachingStaffProfile
from .models.rubrics import Rubric, RubricAssessment, RubricCriterion, RubricLevel, RubricScore
from .services.co_evidence import collect_course_evidence
from .services.outcome_attainment import compute_course_outcome_class_attainment

PASSWORD = "pw12345!"
JSON = "application/json"


class _Phase1Fixture:
    def _build(self):
        self.cse = Department.objects.create(name="Computer Science", code="CSE")
        self.admin = self._user("p1_admin", "Administrator")
        self.faculty = self._user("p1_faculty", "Faculty", first_name="Asha", last_name="Rao")
        TeachingStaffProfile.objects.create(user=self.faculty, employee_id="P1-FAC", department=self.cse, status="active")
        self.other_faculty = self._user("p1_faculty2", "Faculty")
        TeachingStaffProfile.objects.create(user=self.other_faculty, employee_id="P1-FAC2", department=self.cse, status="active")

        self.student_a = self._student("p1_stu_a", first_name="Ravi", last_name="Kumar")
        self.student_b = self._student("p1_stu_b")
        self.outsider = self._student("p1_stu_c")

        year = AcademicYear.objects.create(
            name="2026-2027", start_date=datetime.date(2026, 7, 1), end_date=datetime.date(2027, 6, 30),
            is_current=True,
        )
        today = datetime.date.today()
        self.term = Term.objects.create(
            academic_year=year, name="Odd", kind=Term.KIND_ODD, sequence=1,
            start_date=today - datetime.timedelta(days=30), end_date=today + datetime.timedelta(days=90),
            is_current=True,
        )
        program = Program.objects.create(name="B.Tech CSE", code="P1CSE", department=self.cse)
        regulation = Regulation.objects.create(program=program, code="P1R26", effective_from_year=2026)
        batch = Batch.objects.create(program=program, regulation=regulation, admission_year=2026, name="2026-2030")
        self.course = Course.objects.create(course_code="CS310", course_name="Operating Systems", department=self.cse)
        self.other_course = Course.objects.create(course_code="CS320", course_name="Networks", department=self.cse)
        self.offering = CourseOffering.objects.create(
            course=self.course, term=self.term, batch=batch, faculty=self.faculty, is_active=True,
        )
        for student in (self.student_a, self.student_b):
            StudentCourseRegistration.objects.create(student=student, offering=self.offering, term=self.term)

        self.co1 = CourseOutcome.objects.create(
            course=self.course, code="CO1", statement="Explain scheduling",
            target_attainment_percent=60, target_student_percent=50,
        )
        self.foreign_co = CourseOutcome.objects.create(
            course=self.other_course, code="CO1", statement="Explain routing",
            target_attainment_percent=60, target_student_percent=50,
        )

    def _user(self, username, role, **extra):
        user = User.objects.create_user(username=username, password=PASSWORD, **extra)
        user.groups.add(Group.objects.get_or_create(name=role)[0])
        return user

    def _student(self, username, **extra):
        user = self._user(username, "student", **extra)
        return StudentProfile.objects.create(
            user=user, student_id=username.upper(), department=self.cse, status="active",
            program_enrolled_in="B.Tech CSE", current_semester_year="Semester 5",
        )

    def _auth(self, user):
        with schema_context(self.tenant.schema_name):
            token = RefreshToken.for_user(user)
        token["tenant_schema"] = self.tenant.schema_name
        return {"HTTP_AUTHORIZATION": f"Bearer {token.access_token}"}

    def _rubric(self, with_co=True):
        rubric = Rubric.objects.create(name="Lab rubric", course=self.course, applies_to=Rubric.APPLIES_LAB, created_by=self.faculty)
        criterion = RubricCriterion.objects.create(
            rubric=rubric, title="Implementation", course_outcome=self.co1 if with_co else None, weight=2,
        )
        levels = {
            label: RubricLevel.objects.create(criterion=criterion, label=label, score=score)
            for label, score in (("Excellent", 4), ("Good", 3), ("Poor", 1))
        }
        return rubric, criterion, levels


# ── 1.0 CO evidence ─────────────────────────────────────────────────────────

class COEvidenceTests(_Phase1Fixture, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build()

    def _assignment_marks(self, student, marks, max_marks=10, co=None):
        assignment = Assignment.objects.create(
            title=f"A-{student.student_id}-{marks}", description="d", department=self.cse, course=self.course,
            due_date=timezone.now(), created_by=self.faculty, course_outcome=co or self.co1, max_marks=max_marks,
        )
        AssignmentSubmission.objects.create(assignment=assignment, student=student.user, marks_obtained=marks, grade="x")
        return assignment

    def test_assignment_and_rubric_evidence_combine(self):
        with schema_context(self.tenant.schema_name):
            # student_a: assignment 8/10 + rubric Excellent (4*2 of 4*2) => pooled 16/18 = 88.9%
            # student_b: assignment 2/10 + rubric Poor (1*2 of 4*2)      => pooled 4/18  = 22.2%
            self._assignment_marks(self.student_a, 8)
            self._assignment_marks(self.student_b, 2)
            rubric, criterion, levels = self._rubric()
            for student, level in ((self.student_a, "Excellent"), (self.student_b, "Poor")):
                assessment = RubricAssessment.objects.create(rubric=rubric, student=student, evaluator=self.faculty)
                RubricScore.objects.create(assessment=assessment, criterion=criterion, level=levels[level])

            sources = {e.source for e in collect_course_evidence(self.course.id)}
            self.assertEqual(sources, {"assignment", "rubric"})

            result = compute_course_outcome_class_attainment(self.course.id)
            co = next(r for r in result if r["code"] == "CO1")
            self.assertEqual(co["students_considered"], 2)
            self.assertEqual(co["students_meeting_target"], 1)  # only student_a clears 60%
            self.assertEqual(co["class_percent_meeting_target"], 50.0)
            self.assertTrue(co["attained"])
            self.assertEqual(set(co["source_breakdown"]), {"assignment", "rubric"})
            self.assertEqual(co["source_breakdown"]["assignment"]["average_percent"], 50.0)

    def test_weights_change_per_student_percentage(self):
        with schema_context(self.tenant.schema_name):
            # student_a: assignment 10/10 (100%), rubric Poor (25%).
            self._assignment_marks(self.student_a, 10)
            rubric, criterion, levels = self._rubric()
            assessment = RubricAssessment.objects.create(rubric=rubric, student=self.student_a, evaluator=self.faculty)
            RubricScore.objects.create(assessment=assessment, criterion=criterion, level=levels["Poor"])

            # Pooled: (10 + 2) / (10 + 8) = 66.7% -> clears 60%.
            pooled = compute_course_outcome_class_attainment(self.course.id)[0]
            self.assertEqual(pooled["students_meeting_target"], 1)
            # Rubric-heavy: 0.2*100 + 0.8*25 = 40% -> does not clear 60%.
            weighted = compute_course_outcome_class_attainment(
                self.course.id, weights={"assignment": 0.2, "rubric": 0.8},
            )[0]
            self.assertEqual(weighted["students_meeting_target"], 0)

    def test_untagged_or_unmarked_assignments_are_ignored(self):
        with schema_context(self.tenant.schema_name):
            assignment = Assignment.objects.create(
                title="untagged", description="d", department=self.cse, course=self.course,
                due_date=timezone.now(), created_by=self.faculty, max_marks=10,
            )
            AssignmentSubmission.objects.create(assignment=assignment, student=self.student_a.user, marks_obtained=9)
            tagged = self._assignment_marks(self.student_b, 5)
            AssignmentSubmission.objects.filter(assignment=tagged).update(marks_obtained=None)
            self.assertEqual(list(collect_course_evidence(self.course.id)), [])


class AssignmentOBEApiTests(_Phase1Fixture, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self.tenant.subscribed_modules = ["assignments"]
            self.tenant.save(update_fields=["subscribed_modules"])
            self._build()

    def _create(self, **extra):
        data = {
            "title": "Scheduling", "description": "Simulate RR", "due_date": "2026-12-01T10:00:00+05:30",
            "department_id": self.cse.id, "course_id": self.course.id, **extra,
        }
        return self.client.post(reverse("assignment-list-create"), data, **self._auth(self.faculty))

    def test_course_outcome_must_belong_to_course(self):
        response = self._create(course_outcome_id=self.foreign_co.id, max_marks="10")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_numeric_marks_are_validated_and_stored(self):
        response = self._create(course_outcome_id=self.co1.id, max_marks="10")
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        assignment_id = response.data["id"]
        with schema_context(self.tenant.schema_name):
            submission = AssignmentSubmission.objects.create(
                assignment_id=assignment_id, student=self.student_a.user, text_submission="answer",
            )

        too_high = self.client.post(
            reverse("submission-grade", args=[submission.id]), {"marks_obtained": "11"},
            content_type=JSON, **self._auth(self.faculty),
        )
        self.assertEqual(too_high.status_code, status.HTTP_400_BAD_REQUEST)

        ok = self.client.post(
            reverse("submission-grade", args=[submission.id]), {"marks_obtained": "7.5"},
            content_type=JSON, **self._auth(self.faculty),
        )
        self.assertEqual(ok.status_code, status.HTTP_200_OK, ok.content)
        self.assertEqual(ok.data["grade"], "7.5/10.00")
        with schema_context(self.tenant.schema_name):
            submission.refresh_from_db()
            self.assertEqual(submission.marks_obtained, Decimal("7.5"))
            self.assertEqual(len(list(collect_course_evidence(self.course.id))), 1)


# ── 1.1 Certificates ────────────────────────────────────────────────────────

class CertificateTests(_Phase1Fixture, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build()

    def _templates(self):
        response = self.client.get(reverse("certificatetemplate-list"), **self._auth(self.admin))
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return {t["cert_type"]: t for t in response.data}

    def test_default_templates_are_seeded(self):
        templates = self._templates()
        self.assertIn("bonafide", templates)
        self.assertTrue(templates["leaving"]["requires_final_clearance"])

    def test_request_approve_pdf_verify_and_revoke(self):
        bonafide = self._templates()["bonafide"]
        response = self.client.post(
            reverse("certificaterequest-list"), {"template": bonafide["id"], "purpose": "Bank loan"},
            content_type=JSON, **self._auth(self.student_a.user),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        request_id = response.data["id"]

        duplicate = self.client.post(
            reverse("certificaterequest-list"), {"template": bonafide["id"]},
            content_type=JSON, **self._auth(self.student_a.user),
        )
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

        # A student can't approve their own request.
        denied = self.client.post(
            reverse("certificaterequest-approve", args=[request_id]), {}, content_type=JSON,
            **self._auth(self.student_a.user),
        )
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

        approved = self.client.post(
            reverse("certificaterequest-approve", args=[request_id]), {}, content_type=JSON,
            **self._auth(self.admin),
        )
        self.assertEqual(approved.status_code, status.HTTP_201_CREATED, approved.content)
        self.assertIn("Ravi Kumar", approved.data["rendered_body"])
        self.assertIn("Bank loan", approved.data["rendered_body"])
        certificate_id = approved.data["id"]

        pdf = self.client.get(reverse("issuedcertificate-pdf", args=[certificate_id]), **self._auth(self.student_a.user))
        self.assertEqual(pdf.status_code, status.HTTP_200_OK)
        self.assertEqual(pdf["Content-Type"], "application/pdf")
        self.assertTrue(pdf.content.startswith(b"%PDF"))

        # Another student can't see it.
        other = self.client.get(reverse("issuedcertificate-detail", args=[certificate_id]), **self._auth(self.student_b.user))
        self.assertEqual(other.status_code, status.HTTP_404_NOT_FOUND)

        with schema_context(self.tenant.schema_name):
            token = IssuedCertificate.objects.get(pk=certificate_id).verification_token
        verify_url = reverse("certificate-verify", args=[self.tenant.schema_name, token])
        verified = self.client.get(verify_url)  # no auth
        self.assertEqual(verified.status_code, status.HTTP_200_OK)
        self.assertTrue(verified.data["valid"])
        self.assertNotIn("date_of_birth", verified.data)

        revoked = self.client.post(
            reverse("issuedcertificate-revoke", args=[certificate_id]), {"reason": "Issued in error"},
            content_type=JSON, **self._auth(self.admin),
        )
        self.assertEqual(revoked.status_code, status.HTTP_200_OK)
        self.assertFalse(self.client.get(verify_url).data["valid"])

    def test_unknown_token_and_public_schema_are_not_found(self):
        import uuid
        response = self.client.get(reverse("certificate-verify", args=[self.tenant.schema_name, uuid.uuid4()]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        response = self.client.get(reverse("certificate-verify", args=["public", uuid.uuid4()]))
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_leaving_certificate_waits_for_final_clearance(self):
        leaving = self._templates()["leaving"]
        with schema_context(self.tenant.schema_name):
            ClearanceDesk.objects.create(
                name="Library", code="library", responsible_group=Group.objects.get_or_create(name="Librarian")[0], order=1,
            )
        response = self.client.post(
            reverse("issuedcertificate-list"), {"template": leaving["id"], "student": self.student_a.id},
            content_type=JSON, **self._auth(self.admin),
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("clearance", response.data["error"])

    def test_placeholders_cannot_reach_attributes(self):
        with schema_context(self.tenant.schema_name):
            template = CertificateTemplate.objects.create(
                name="Probe", title="T", body_text="{student_name} {student_name.__class__} {nope} {conduct}",
            )
        response = self.client.post(
            reverse("issuedcertificate-list"),
            {"template": template.id, "student": self.student_a.id, "extra_context": {"conduct": "Good", "bad key": "x"}},
            content_type=JSON, **self._auth(self.admin),
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        self.assertEqual(response.data["rendered_body"], "Ravi Kumar {student_name.__class__} {nope} Good")

    def test_id_cards_pdf(self):
        response = self.client.get(
            reverse("student-id-cards") + f"?department={self.cse.id}", **self._auth(self.admin),
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.content.startswith(b"%PDF"))

        no_filter = self.client.get(reverse("student-id-cards"), **self._auth(self.admin))
        self.assertEqual(no_filter.status_code, status.HTTP_400_BAD_REQUEST)

        own = self.client.get(reverse("student-id-cards"), **self._auth(self.student_a.user))
        self.assertEqual(own.status_code, status.HTTP_200_OK)

        faculty = self.client.get(reverse("student-id-cards") + f"?department={self.cse.id}", **self._auth(self.faculty))
        self.assertEqual(faculty.status_code, status.HTTP_403_FORBIDDEN)


# ── 1.2 Rubrics ─────────────────────────────────────────────────────────────

class RubricApiTests(_Phase1Fixture, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build()

    def _rubric_payload(self, course=None, co=None):
        course = course or self.course
        return {
            "name": "Mini project", "course": course.id, "applies_to": "project",
            "criteria": [
                {"title": "Design", "course_outcome": (co or self.co1).id, "weight": "1",
                 "levels": [{"label": "Excellent", "score": "5"}, {"label": "Fair", "score": "2"}]},
                {"title": "Report", "weight": "1",
                 "levels": [{"label": "Excellent", "score": "5"}, {"label": "Fair", "score": "2"}]},
            ],
        }

    def test_create_assess_and_freeze(self):
        response = self.client.post(reverse("rubric-list"), self._rubric_payload(), content_type=JSON, **self._auth(self.faculty))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        rubric = response.data
        self.assertEqual(rubric["max_score"], 10.0)
        design, report = rubric["criteria"]
        design_excellent = next(l for l in design["levels"] if l["label"] == "Excellent")
        report_fair = next(l for l in report["levels"] if l["label"] == "Fair")

        missing = self.client.post(reverse("rubricassessment-list"), {
            "rubric": rubric["id"], "student": self.student_a.id,
            "scores": [{"criterion": design["id"], "level": design_excellent["id"]}],
        }, content_type=JSON, **self._auth(self.faculty))
        self.assertEqual(missing.status_code, status.HTTP_400_BAD_REQUEST)

        wrong_level = self.client.post(reverse("rubricassessment-list"), {
            "rubric": rubric["id"], "student": self.student_a.id,
            "scores": [{"criterion": design["id"], "level": report_fair["id"]},
                       {"criterion": report["id"], "level": report_fair["id"]}],
        }, content_type=JSON, **self._auth(self.faculty))
        self.assertEqual(wrong_level.status_code, status.HTTP_400_BAD_REQUEST)

        ok = self.client.post(reverse("rubricassessment-list"), {
            "rubric": rubric["id"], "student": self.student_a.id, "context_label": "Mini project review 1",
            "scores": [{"criterion": design["id"], "level": design_excellent["id"]},
                       {"criterion": report["id"], "level": report_fair["id"]}],
        }, content_type=JSON, **self._auth(self.faculty))
        self.assertEqual(ok.status_code, status.HTTP_201_CREATED, ok.content)
        self.assertEqual(Decimal(ok.data["total_score"]), Decimal("7"))
        self.assertEqual(Decimal(ok.data["max_score"]), Decimal("10"))

        # Only the CO-tagged "Design" criterion counts toward CO1: 5/5.
        with schema_context(self.tenant.schema_name):
            co = compute_course_outcome_class_attainment(self.course.id)[0]
            self.assertEqual(co["source_breakdown"]["rubric"]["average_percent"], 100.0)

        frozen = self.client.patch(
            reverse("rubric-detail", args=[rubric["id"]]), self._rubric_payload(), content_type=JSON,
            **self._auth(self.faculty),
        )
        self.assertEqual(frozen.status_code, status.HTTP_400_BAD_REQUEST)
        renamed = self.client.patch(
            reverse("rubric-detail", args=[rubric["id"]]), {"name": "Mini project v2"}, content_type=JSON,
            **self._auth(self.faculty),
        )
        self.assertEqual(renamed.status_code, status.HTTP_200_OK)

        mine = self.client.get(reverse("rubricassessment-list"), **self._auth(self.student_a.user))
        self.assertEqual(len(mine.data), 1)
        theirs = self.client.get(reverse("rubricassessment-list"), **self._auth(self.student_b.user))
        self.assertEqual(len(theirs.data), 0)

    def test_co_must_match_course_and_faculty_must_teach_it(self):
        bad_co = self.client.post(
            reverse("rubric-list"), self._rubric_payload(co=self.foreign_co), content_type=JSON, **self._auth(self.faculty),
        )
        self.assertEqual(bad_co.status_code, status.HTTP_400_BAD_REQUEST)

        not_taught = self.client.post(
            reverse("rubric-list"), self._rubric_payload(course=self.other_course, co=self.foreign_co),
            content_type=JSON, **self._auth(self.faculty),
        )
        self.assertEqual(not_taught.status_code, status.HTTP_403_FORBIDDEN)

    def test_students_cannot_create_rubrics(self):
        response = self.client.post(reverse("rubric-list"), self._rubric_payload(), content_type=JSON, **self._auth(self.student_a.user))
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


# ── 1.3 LMS ─────────────────────────────────────────────────────────────────

class LMSApiTests(_Phase1Fixture, TenantTestCase):
    def setUp(self):
        super().setUp()
        with schema_context(self.tenant.schema_name):
            self._build()

    def _module(self, user=None):
        return self.client.post(
            reverse("lms-module-list"), {"offering": self.offering.id, "title": "Unit 1: Processes"},
            content_type=JSON, **self._auth(user or self.faculty),
        )

    def test_only_offering_faculty_manage_content(self):
        self.assertEqual(self._module(self.other_faculty).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._module(self.student_a.user).status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(self._module().status_code, status.HTTP_201_CREATED)
        self.assertEqual(self._module(self.admin).status_code, status.HTTP_201_CREATED)

    def test_students_see_released_content_of_registered_offerings_only(self):
        module_id = self._module().data["id"]
        auth = self._auth(self.faculty)
        published = self.client.post(reverse("lms-resource-list"), {
            "module": module_id, "title": "Lecture video", "resource_type": "video_url",
            "url": "https://youtu.be/abc",
        }, content_type=JSON, **auth)
        self.assertEqual(published.status_code, status.HTTP_201_CREATED, published.content)
        future = (timezone.now() + datetime.timedelta(days=3)).isoformat()
        self.client.post(reverse("lms-resource-list"), {
            "module": module_id, "title": "Next week", "resource_type": "note", "body": "Soon", "release_at": future,
        }, content_type=JSON, **auth)
        self.client.post(reverse("lms-resource-list"), {
            "module": module_id, "title": "Draft", "resource_type": "note", "body": "WIP", "is_published": False,
        }, content_type=JSON, **auth)
        bad_link = self.client.post(reverse("lms-resource-list"), {
            "module": module_id, "title": "Bad", "resource_type": "link", "url": "javascript:alert(1)",
        }, content_type=JSON, **auth)
        self.assertEqual(bad_link.status_code, status.HTTP_400_BAD_REQUEST)

        faculty_view = self.client.get(reverse("lms-resource-list") + f"?module={module_id}", **auth)
        self.assertEqual(len(faculty_view.data), 3)

        student_view = self.client.get(reverse("lms-resource-list") + f"?module={module_id}", **self._auth(self.student_a.user))
        self.assertEqual([r["title"] for r in student_view.data], ["Lecture video"])
        modules = self.client.get(reverse("lms-module-list"), **self._auth(self.student_a.user))
        self.assertEqual(len(modules.data[0]["resources"]), 1)

        outsider = self.client.get(reverse("lms-module-list"), **self._auth(self.outsider.user))
        self.assertEqual(outsider.data, [])

        offerings = self.client.get(reverse("lms-my-offerings"), **self._auth(self.student_a.user))
        self.assertEqual([o["course_code"] for o in offerings.data], ["CS310"])

    def test_file_upload_and_view_tracking(self):
        module_id = self._module().data["id"]
        upload = SimpleUploadedFile("notes.pdf", b"%PDF-1.4 test", content_type="application/pdf")
        response = self.client.post(reverse("lms-resource-list"), {
            "module": module_id, "title": "Notes", "resource_type": "file", "file": upload,
        }, **self._auth(self.faculty))
        self.assertEqual(response.status_code, status.HTTP_201_CREATED, response.content)
        resource_id = response.data["id"]

        for _ in range(2):
            viewed = self.client.post(reverse("lms-resource-view", args=[resource_id]), **self._auth(self.student_a.user))
            self.assertEqual(viewed.status_code, status.HTTP_200_OK)
        with schema_context(self.tenant.schema_name):
            self.assertEqual(ResourceView.objects.get(resource_id=resource_id).view_count, 2)

        engagement = self.client.get(reverse("lms-resource-engagement", args=[resource_id]), **self._auth(self.faculty))
        self.assertEqual(engagement.data["registered"], 2)
        self.assertEqual(engagement.data["viewed"], 1)

        denied = self.client.get(reverse("lms-resource-engagement", args=[resource_id]), **self._auth(self.student_a.user))
        self.assertEqual(denied.status_code, status.HTTP_403_FORBIDDEN)

    def test_lecture_meeting_link_in_serializer(self):
        from .serializers import LectureSerializer
        self.assertIn("meeting_url", LectureSerializer.Meta.fields)

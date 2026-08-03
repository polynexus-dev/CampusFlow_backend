from django.core.management.base import BaseCommand
from django_tenants.utils import tenant_context
from tenants.models import Tenant
from campusflow_app.models.compliance import AccreditationCriterion

# Standard, publicly-published NAAC criteria/key-indicator framework (Affiliated/
# Constituent College manual) and NBA's Tier-I SAR criteria for UG programs.
# Same rationale as the P1 certificate-type seed: colleges shouldn't have to
# type out the criteria catalog by hand before the Evidence Workspace is usable.
# Safe to re-run — only creates missing rows.
NAAC_CRITERIA = [
    ("1.1", "Curricular Planning and Implementation"),
    ("1.2", "Academic Flexibility"),
    ("1.3", "Curriculum Enrichment"),
    ("1.4", "Feedback System"),
    ("2.1", "Student Enrolment and Profile"),
    ("2.2", "Catering to Student Diversity"),
    ("2.3", "Teaching-Learning Process"),
    ("2.4", "Teacher Profile and Quality"),
    ("2.5", "Evaluation Process and Reforms"),
    ("2.6", "Student Performance and Learning Outcomes"),
    ("2.7", "Student Satisfaction Survey"),
    ("3.1", "Resource Mobilization for Research"),
    ("3.2", "Innovation Ecosystem"),
    ("3.3", "Research Publications and Awards"),
    ("3.4", "Extension Activities"),
    ("3.5", "Collaboration"),
    ("4.1", "Physical Facilities"),
    ("4.2", "Library as a Learning Resource"),
    ("4.3", "IT Infrastructure"),
    ("4.4", "Maintenance of Campus Infrastructure"),
    ("5.1", "Student Support"),
    ("5.2", "Student Progression"),
    ("5.3", "Student Participation and Activities"),
    ("5.4", "Alumni Engagement"),
    ("6.1", "Institutional Vision and Leadership"),
    ("6.2", "Strategy Development and Deployment"),
    ("6.3", "Faculty Empowerment Strategies"),
    ("6.4", "Financial Management and Resource Mobilization"),
    ("6.5", "Internal Quality Assurance System"),
    ("7.1", "Institutional Values and Social Responsibilities"),
    ("7.2", "Best Practices"),
    ("7.3", "Institutional Distinctiveness"),
]

NBA_CRITERIA = [
    ("1", "Vision, Mission and Program Educational Objectives"),
    ("2", "Program Curriculum and Teaching-Learning Processes"),
    ("3", "Course Outcomes and Program Outcomes"),
    ("4", "Students' Performance"),
    ("5", "Faculty Information and Contributions"),
    ("6", "Facilities and Technical Support"),
    ("7", "Continuous Improvement"),
    ("8", "First Year Academics"),
    ("9", "Student Support Systems"),
]


class Command(BaseCommand):
    help = "Seeds the AccreditationCriterion catalog with the standard NAAC key-indicator and NBA Tier-I SAR criteria, for every tenant schema. Safe to re-run — only creates missing rows."

    def handle(self, *args, **options):
        tenants = Tenant.objects.exclude(schema_name='public')

        for tenant in tenants:
            with tenant_context(tenant):
                created_count = 0
                for body, catalog in (
                    (AccreditationCriterion.BODY_NAAC, NAAC_CRITERIA),
                    (AccreditationCriterion.BODY_NBA, NBA_CRITERIA),
                ):
                    for code, title in catalog:
                        _, created = AccreditationCriterion.objects.get_or_create(
                            body=body, code=code, defaults={"title": title},
                        )
                        if created:
                            created_count += 1

                self.stdout.write(self.style.SUCCESS(
                    f"Schema '{tenant.schema_name}': {created_count} accreditation criterion/criteria seeded."
                ))

        self.stdout.write(self.style.SUCCESS("Accreditation criteria seed completed for all schemas."))

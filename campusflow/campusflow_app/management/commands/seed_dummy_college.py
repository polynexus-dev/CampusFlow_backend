"""
Management command: seed_dummy_college

Creates (once) a separate 'dummy' tenant college and fills it with realistic
test data across every model, so each role and module can be exercised on any
server without touching a real college's data:

  - ~2,000 students across 7 streams (Engineering, Science, Computer
    Applications, Commerce, Management, Arts, Pharmacy), 15 departments and
    19 UG/PG programmes, each with real Program/Regulation/Batch/Section rows
  - Faculty (~1 per 20 students), an HOD per department, a Principal,
    Management, Administrators, Support Staff, every functional non-teaching
    role (Librarian, Hostel Warden, Fee Counter, ...), guardians and a CA
  - Courses + outcomes + syllabus, offerings, registrations, timetable,
    lectures + attendance, exams + results, assignments, fees + payments,
    leave, payroll, library, hostel, transport, inventory, placements,
    finance ledger, accreditation catalogues, announcements
  - Then a generic pass puts a few valid rows into every remaining model
    that is still empty (grades, committees, admissions, clearance, ...).

Idempotent — safe to run on every deploy (entrypoint.sh does):
  - users are matched by username; existing ones (and their passwords) are
    never touched, only missing ones are created
  - each data section only runs while its main table is still empty
  - the generic pass only fills models that have zero rows
  - each section runs in its own transaction; a failing section is reported
    and skipped instead of aborting the rest (re-run fills it in later)

Every dummy username starts with 'dmy_' so login (which searches all
colleges by username) can never match a real college's user. All dummy
accounts share one password: $DUMMY_SEED_PASSWORD, default 'Dummy@123'.
Phone numbers are left blank on purpose so no OTP/WhatsApp can ever reach a
real number.

Usage:
    python manage.py seed_dummy_college
    python manage.py seed_dummy_college --skip-generic
"""
import math
import os
import random
import uuid
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand
from django.db import models, transaction
from django.utils import timezone
from django_tenants.utils import schema_context

from campusflow_app.permissions import NON_TEACHING_STAFF_ROLES
from tenants.models import Domain, Tenant

SCHEMA = 'dummy'
TENANT_NAME = 'CampusNexus Dummy College'
TENANT_CODE = 'dummy'
U = 'dmy_'  # username prefix for every dummy account

# (dept code, dept name, stream, [(program code, name, short name, level, years, students)])
STREAMS = [
    ("CSE", "Computer Science & Engineering", "Engineering", [
        ("BTCSE", "B.Tech Computer Science & Engineering", "B.Tech CSE", "ug", 4, 240),
        ("MTCSE", "M.Tech Computer Science & Engineering", "M.Tech CSE", "pg", 2, 30),
    ]),
    ("IT", "Information Technology", "Engineering", [
        ("BTIT", "B.Tech Information Technology", "B.Tech IT", "ug", 4, 180),
    ]),
    ("ECE", "Electronics & Communication Engineering", "Engineering", [
        ("BTECE", "B.Tech Electronics & Communication", "B.Tech ECE", "ug", 4, 160),
    ]),
    ("MECH", "Mechanical Engineering", "Engineering", [
        ("BTME", "B.Tech Mechanical Engineering", "B.Tech Mech", "ug", 4, 150),
    ]),
    ("CIVIL", "Civil Engineering", "Engineering", [
        ("BTCE", "B.Tech Civil Engineering", "B.Tech Civil", "ug", 4, 120),
    ]),
    ("EEE", "Electrical & Electronics Engineering", "Engineering", [
        ("BTEEE", "B.Tech Electrical & Electronics", "B.Tech EEE", "ug", 4, 120),
    ]),
    ("PHY", "Physics", "Science", [
        ("BSCPHY", "B.Sc Physics", "B.Sc Physics", "ug", 3, 60),
    ]),
    ("CHEM", "Chemistry", "Science", [
        ("BSCCHE", "B.Sc Chemistry", "B.Sc Chemistry", "ug", 3, 60),
    ]),
    ("MATH", "Mathematics", "Science", [
        ("BSCMAT", "B.Sc Mathematics", "B.Sc Maths", "ug", 3, 60),
    ]),
    ("CA", "Computer Applications", "Computer Applications", [
        ("BCA", "Bachelor of Computer Applications", "BCA", "ug", 3, 150),
        ("MCA", "Master of Computer Applications", "MCA", "pg", 2, 60),
    ]),
    ("COM", "Commerce", "Commerce", [
        ("BCOM", "Bachelor of Commerce", "B.Com", "ug", 3, 200),
        ("MCOM", "Master of Commerce", "M.Com", "pg", 2, 40),
    ]),
    ("MGT", "Management Studies", "Management", [
        ("BBA", "Bachelor of Business Administration", "BBA", "ug", 3, 120),
        ("MBA", "Master of Business Administration", "MBA", "pg", 2, 90),
    ]),
    ("ENG", "English", "Arts", [
        ("BAENG", "B.A. English Literature", "B.A. English", "ug", 3, 50),
    ]),
    ("ECO", "Economics", "Arts", [
        ("BAECO", "B.A. Economics", "B.A. Economics", "ug", 3, 50),
    ]),
    ("PHARM", "Pharmaceutical Sciences", "Pharmacy", [
        ("BPHARM", "Bachelor of Pharmacy", "B.Pharm", "ug", 4, 80),
    ]),
]

SUBJECTS = {
    "CSE": ["Programming in C", "Data Structures", "Discrete Mathematics", "Digital Logic", "Object Oriented Programming",
            "Database Management Systems", "Operating Systems", "Computer Networks", "Theory of Computation",
            "Design & Analysis of Algorithms", "Compiler Design", "Software Engineering", "Machine Learning",
            "Cloud Computing", "Information Security", "Distributed Systems", "Artificial Intelligence",
            "Big Data Analytics", "Computer Graphics", "Internet of Things", "Deep Learning", "Blockchain",
            "Natural Language Processing", "Major Project"],
    "IT": ["Programming Fundamentals", "Web Technologies", "Data Structures", "Database Systems", "Java Programming",
           "Computer Networks", "Operating Systems", "Software Testing", "Cloud Computing", "Mobile App Development",
           "Information Security", "Data Mining", "DevOps", "Cyber Laws", "Python for Data Science",
           "Enterprise Systems", "UI/UX Design", "Network Security", "Microservices", "E-Commerce",
           "Big Data", "Human Computer Interaction", "IT Project Management", "Capstone Project"],
    "ECE": ["Basic Electronics", "Network Analysis", "Signals & Systems", "Analog Circuits", "Digital Electronics",
            "Electromagnetic Theory", "Microprocessors", "Communication Systems", "Digital Signal Processing",
            "VLSI Design", "Control Systems", "Antenna & Wave Propagation", "Embedded Systems",
            "Optical Communication", "Wireless Communication", "Microwave Engineering", "Satellite Communication",
            "IoT Systems", "Radar Systems", "Image Processing", "Mobile Communication", "RF Design",
            "Nano Electronics", "Major Project"],
    "MECH": ["Engineering Mechanics", "Engineering Drawing", "Thermodynamics", "Strength of Materials",
             "Fluid Mechanics", "Manufacturing Processes", "Kinematics of Machines", "Heat Transfer",
             "Machine Design", "Dynamics of Machines", "IC Engines", "Metrology", "Refrigeration & AC",
             "CAD/CAM", "Industrial Engineering", "Automobile Engineering", "Robotics", "Finite Element Analysis",
             "Power Plant Engineering", "Mechatronics", "Composite Materials", "Operations Research",
             "Renewable Energy", "Major Project"],
    "CIVIL": ["Engineering Mechanics", "Building Materials", "Surveying", "Strength of Materials", "Fluid Mechanics",
              "Structural Analysis", "Concrete Technology", "Geotechnical Engineering", "Transportation Engineering",
              "Hydrology", "Design of RC Structures", "Environmental Engineering", "Design of Steel Structures",
              "Estimation & Costing", "Foundation Engineering", "Irrigation Engineering", "Construction Management",
              "Bridge Engineering", "Earthquake Engineering", "Remote Sensing & GIS", "Town Planning",
              "Pavement Design", "Prestressed Concrete", "Major Project"],
    "EEE": ["Basic Electrical Engineering", "Circuit Theory", "Electrical Machines I", "Electrical Measurements",
            "Analog Electronics", "Electrical Machines II", "Power Systems I", "Control Systems", "Power Electronics",
            "Power Systems II", "Microcontrollers", "Switchgear & Protection", "Electric Drives",
            "High Voltage Engineering", "Renewable Energy Systems", "Smart Grid", "Utilization of Electrical Energy",
            "Power Quality", "HVDC Transmission", "Electric Vehicles", "Energy Auditing", "FACTS",
            "Industrial Automation", "Major Project"],
    "PHY": ["Mechanics", "Properties of Matter", "Electricity & Magnetism", "Waves & Oscillations", "Optics",
            "Thermal Physics", "Mathematical Physics", "Quantum Mechanics", "Electronics", "Solid State Physics",
            "Nuclear Physics", "Statistical Mechanics", "Atomic Physics", "Astrophysics", "Laser Physics",
            "Physics Lab", "Spectroscopy", "Project Work"],
    "CHEM": ["Inorganic Chemistry I", "Organic Chemistry I", "Physical Chemistry I", "Analytical Chemistry",
             "Inorganic Chemistry II", "Organic Chemistry II", "Physical Chemistry II", "Spectroscopy",
             "Polymer Chemistry", "Green Chemistry", "Environmental Chemistry", "Biochemistry",
             "Medicinal Chemistry", "Industrial Chemistry", "Chemistry Lab", "Instrumental Methods",
             "Coordination Chemistry", "Project Work"],
    "MATH": ["Calculus", "Algebra", "Analytical Geometry", "Differential Equations", "Real Analysis",
             "Abstract Algebra", "Linear Algebra", "Numerical Methods", "Complex Analysis", "Probability",
             "Statistics", "Discrete Mathematics", "Number Theory", "Topology", "Operations Research",
             "Graph Theory", "Mathematical Modelling", "Project Work"],
    "CA": ["Programming in C", "Computer Fundamentals", "Data Structures", "DBMS", "Java Programming",
           "Web Design", "Operating Systems", "Python Programming", "Software Engineering", "Computer Networks",
           "PHP & MySQL", "Cloud Computing", "Android Development", "Data Analytics", "Cyber Security",
           "Machine Learning", "Advanced Java", "Project Work"],
    "COM": ["Financial Accounting", "Business Economics", "Business Communication", "Corporate Accounting",
            "Business Law", "Cost Accounting", "Income Tax", "Auditing", "Banking & Insurance",
            "Management Accounting", "Company Law", "Indirect Taxes (GST)", "Financial Management",
            "Marketing Management", "E-Commerce", "Entrepreneurship", "Investment Management", "Project Work"],
    "MGT": ["Principles of Management", "Business Economics", "Financial Accounting", "Organisational Behaviour",
            "Marketing Management", "Business Statistics", "Human Resource Management", "Financial Management",
            "Operations Management", "Business Research Methods", "Strategic Management", "Business Law",
            "Consumer Behaviour", "Digital Marketing", "International Business", "Supply Chain Management",
            "Entrepreneurship", "Project Work"],
    "ENG": ["British Poetry", "Indian Writing in English", "Prose & Essays", "Shakespeare", "Literary Criticism",
            "American Literature", "Drama", "The Novel", "Linguistics", "Postcolonial Literature",
            "Women's Writing", "World Literature", "Creative Writing", "Translation Studies", "Cultural Studies",
            "Modern Poetry", "Film & Literature", "Dissertation"],
    "ECO": ["Microeconomics I", "Macroeconomics I", "Indian Economy", "Mathematics for Economics", "Microeconomics II",
            "Macroeconomics II", "Statistics for Economics", "Public Finance", "Money & Banking",
            "International Economics", "Development Economics", "Econometrics", "Environmental Economics",
            "Agricultural Economics", "Economic History", "Labour Economics", "Economics of Growth", "Dissertation"],
    "PHARM": ["Human Anatomy & Physiology", "Pharmaceutical Analysis", "Pharmaceutics I", "Pharmaceutical Chemistry",
              "Biochemistry", "Pathophysiology", "Pharmaceutical Microbiology", "Pharmaceutical Engineering",
              "Medicinal Chemistry I", "Physical Pharmaceutics", "Pharmacology I", "Pharmacognosy",
              "Medicinal Chemistry II", "Industrial Pharmacy", "Pharmacology II", "Pharmaceutical Jurisprudence",
              "Biopharmaceutics", "Pharmacy Practice", "Novel Drug Delivery", "Quality Assurance",
              "Pharmacovigilance", "Clinical Research", "Social Pharmacy", "Project Work"],
}
PG_SUBJECTS = {
    "MTCSE": ["Advanced Algorithms", "Advanced Computer Architecture", "Machine Learning", "Research Methodology",
              "Advanced Databases", "Cloud Architecture", "Deep Learning", "Elective I", "Elective II",
              "Seminar", "Dissertation Phase I", "Dissertation Phase II"],
    "MCA": ["Advanced Data Structures", "Advanced DBMS", "Object Oriented Analysis & Design", "Computer Networks",
            "Web Frameworks", "Machine Learning", "Cloud Computing", "Software Project Management",
            "Data Science", "Mobile Computing", "Elective", "Major Project"],
    "MCOM": ["Advanced Financial Accounting", "Managerial Economics", "Corporate Finance", "Research Methodology",
             "Advanced Cost Accounting", "Strategic Management", "International Finance", "Tax Planning",
             "Financial Markets", "Corporate Governance", "Elective", "Dissertation"],
    "MBA": ["Management Concepts", "Managerial Economics", "Accounting for Managers", "Marketing Management",
            "Financial Management", "Human Resource Management", "Operations Research", "Business Analytics",
            "Strategic Management", "Elective I", "Elective II", "Summer Internship Project"],
}

MALE = ['Aarav', 'Vihaan', 'Aditya', 'Arjun', 'Reyansh', 'Krishna', 'Ishaan', 'Shaurya', 'Rohan', 'Rahul',
        'Amit', 'Vikram', 'Deepak', 'Sanjay', 'Rajesh', 'Aniket', 'Vijay', 'Kunal', 'Siddharth', 'Omkar',
        'Pranav', 'Yash', 'Harsh', 'Nikhil', 'Tejas', 'Sahil', 'Varun', 'Manish', 'Abhishek', 'Karan']
FEMALE = ['Ananya', 'Diya', 'Pari', 'Ira', 'Avani', 'Riya', 'Kavya', 'Saanvi', 'Kiara', 'Sneha',
          'Priya', 'Neha', 'Pooja', 'Divya', 'Jyoti', 'Sunita', 'Aishwarya', 'Shalini', 'Shruti', 'Tanvi',
          'Gauri', 'Mrunal', 'Isha', 'Sakshi', 'Prachi', 'Megha', 'Rutuja', 'Komal', 'Nidhi', 'Aditi']
LAST = ['Sharma', 'Verma', 'Gupta', 'Patel', 'Joshi', 'Mehra', 'Singh', 'Kumar', 'Deshmukh', 'Kulkarni',
        'Nair', 'Pillai', 'Rao', 'Reddy', 'Kapoor', 'Malhotra', 'Banerjee', 'Das', 'Mishra', 'Yadav',
        'Patil', 'Jadhav', 'Pawar', 'Shinde', 'Gaikwad', 'Bhosale', 'Iyer', 'Menon', 'Chavan', 'More']
CITIES = [('Pune', 'Pune', 'Maharashtra', '411001'), ('Mumbai', 'Mumbai', 'Maharashtra', '400001'),
          ('Nashik', 'Nashik', 'Maharashtra', '422001'), ('Nagpur', 'Nagpur', 'Maharashtra', '440001'),
          ('Bengaluru', 'Bengaluru Urban', 'Karnataka', '560001'), ('Hyderabad', 'Hyderabad', 'Telangana', '500001')]

D = Decimal

# Job titles for the non-teaching dummy accounts (username without the dmy_ prefix).
NT_DESIGNATIONS = {
    'driver': 'Bus Driver', 'conductor': 'Bus Conductor', 'labasst': 'Lab Assistant', 'clerk': 'Office Clerk',
    'librarian': 'Librarian', 'warden_boys': 'Warden, Boys Hostel', 'warden_girls': 'Warden, Girls Hostel',
    'store': 'Store Manager', 'tpo': 'Training & Placement Officer', 'fees': 'Fee Counter Clerk',
    'transport': 'Transport Coordinator', 'payroll': 'Payroll Officer', 'admissions': 'Admissions Officer',
    'scholarship': 'Scholarship Officer', 'accounts': 'Accounts Officer',
    'canteen_head': 'Canteen Manager', 'canteen': 'Canteen Staff', 'support_head': 'Support Staff Supervisor',
}


def nt_designation(uname):
    return NT_DESIGNATIONS.get(uname.rstrip('0123456789'), uname.title())


class Command(BaseCommand):
    help = "Creates/refreshes the 'dummy' tenant college with ~2,000 students and data in every model. Idempotent."

    def add_arguments(self, parser):
        parser.add_argument('--skip-generic', action='store_true',
                            help="Skip the pass that puts placeholder rows into every remaining empty model.")

    def handle(self, *args, **options):
        self.rnd = random.Random(2026)
        self.password_hash = make_password(os.environ.get('DUMMY_SEED_PASSWORD', 'Dummy@123'))
        self.failures = []

        tenant, email_domain = self._ensure_tenant()
        self.email_domain = email_domain

        with schema_context(tenant.schema_name):
            self._step("role groups", self._groups)
            self._step("academic calendar & grading", self._calendar)
            self._step("departments & programmes", self._structure)
            self._step("people (all roles)", self._people)
            self._step("courses, outcomes & syllabus", self._courses)
            self._step("classrooms, offerings & registrations", self._offerings)
            self._step("timetable, lectures & attendance", self._timetable)
            self._step("exams & results", self._exams)
            self._step("assignments", self._assignments)
            self._step("fees & payments", self._fees)
            self._step("leave", self._leave)
            self._step("payroll", self._payroll)
            self._step("library", self._library)
            self._step("hostel", self._hostel)
            self._step("transport", self._transport)
            self._step("inventory", self._inventory)
            self._step("placements", self._placements)
            self._step("finance & accreditation", self._finance)
            self._step("auditor access to every financial year", self._audit_years)
            self._step("announcements & notifications", self._announcements)
            self._step("clearance desks & final-year no-dues", self._clearance)
            if not options['skip_generic']:
                self._generic_fill()
            self._report()

    # ── helpers ────────────────────────────────────────────────────────────

    def _step(self, label, fn):
        try:
            with transaction.atomic():
                result = fn()
            self.stdout.write(f"   ✅ {label}{': ' + result if result else ''}")
        except Exception as e:  # keep going: one broken section must not block the rest / the deploy
            self.failures.append(label)
            self.stdout.write(self.style.WARNING(f"   ⚠️  {label} failed, skipped: {type(e).__name__}: {e}"))

    def _load(self):
        """Reload the reference objects later sections need (they may run on a later deploy than _people)."""
        from campusflow_app.models import Department, StudentProfile, TeachingStaffProfile
        self.depts = {d.code: d for d in Department.objects.all()}
        self.fac_by_dept = {}
        for p in TeachingStaffProfile.objects.select_related('user', 'department'):
            if p.department_id:
                self.fac_by_dept.setdefault(p.department.code, []).append(p.user)
        self.students = list(StudentProfile.objects.select_related('user', 'department', 'program', 'batch', 'section'))
        self.users = {u.username: u for u in User.objects.filter(username__startswith=U)}

    def _user(self, username):
        return self.users.get(U + username)

    def _gender_name(self, i):
        if i % 2:
            return 'Female', self.rnd.choice(FEMALE), self.rnd.choice(LAST)
        return 'Male', self.rnd.choice(MALE), self.rnd.choice(LAST)

    def _address(self, i):
        city, district, state, pin = CITIES[i % len(CITIES)]
        return {
            'current_address_line1': f"{(i % 200) + 1}, Dummy Residency, Sector {(i % 30) + 1}",
            'current_city': city, 'current_district': district, 'current_state': state, 'current_pincode': pin,
            'permanent_address_line1': f"{(i % 150) + 10}, Old Town Road",
            'permanent_city': city, 'permanent_district': district, 'permanent_state': state, 'permanent_pincode': pin,
        }

    def _ensure_people(self, role, specs):
        """specs: [{username, first_name, last_name, profile: {...}}]. Creates only what's missing."""
        from campusflow_app.models import (
            AdministratorProfile, AuditorProfile, DepartmentHeadProfile, GuardianProfile, ManagementProfile,
            NonTeachingStaffProfile, PrincipalProfile, StudentProfile, TeachingStaffProfile,
        )
        profile_model = {
            'student': StudentProfile, 'Faculty': TeachingStaffProfile, 'Department Head': DepartmentHeadProfile,
            'Principal': PrincipalProfile, 'Administrator': AdministratorProfile, 'Management': ManagementProfile,
            'guardian': GuardianProfile, 'CA': AuditorProfile,
        }.get(role, NonTeachingStaffProfile)

        names = [s['username'] for s in specs]
        existing = {u.username: u for u in User.objects.filter(username__in=names)}
        new_users = [
            User(username=s['username'], email=f"{s['username']}@{self.email_domain}",
                 first_name=s['first_name'], last_name=s['last_name'],
                 password=self.password_hash, is_active=True)
            for s in specs if s['username'] not in existing
        ]
        User.objects.bulk_create(new_users, batch_size=1000)
        users = {**existing, **{u.username: u for u in new_users}}

        group = Group.objects.get(name=role)
        User.groups.through.objects.bulk_create(
            [User.groups.through(user_id=u.id, group_id=group.id) for u in new_users],
            batch_size=1000, ignore_conflicts=True,
        )

        have = set(profile_model.objects.filter(user__in=users.values()).values_list('user_id', flat=True))
        profile_model.objects.bulk_create(
            [profile_model(user=users[s['username']], **s.get('profile', {}))
             for s in specs if users[s['username']].id not in have],
            batch_size=1000,
        )
        self.users.update(users)
        return len(new_users)

    # ── tenant ─────────────────────────────────────────────────────────────

    def _ensure_tenant(self):
        from campusflow_app.views.module_permissions import ALL_ERP_MODULES

        public = Tenant.objects.filter(schema_name='public').first()
        primary = Domain.objects.filter(tenant=public, is_primary=True).first() if public else None
        public_domain = primary.domain if primary else 'localhost'
        email_domain = f"{SCHEMA}.{public_domain}"

        tenant = Tenant.objects.filter(schema_name=SCHEMA).first()
        if not tenant:
            self.stdout.write(f"🔄 Creating tenant '{SCHEMA}' (creates the schema and runs its migrations)...")
            tenant = Tenant.objects.create(
                schema_name=SCHEMA, name=TENANT_NAME, code=TENANT_CODE,
                address="1 Test Campus Road, Pune, Maharashtra 411001",
                contact_email=f"office@{email_domain}", permitted_email_domain=email_domain,
                timezone="Asia/Kolkata", subscribed_modules=sorted(ALL_ERP_MODULES),
            )
        missing = set(ALL_ERP_MODULES) - set(tenant.subscribed_modules or [])
        if missing:
            tenant.subscribed_modules = sorted(set(tenant.subscribed_modules or []) | missing)
            tenant.save(update_fields=['subscribed_modules'])

        domains = [f"{SCHEMA}.localhost"] + ([f"{SCHEMA}.{public_domain}"] if public_domain != 'localhost' else [])
        for i, dom in enumerate(domains):
            if not Domain.objects.filter(domain=dom).exists():
                Domain.objects.create(domain=dom, tenant=tenant, is_primary=(i == 0))
        self.stdout.write(f"✅ Tenant '{SCHEMA}' ready ({', '.join(domains)}). Seeding...")
        return tenant, email_domain

    # ── sections ───────────────────────────────────────────────────────────

    def _groups(self):
        for name in ['student', 'Faculty', 'Management', 'Administrator', 'Principal', 'Department Head',
                     'guardian', 'CA', *NON_TEACHING_STAFF_ROLES]:
            Group.objects.get_or_create(name=name)

    def _calendar(self):
        from campusflow_app.services.academics import get_current_term, get_default_grading_scheme
        self.term = get_current_term()
        get_default_grading_scheme()
        return f"current term {self.term}"

    def _structure(self):
        from campusflow_app.models import Batch, Department, Program, Regulation, Section
        from campusflow_app.services.academics import get_current_term

        term = get_current_term()
        ay_start = term.academic_year.start_date.year
        odd_term = term.sequence == 1
        created = 0
        for i, (dcode, dname, stream, programs) in enumerate(STREAMS):
            dept, c = Department.objects.get_or_create(code=dcode, defaults={
                'name': dname, 'status': 'Active', 'description': f"{stream} stream",
                'email': f"{dcode.lower()}@{self.email_domain}", 'date_established': date(1995 + i, 6, 1),
            })
            created += c
            for pcode, pname, short, level, years, _ in programs:
                program, _ = Program.objects.get_or_create(code=pcode, defaults={
                    'name': pname, 'short_name': short, 'level': level, 'department': dept,
                    'duration_years': D(years), 'total_terms': years * 2,
                    'total_credits_required': D(40 * years),
                })
                if Batch.objects.filter(program=program).exists():
                    continue
                first_year = ay_start - years + 1
                regulation, _ = Regulation.objects.get_or_create(program=program, code=f"R{first_year}", defaults={
                    'name': f"{short} Regulation {first_year}", 'effective_from_year': first_year,
                    'status': 'active', 'min_credits_to_graduate': D(40 * years),
                })
                for k in range(years):  # k = years since admission
                    adm = ay_start - k
                    sem = min(years * 2, k * 2 + (1 if odd_term else 2))
                    batch = Batch.objects.create(
                        program=program, regulation=regulation, admission_year=adm,
                        name=f"{adm}-{adm + years}", expected_graduation_year=adm + years,
                        current_semester_number=sem,
                    )
                    for sec in ('A', 'B'):
                        Section.objects.create(batch=batch, name=sec, semester_number=sem, capacity=60)
        return f"{Department.objects.count()} departments, {Program.objects.count()} programmes, {Batch.objects.count()} batches"

    def _people(self):
        from campusflow_app.models import Batch, Department, Program, Section, TeachingStaffProfile

        self.users = {u.username: u for u in User.objects.filter(username__startswith=U)}
        depts = {d.code: d for d in Department.objects.all()}
        made = {}
        today = date.today()

        # Leadership & office
        specs = lambda rows, extra=None: [  # noqa: E731
            {'username': U + uname, 'first_name': fn, 'last_name': ln, 'profile': {
                'employee_id': emp, 'designation': desig, 'status': 'active', 'consent_given': True,
                'date_of_joining': date(2010 + n % 12, 6, 1), 'gender': g, **(extra or {}), **self._address(n)}}
            for n, (uname, fn, ln, g, emp, desig) in enumerate(rows)
        ]
        made['Management'] = self._ensure_people('Management', specs([
            ('chairman', 'Rajendra', 'Deshmukh', 'Male', 'DMY-MGT-001', 'Chairman'),
            ('director', 'Sunita', 'Kulkarni', 'Female', 'DMY-MGT-002', 'Director'),
        ], {'staff_role': 'director'}))
        made['Principal'] = self._ensure_people('Principal', specs([
            ('principal', 'Dr. Mahesh', 'Joshi', 'Male', 'DMY-PRN-001', 'Principal'),
        ]))
        made['Administrator'] = self._ensure_people('Administrator', specs([
            ('admin', 'Prakash', 'Patil', 'Male', 'DMY-ADM-001', 'Registrar'),
            ('admin2', 'Meena', 'Iyer', 'Female', 'DMY-ADM-002', 'Office Superintendent'),
        ]))

        # Non-teaching staff: Support Staff (incl. bus drivers/conductors) + every functional role
        nt_rows = {
            'Support Staff': [('driver1', 'Ramesh'), ('driver2', 'Suresh'), ('driver3', 'Ganesh'), ('driver4', 'Mahadev'),
                              ('conductor1', 'Santosh'), ('conductor2', 'Dinesh'), ('conductor3', 'Anil'),
                              ('conductor4', 'Sunil'), ('labasst1', 'Kavita'), ('labasst2', 'Sachin'),
                              ('clerk1', 'Vaishali'), ('clerk2', 'Nitin')],
            'Librarian': [('librarian', 'Shubhangi'), ('librarian2', 'Ajay')],
            'Hostel Warden': [('warden_boys', 'Dattatray'), ('warden_girls', 'Lata')],
            'Store Manager': [('store', 'Mohan')],
            'Placement Officer': [('tpo', 'Rekha'), ('tpo2', 'Amol')],
            'Fee Counter': [('fees', 'Swati'), ('fees2', 'Rohit')],
            'Transport Coordinator': [('transport', 'Balasaheb')],
            'Payroll Officer': [('payroll', 'Anjali')],
            'Admissions Officer': [('admissions', 'Kiran'), ('admissions2', 'Pallavi')],
            'Scholarship Officer': [('scholarship', 'Vandana')],
            'Accounts Officer': [('accounts', 'Mukund'), ('accounts2', 'Seema')],
        }
        n = 0
        for role, rows in nt_rows.items():
            role_specs = []
            for uname, fn in rows:
                n += 1
                role_specs.append({'username': U + uname, 'first_name': fn, 'last_name': LAST[n % len(LAST)], 'profile': {
                    'employee_id': f"DMY-NT-{n:03d}", 'designation': nt_designation(uname),
                    'staff_role': role if role != 'Support Staff' else 'administrator', 'status': 'active',
                    'consent_given': True, 'date_of_joining': date(2012 + n % 10, 7, 1), **self._address(n)}})
            made[role] = self._ensure_people(role, role_specs)

        # HODs, faculty, students per department
        hod_specs, fac_specs, stu_specs = [], [], []
        cadres = [TeachingStaffProfile.CADRE_PROFESSOR, TeachingStaffProfile.CADRE_ASSOCIATE_PROFESSOR,
                  TeachingStaffProfile.CADRE_ASSISTANT_PROFESSOR, TeachingStaffProfile.CADRE_ASSISTANT_PROFESSOR]
        cadre_title = {'professor': 'Professor', 'associate_professor': 'Associate Professor',
                       'assistant_professor': 'Assistant Professor'}
        stu_serial = 0
        for di, (dcode, dname, stream, programs) in enumerate(STREAMS):
            dept = depts[dcode]
            g, fn, ln = self._gender_name(di)
            hod_specs.append({'username': f"{U}hod_{dcode.lower()}", 'first_name': f"Dr. {fn}", 'last_name': ln, 'profile': {
                'employee_id': f"DMY-HOD-{dcode}", 'department': dept, 'designation': f"Head, {dname}",
                'status': 'active', 'gender': g, 'consent_given': True, 'date_of_joining': date(2008 + di % 8, 6, 1)}})

            dept_students = sum(p[5] for p in programs)
            for f in range(max(4, math.ceil(dept_students / 20))):
                g, fn, ln = self._gender_name(di * 7 + f)
                cadre = cadres[f % 4]
                fac_specs.append({'username': f"{U}fac_{dcode.lower()}_{f + 1:02d}",
                                  'first_name': ("Dr. " if cadre != 'assistant_professor' else "Prof. ") + fn,
                                  'last_name': ln, 'profile': {
                    'employee_id': f"DMY-FAC-{dcode}-{f + 1:02d}", 'department': dept, 'designation': cadre_title[cadre],
                    'aicte_cadre': cadre, 'staff_role': 'lecturer', 'status': 'active', 'gender': g,
                    'has_phd': cadre != 'assistant_professor', 'experience_years': 3 + (f * 3) % 25,
                    'qualifications': 'Ph.D.' if cadre != 'assistant_professor' else 'M.Tech / M.Sc / M.Com',
                    'specializations': SUBJECTS[dcode][f % len(SUBJECTS[dcode])],
                    'date_of_joining': date(2005 + f % 18, 7, 1), 'consent_given': True,
                    'office_room_number': f"{dcode}-{100 + f}", 'max_weekly_teaching_hours': 16}})

            for pcode, pname, short, level, years, total in programs:
                program = Program.objects.get(code=pcode)
                batches = list(Batch.objects.filter(program=program).order_by('-admission_year'))
                per_batch = total // len(batches)
                for bi, batch in enumerate(batches):
                    count = per_batch + (total - per_batch * len(batches) if bi == 0 else 0)
                    sections = {s.name: s for s in Section.objects.filter(batch=batch, semester_number=batch.current_semester_number)}
                    for s in range(count):
                        stu_serial += 1
                        g, fn, ln = self._gender_name(stu_serial)
                        sec = sections['A' if s % 2 == 0 else 'B']
                        sid = f"DMY-{pcode}-{batch.admission_year % 100:02d}{s + 1:03d}"
                        stu_specs.append({'username': f"{U}{pcode.lower()}{batch.admission_year % 100:02d}{s + 1:03d}",
                                          'first_name': fn, 'last_name': ln, 'profile': {
                            'student_id': sid, 'department': dept, 'program': program, 'batch': batch, 'section': sec,
                            'current_semester_number': batch.current_semester_number,
                            # legacy mirror fields (StudentProfile.save() would sync these; bulk_create doesn't call it)
                            'program_enrolled_in': program.name[:50], 'batch_academic_year': batch.name,
                            'current_semester_year': f"Semester {batch.current_semester_number}",
                            'section_division': sec.name, 'status': 'active', 'academic_status': 'active',
                            'gender': g, 'date_of_birth': date(batch.admission_year - (18 if level == 'ug' else 21), 1 + s % 12, 1 + s % 28),
                            'blood_group': ['A+', 'B+', 'O+', 'AB+', 'O-'][s % 5], 'nationality': 'Indian',
                            'category': ['General', 'OBC', 'SC', 'ST', 'EWS'][s % 5],
                            'admission_date': date(batch.admission_year, 8, 1), 'admission_number': sid.replace('DMY-', 'ADM-'),
                            'tenth_marksheet_percentage': D(60 + (s * 7) % 39), 'twelfth_marksheet_percentage': D(55 + (s * 11) % 44),
                            'consent_given': True, 'consent_version': 'v1.0',
                            'parent_guardian_name': f"{self.rnd.choice(MALE)} {ln}", **self._address(stu_serial)}})

        made['Department Head'] = self._ensure_people('Department Head', hod_specs)
        made['Faculty'] = self._ensure_people('Faculty', fac_specs)
        made['student'] = self._ensure_people('student', stu_specs)

        # Team roles added later. Drivers/conductors keep their place above (their
        # employee ids are positional) and just move to their own roles; the new
        # canteen team and support in-charge get ids from a separate range.
        from campusflow_app.models import NonTeachingStaffProfile as NTP
        for uname, new_role in [(f'driver{i}', 'Driver') for i in range(1, 5)] + [(f'conductor{i}', 'Conductor') for i in range(1, 5)]:
            u = self.users.get(U + uname)
            if u and u.groups.filter(name='Support Staff').exists():
                u.groups.set([Group.objects.get(name=new_role)])
                NTP.objects.filter(user=u).update(staff_role=new_role)
        team_rows = {
            'Support Staff': [('support_head', 'Vilas', 101)],
            'Canteen Staff': [('canteen_head', 'Sharad', 102), ('canteen1', 'Babu', 103), ('canteen2', 'Lakshmi', 104)],
        }
        for role, rows in team_rows.items():
            made[role] = made.get(role, 0) + self._ensure_people(role, [
                {'username': U + uname, 'first_name': fn, 'last_name': LAST[k % len(LAST)], 'profile': {
                    'employee_id': f"DMY-NT-{k:03d}", 'designation': nt_designation(uname),
                    'staff_role': role if role != 'Support Staff' else 'administrator', 'status': 'active',
                    'consent_given': True, 'date_of_joining': date(2015, 7, 1), **self._address(k)}}
                for uname, fn, k in rows])
        # One in-charge per team, set once when the feature first arrives (never
        # re-applied, so an admin's later change sticks).
        if not NTP.objects.filter(is_in_charge=True).exists():
            NTP.objects.filter(user__username__in=[U + n for n in ('librarian', 'warden_boys', 'support_head', 'canteen_head')]
                               ).update(is_in_charge=True)

        # Older seeds derived the title from the username ("Labasst"); fix only those untouched rows.
        from campusflow_app.models import NonTeachingStaffProfile
        for role_rows in nt_rows.values():
            for uname, _ in role_rows:
                old = uname.rstrip('0123456789').replace('_', ' ').title()
                if old != nt_designation(uname):
                    NonTeachingStaffProfile.objects.filter(user__username=U + uname, designation=old).update(
                        designation=nt_designation(uname))

        # Department-attached support staff, so a HOD's own-department staff list isn't empty.
        # Only fills a missing department, never moves someone an admin re-assigned.
        from campusflow_app.models import NonTeachingStaffProfile
        for uname, dcode in (('labasst1', 'CSE'), ('labasst2', 'MECH'), ('clerk1', 'COM'), ('clerk2', 'CA'),
                             ('librarian2', 'ENG'), ('admissions2', 'MGT')):
            NonTeachingStaffProfile.objects.filter(user__username=U + uname, department__isnull=True).update(department=depts[dcode])

        for dcode, dept in depts.items():
            hod = self.users.get(f"{U}hod_{dcode.lower()}")
            if hod and dept.hod_id != hod.id:
                dept.hod = hod
                dept.save(update_fields=['hod'])

        # Guardians for the first 300 students, and one CA
        from campusflow_app.models import GuardianProfile, StudentProfile
        first_students = list(StudentProfile.objects.filter(user__username__startswith=U).order_by('id')[:300])
        made['guardian'] = self._ensure_people('guardian', [
            {'username': f"{U}parent_{sp.student_id.lower().replace('-', '')}", 'first_name': (sp.parent_guardian_name or 'Parent').split()[0],
             'last_name': sp.user.last_name, 'profile': {'guardian_id': f"DMY-GUA-{i + 1:04d}", 'status': 'active',
                                                         'consent_given': True, 'address': 'Dummy Residency, Pune'}}
            for i, sp in enumerate(first_students)
        ])
        for i, sp in enumerate(first_students):
            gp = GuardianProfile.objects.filter(guardian_id=f"DMY-GUA-{i + 1:04d}").first()
            if gp and not gp.students.exists():
                gp.students.add(sp)
        made['CA'] = self._ensure_people('CA', [{'username': U + 'auditor', 'first_name': 'CA Rakesh', 'last_name': 'Agarwal',
                                                 'profile': {'firm_name': 'Agarwal & Associates', 'icai_membership_number': '123456'}}])
        new = sum(made.values())
        return f"{new} new accounts" if new else "all accounts already exist"

    def _courses(self):
        from campusflow_app.models import (
            Course, CourseOutcome, Program, ProgramOutcome, POCOMapping, Question, Regulation, SyllabusTopic,
        )
        if Course.objects.exists():
            return "already seeded"
        courses = []
        for dcode, dname, stream, programs in STREAMS:
            for pcode, pname, short, level, years, _ in programs:
                program = Program.objects.get(code=pcode)
                regulation = Regulation.objects.filter(program=program).first()
                pool = PG_SUBJECTS.get(pcode) or SUBJECTS[dcode]
                k = 0
                for sem in range(1, years * 2 + 1):
                    for c in range(3):
                        name = pool[k % len(pool)] + (" II" if k >= len(pool) else "")
                        k += 1
                        courses.append(Course(
                            course_code=f"{pcode}{sem}{c + 1:02d}", course_name=name, department=program.department,
                            regulation=regulation, semester_number=sem,
                            course_type='project' if 'Project' in name or 'Dissertation' in name else ('lab' if 'Lab' in name else 'core'),
                            credits=D(4 if c < 2 else 3), lecture_hours=3, tutorial_hours=1, practical_hours=2 if c == 2 else 0,
                        ))
        Course.objects.bulk_create(courses, batch_size=1000)

        po_rows = []
        po_text = ["Apply knowledge of fundamentals to solve problems", "Identify and analyse complex problems",
                   "Design solutions meeting specified needs", "Conduct investigations of complex problems",
                   "Use modern tools appropriately", "Assess societal and safety issues",
                   "Understand environmental sustainability", "Apply ethical principles",
                   "Function effectively in teams", "Communicate effectively",
                   "Apply project and finance management", "Engage in life-long learning"]
        for program in Program.objects.all():
            for i, txt in enumerate(po_text):
                po_rows.append(ProgramOutcome(program=program, kind='po', code=f"PO{i + 1}", statement=txt, order=i + 1))
            for i in range(2):
                po_rows.append(ProgramOutcome(program=program, kind='pso', code=f"PSO{i + 1}",
                                              statement=f"Programme-specific competence {i + 1} in {program.short_name}", order=20 + i))
        ProgramOutcome.objects.bulk_create(po_rows, batch_size=1000)

        blooms = ['remember', 'understand', 'apply', 'analyse']
        co_rows, topic_rows = [], []
        for course in Course.objects.all():
            for i in range(4):
                co_rows.append(CourseOutcome(course=course, code=f"CO{i + 1}", bloom_level=blooms[i], order=i + 1,
                                             statement=f"Students will be able to {blooms[i]} key concepts of {course.course_name} (unit {i + 1})"))
            for i in range(5):
                topic_rows.append(SyllabusTopic(course=course, name=f"Unit {i + 1}: {course.course_name} — Part {i + 1}", order=i + 1))
        CourseOutcome.objects.bulk_create(co_rows, batch_size=2000)
        SyllabusTopic.objects.bulk_create(topic_rows, batch_size=2000)

        pos = {}
        for po in ProgramOutcome.objects.filter(kind='po').select_related('program'):
            pos.setdefault(po.program.department_id, {}).setdefault(po.program_id, []).append(po)
        reg_program = dict(Regulation.objects.values_list('id', 'program_id'))
        maps, questions = [], []
        topics = {}
        for t in SyllabusTopic.objects.all():
            topics.setdefault(t.course_id, []).append(t)
        for co in CourseOutcome.objects.select_related('course'):
            plist = pos.get(co.course.department_id, {}).get(reg_program.get(co.course.regulation_id), [])
            for j, po in enumerate(plist[co.order - 1: co.order + 2]):
                maps.append(POCOMapping(course_outcome=co, program_outcome=po, strength=3 - j))
            t = topics.get(co.course_id, [None])[co.order - 1]
            for q in range(2):
                questions.append(Question(course=co.course, topic=t, course_outcome=co, marks=D(5 if q == 0 else 10),
                                          difficulty=['easy', 'medium', 'hard'][(co.order + q) % 3],
                                          text=f"{'Explain' if q == 0 else 'Analyse with an example'}: {t.name if t else co.course.course_name}"))
        POCOMapping.objects.bulk_create(maps, batch_size=2000)
        Question.objects.bulk_create(questions, batch_size=2000)
        return f"{len(courses)} courses, {len(co_rows)} COs, {len(questions)} questions"

    def _offerings(self):
        from campusflow_app.models import Classroom, Course, CourseOffering, Section, StudentCourseRegistration
        from campusflow_app.services.academics import get_current_term
        self._load()
        if not Classroom.objects.exists():
            rooms = [Classroom(name=f"{blk} Block Room {r}", code=f"{blk[0]}{r}", capacity=60 + (r % 3) * 20)
                     for blk in ('Aryabhata', 'Bhaskara', 'CV Raman', 'Dhanvantari') for r in range(101, 116)]
            rooms += [Classroom(name=f"Computer Lab {i}", code=f"LAB{i}", capacity=40) for i in range(1, 6)]
            rooms += [Classroom(name="Main Auditorium", code="AUD1", capacity=500), Classroom(name="Seminar Hall", code="SEM1", capacity=150)]
            Classroom.objects.bulk_create(rooms)
        if CourseOffering.objects.exists():
            return "already seeded"
        term = get_current_term()
        offerings = []
        rr = {}
        for section in Section.objects.select_related('batch__program__department', 'batch__regulation'):
            batch = section.batch
            dcode = batch.program.department.code
            faculty = self.fac_by_dept.get(dcode) or []
            for course in Course.objects.filter(regulation=batch.regulation, semester_number=section.semester_number):
                i = rr[dcode] = rr.get(dcode, -1) + 1
                offerings.append(CourseOffering(course=course, term=term, batch=batch, section=section,
                                                faculty=faculty[i % len(faculty)] if faculty else None, max_seats=60))
        CourseOffering.objects.bulk_create(offerings, batch_size=1000)
        by_section = {}
        for off in CourseOffering.objects.filter(term=term):
            by_section.setdefault(off.section_id, []).append(off)
        regs = [StudentCourseRegistration(student=sp, offering=off, term=term, status='registered', attempt_type='regular')
                for sp in self.students for off in by_section.get(sp.section_id, [])]
        StudentCourseRegistration.objects.bulk_create(regs, batch_size=2000)
        return f"{len(offerings)} offerings, {len(regs)} registrations"

    def _timetable(self):
        from campusflow_app.models import (
            Attendance, Classroom, CourseOffering, FaceAttendanceLog, Lecture, Schedule,
        )
        from campusflow_app.services.academics import get_current_term
        if Schedule.objects.exists():
            return "already seeded"
        self._load()
        term = get_current_term()
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
        rooms = list(Classroom.objects.exclude(code__in=['AUD1', 'SEM1']).order_by('id'))
        schedules = []
        sections = {}
        for off in CourseOffering.objects.filter(term=term).select_related('course', 'section').order_by('section_id', 'id'):
            sections.setdefault(off.section_id, []).append(off)
        for si, (section_id, offs) in enumerate(sections.items()):
            room = rooms[si % len(rooms)]
            for ci, off in enumerate(offs):
                if not off.faculty_id:
                    continue
                for slot in range(2):
                    hour = 9 + ci * 2 + slot  # different hour per course => no clash inside a section
                    schedules.append(Schedule(
                        course=off.course, faculty_id=off.faculty_id, classroom=room,
                        day_of_week=days[(ci * 2 + slot + si) % 6], start_time=time(hour), end_time=time(hour + 1),
                        semester=f"Semester {off.section.semester_number}", academic_year=term.academic_year.name,
                        term=term, course_offering=off,
                    ))
        Schedule.objects.bulk_create(schedules, batch_size=1000, ignore_conflicts=True)

        # Lectures for the last 14 days from the timetable, with ~85% attendance
        today = timezone.localdate()
        students_by_section = {}
        for sp in self.students:
            students_by_section.setdefault(sp.section_id, []).append(sp)
        lectures, lec_section = [], []
        day_idx = {d: i for i, d in enumerate(days)}
        for sch in Schedule.objects.select_related('course', 'course_offering'):
            for back in range(1, 15):
                d = today - timedelta(days=back)
                if d.weekday() != day_idx[sch.day_of_week]:
                    continue
                start = timezone.make_aware(datetime.combine(d, sch.start_time))
                lectures.append(Lecture(name=f"{sch.course.course_name} Lecture", subject=sch.course.course_name,
                                        faculty_id=sch.faculty_id, classroom_id=sch.classroom_id, start_time=start,
                                        end_time=start + timedelta(hours=1), code=f"DM{sch.id:05d}{d:%m%d}",
                                        latitude=D('18.520430'), longitude=D('73.856743')))
                lec_section.append(sch.course_offering.section_id)
        Lecture.objects.bulk_create(lectures, batch_size=1000)
        att, face = [], []
        for lec, section_id in zip(lectures, lec_section):
            for sp in students_by_section.get(section_id, []):
                if self.rnd.random() < 0.85:
                    t = lec.start_time + timedelta(minutes=self.rnd.randint(0, 8))
                    att.append(Attendance(user=sp.user, lecture=lec, check_in_time=t, is_geofence_valid=True,
                                          device_id=f"DUMMY-{sp.id}", verification_method='face_geofence'))
                    face.append(FaceAttendanceLog(student=sp, lecture=lec, timestamp=t, is_verified=True,
                                                  liveness_passed=True, confidence_score=round(self.rnd.uniform(0.78, 0.98), 2)))
        Attendance.objects.bulk_create(att, batch_size=5000, ignore_conflicts=True)
        FaceAttendanceLog.objects.bulk_create(face, batch_size=5000, ignore_conflicts=True)
        return f"{len(schedules)} weekly slots, {len(lectures)} lectures, {len(att)} attendance marks"

    def _exams(self):
        from campusflow_app.models import CourseOffering, Exam, ExamType, StudentCourseRegistration, StudentExamResult
        from campusflow_app.services.academics import get_current_term
        if Exam.objects.exists():
            return "already seeded"
        self._load()
        term = get_current_term()
        mid, _ = ExamType.objects.get_or_create(code='MID', defaults={'name': 'Mid-Term Examination'})
        end, _ = ExamType.objects.get_or_create(code='END', defaults={'name': 'End-Semester Examination'})
        ExamType.objects.get_or_create(code='UT', defaults={'name': 'Unit Test'})
        today = date.today()
        exams = []
        offs = list(CourseOffering.objects.filter(term=term).select_related('course__department', 'section', 'batch__program'))
        for i, off in enumerate(offs):
            hod = off.course.department.hod
            common = dict(department=off.course.department, course=off.course, semester=f"Semester {off.section.semester_number}",
                          academic_year=term.academic_year.name, term=term, invigilator_id=off.faculty_id, created_by=hod)
            exams.append(Exam(name=f"{off.course.course_name} Mid-Term ({off.batch.program.short_name} {off.section.name})",
                              exam_type=mid, date=today - timedelta(days=10 + i % 5), start_time=time(10), end_time=time(11, 30),
                              total_marks=50, passing_marks=20, status='completed', results_published=True,
                              results_published_at=timezone.now() - timedelta(days=3), **common))
            exams.append(Exam(name=f"{off.course.course_name} End-Semester ({off.batch.program.short_name} {off.section.name})",
                              exam_type=end, date=today + timedelta(days=30 + i % 10), start_time=time(10), end_time=time(13),
                              total_marks=100, passing_marks=40, status='scheduled', **common))
        Exam.objects.bulk_create(exams, batch_size=1000)
        regs = {}
        for r in StudentCourseRegistration.objects.filter(term=term).select_related('offering'):
            regs.setdefault((r.offering.course_id, r.offering.section_id), []).append(r.student_id)
        results = []
        for off, exam in zip(offs, exams[0::2]):
            for sid in regs.get((off.course_id, off.section_id), []):
                marks = max(8, min(50, int(self.rnd.gauss(33, 8))))
                pct = marks * 2
                grade = 'A+' if pct >= 90 else 'A' if pct >= 80 else 'B+' if pct >= 70 else 'B' if pct >= 60 else 'C' if pct >= 50 else 'D'
                results.append(StudentExamResult(exam=exam, student_id=sid, marks_obtained=D(marks), grade=grade,
                                                 is_pass=marks >= 20, entered_by_id=off.faculty_id))
        StudentExamResult.objects.bulk_create(results, batch_size=5000)
        return f"{len(exams)} exams, {len(results)} results"

    def _assignments(self):
        from campusflow_app.models import Assignment, AssignmentSubmission, CourseOffering, StudentCourseRegistration
        from campusflow_app.services.academics import get_current_term
        if Assignment.objects.exists():
            return "already seeded"
        term = get_current_term()
        offs = list(CourseOffering.objects.filter(term=term, faculty__isnull=False).select_related('course__department', 'section', 'batch__program'))
        assignments = [Assignment(title=f"Assignment 1 — {off.course.course_name} ({off.batch.program.short_name} {off.section.name})",
                                  description=f"Answer the questions on units 1–2 of {off.course.course_name}. Submit as PDF.",
                                  department=off.course.department, course=off.course, created_by_id=off.faculty_id,
                                  due_date=timezone.now() + timedelta(days=(i % 3) * 7 - 3), notify_parents=False)
                       for i, off in enumerate(offs)]
        Assignment.objects.bulk_create(assignments, batch_size=1000)
        regs = {}
        for r in StudentCourseRegistration.objects.filter(term=term).select_related('student'):
            regs.setdefault(r.offering_id, []).append(r.student.user_id)
        subs = []
        for off, a in zip(offs, assignments):
            for uid in regs.get(off.id, []):
                roll = self.rnd.random()
                if roll < 0.45:
                    subs.append(AssignmentSubmission(assignment=a, student_id=uid, status='graded', grade=self.rnd.choice(['A', 'A', 'B', 'B', 'C']),
                                                     text_submission="Submitted my answers.", feedback="Good work."))
                elif roll < 0.75:
                    subs.append(AssignmentSubmission(assignment=a, student_id=uid, status='submitted', text_submission="Please find my submission."))
        AssignmentSubmission.objects.bulk_create(subs, batch_size=5000)
        return f"{len(assignments)} assignments, {len(subs)} submissions"

    def _fees(self):
        from campusflow_app.models import (
            Batch, FeeCategory, FeePayment, FeeStructure, FeeStructureItem, StudentFeeInvoice, StudentFeeInvoiceItem,
        )
        from campusflow_app.services.academics import get_current_term
        if FeeStructure.objects.exists():
            return "already seeded"
        self._load()
        term = get_current_term()
        cats = {n: FeeCategory.objects.get_or_create(name=n, defaults={'description': f"{n} fee"})[0]
                for n in ('Tuition Fee', 'Examination Fee', 'Library Fee', 'Development Fee', 'Sports & Cultural Fee')}
        tuition = {'Engineering': 55000, 'Pharmacy': 50000, 'Management': 45000, 'Computer Applications': 35000,
                   'Science': 18000, 'Commerce': 15000, 'Arts': 12000}
        stream_of = {d: s for d, _, s, _ in STREAMS}
        structures = {}
        for batch in Batch.objects.select_related('program__department'):
            p = batch.program
            fs = FeeStructure.objects.create(
                name=f"{p.short_name} {batch.name} — Semester {batch.current_semester_number}", department=p.department,
                program=p, batch=batch, semester_number=batch.current_semester_number, academic_year_ref=term.academic_year,
                program_enrolled_in=p.name[:50], batch_academic_year=batch.name,
                current_semester_year=f"Semester {batch.current_semester_number}")
            amounts = {'Tuition Fee': tuition[stream_of[p.department.code]] * (1.3 if p.level == 'pg' else 1),
                       'Examination Fee': 2500, 'Library Fee': 1500, 'Development Fee': 5000, 'Sports & Cultural Fee': 1000}
            FeeStructureItem.objects.bulk_create([FeeStructureItem(fee_structure=fs, category=cats[k], amount=D(round(v)))
                                                  for k, v in amounts.items()])
            structures[batch.id] = (fs, amounts)

        invoices, inv_items, payments = [], [], []
        due = term.start_date + timedelta(days=45)
        for n, sp in enumerate(self.students, start=1):
            if sp.batch_id not in structures:
                continue
            fs, amounts = structures[sp.batch_id]
            total = D(round(sum(amounts.values())))
            roll = n % 10
            paid = total if roll < 5 else (total / 2).quantize(D('1')) if roll < 7 else D(0)
            invoices.append(StudentFeeInvoice(student=sp.user, fee_structure=fs, invoice_number=f"DMY-INV-{n:05d}", due_date=due,
                                              total_amount=total, paid_amount=paid,
                                              status='paid' if paid == total else 'partially_paid' if paid else 'unpaid'))
        StudentFeeInvoice.objects.bulk_create(invoices, batch_size=2000)
        fee_staff = self._user('fees')
        methods = ['upi', 'cash', 'card', 'net_banking', 'online']
        for n, inv in enumerate(invoices, start=1):
            _, amounts = next(v for v in structures.values() if v[0].id == inv.fee_structure_id)
            inv_items += [StudentFeeInvoiceItem(invoice=inv, category=cats[k], amount=D(round(v))) for k, v in amounts.items()]
            if inv.paid_amount:
                payments.append(FeePayment(invoice=inv, amount_paid=inv.paid_amount, payment_method=methods[n % 5],
                                           transaction_reference=f"TXN{n:08d}", receipt_number=f"DMY-RCP-{n:05d}",
                                           collected_by=fee_staff, remarks="Dummy payment"))
        StudentFeeInvoiceItem.objects.bulk_create(inv_items, batch_size=5000)
        FeePayment.objects.bulk_create(payments, batch_size=2000)
        return f"{len(structures)} fee structures, {len(invoices)} invoices, {len(payments)} payments"

    def _staff_users(self):
        return [u for u in User.objects.filter(username__startswith=U).exclude(
            groups__name__in=['student', 'guardian', 'CA']).order_by('id')]

    def _leave(self):
        from campusflow_app.models import LeaveBalance, LeaveRequest, LeaveType
        from campusflow_app.services.academics import get_current_term
        if LeaveRequest.objects.exists():
            return "already seeded"
        ay = get_current_term().academic_year.name
        types = [LeaveType.objects.get_or_create(code=c, defaults={'name': n, 'max_days': d, 'is_paid': p})[0]
                 for c, n, d, p in (('CL', 'Casual Leave', 12, True), ('SL', 'Sick Leave', 10, True),
                                    ('EL', 'Earned Leave', 15, True), ('LWP', 'Leave Without Pay', 30, False))]
        staff = self._staff_users()
        LeaveBalance.objects.bulk_create([LeaveBalance(user=u, leave_type=t, academic_year=ay, allocated=t.max_days,
                                                       used=(u.id + i) % 4)
                                          for u in staff for i, t in enumerate(types[:3])], ignore_conflicts=True)
        principal = self._user('principal')
        today = date.today()
        reqs = []
        for i, u in enumerate(staff[:60]):
            start = today + timedelta(days=(i % 20) - 8)
            status = ['pending', 'approved', 'approved', 'rejected', 'pending'][i % 5]
            reqs.append(LeaveRequest(user=u, leave_type=types[i % 3], start_date=start, end_date=start + timedelta(days=i % 3),
                                     reason=['Family function', 'Medical appointment', 'Attending a conference',
                                             'Personal work', 'Fever'][i % 5], status=status,
                                     approved_by=principal if status != 'pending' else None,
                                     rejection_reason='Exams scheduled that week' if status == 'rejected' else None))
        LeaveRequest.objects.bulk_create(reqs)
        return f"{len(types)} leave types, {len(reqs)} requests"

    def _payroll(self):
        from campusflow_app.models import Payslip, SalaryStructure
        first_run = not SalaryStructure.objects.exists()
        basic = {'Management': 150000, 'Principal': 140000, 'Department Head': 110000, 'Administrator': 70000, 'Faculty': 65000}
        structures = []
        have = set(SalaryStructure.objects.values_list('user_id', flat=True))
        for u in self._staff_users():
            if u.id in have:
                continue  # staff added on a later deploy still get a salary structure
            group = u.groups.first().name
            b = D(basic.get(group, 25000) + (u.id % 7) * 1000)
            structures.append(SalaryStructure(user=u, basic_pay=b, hra=(b * D('0.24')).quantize(D('1')), da=(b * D('0.17')).quantize(D('1')),
                                              ta=D(1600), pf_deduction=min(D(1800), (b * D('0.12')).quantize(D('1'))),
                                              tds_deduction=(b * D('0.05')).quantize(D('1')) if b > 50000 else D(0)))
        SalaryStructure.objects.bulk_create(structures)
        if not first_run:
            return f"{len(structures)} new salary structures" if structures else "already seeded"
        today = date.today()
        payslips = []
        payroll_officer = self._user('payroll')
        for back in (3, 2, 1):
            m = (today.month - back - 1) % 12 + 1
            y = today.year if today.month - back > 0 else today.year - 1
            for s in structures:
                gross = s.basic_pay + s.hra + s.da + s.ta
                ded = s.pf_deduction + s.tds_deduction
                payslips.append(Payslip(user=s.user, month=m, year=y, total_working_days=26, present_days=24, leave_days=2,
                                        gross_salary=gross, total_deductions=ded, pf_deduction=s.pf_deduction,
                                        tds_deduction=s.tds_deduction, net_payable=gross - ded,
                                        status='paid' if back > 1 else 'finalized', finalized_by=payroll_officer))
        Payslip.objects.bulk_create(payslips, ignore_conflicts=True)
        return f"{len(structures)} salary structures, {len(payslips)} payslips"

    def _library(self):
        from campusflow_app.models import Book, BookCopy, BookIssue
        if Book.objects.exists():
            return "already seeded"
        self._load()
        titles = [("Introduction to Algorithms", "Cormen, Leiserson, Rivest", "MIT Press"),
                  ("Operating System Concepts", "Silberschatz, Galvin", "Wiley"),
                  ("Computer Networks", "Andrew S. Tanenbaum", "Pearson"),
                  ("Database System Concepts", "Korth, Sudarshan", "McGraw Hill"),
                  ("Engineering Mathematics", "B.S. Grewal", "Khanna"),
                  ("Fundamentals of Physics", "Halliday, Resnick", "Wiley"),
                  ("Organic Chemistry", "Morrison & Boyd", "Pearson"),
                  ("Principles of Economics", "N. Gregory Mankiw", "Cengage"),
                  ("Financial Accounting", "T.S. Grewal", "Sultan Chand"),
                  ("Marketing Management", "Philip Kotler", "Pearson"),
                  ("Strength of Materials", "R.K. Bansal", "Laxmi"),
                  ("Thermodynamics", "P.K. Nag", "McGraw Hill"),
                  ("Electrical Machines", "P.S. Bimbhra", "Khanna"),
                  ("Signals and Systems", "Oppenheim", "Pearson"),
                  ("Pharmacology", "K.D. Tripathi", "Jaypee"),
                  ("Indian Economy", "Ramesh Singh", "McGraw Hill"),
                  ("Let Us C", "Yashavant Kanetkar", "BPB"),
                  ("Clean Code", "Robert C. Martin", "Prentice Hall"),
                  ("Human Resource Management", "Gary Dessler", "Pearson"),
                  ("Pride and Prejudice", "Jane Austen", "Penguin")]
        books = [Book(title=f"{t}" + (f" (Vol. {v + 1})" if v else ""), author=a, publisher=p,
                      isbn=f"978{(i * 3 + v):010d}", total_copies=4, available_copies=4)
                 for i, (t, a, p) in enumerate(titles) for v in range(2)]
        Book.objects.bulk_create(books)
        copies = [BookCopy(book=b, barcode=f"DMY-BK-{b.id:04d}-{c + 1}", status='Available') for b in books for c in range(4)]
        BookCopy.objects.bulk_create(copies)
        issues = []
        today = date.today()
        for i, copy in enumerate(copies[::2][:60]):
            sp = self.students[(i * 31) % len(self.students)]
            issued = today - timedelta(days=5 + i % 25)
            returned = issued + timedelta(days=10) if i % 3 == 0 else None
            overdue = not returned and issued + timedelta(days=14) < today
            issues.append(BookIssue(book_copy=copy, student=sp, issued_date=issued, due_date=issued + timedelta(days=14),
                                    returned_date=returned, status='Returned' if returned else 'Overdue' if overdue else 'Issued',
                                    fine_amount=D(50) if overdue else D(0)))
            if not returned:
                copy.status = 'Issued'
        BookIssue.objects.bulk_create(issues)
        BookCopy.objects.bulk_update([c for c in copies if c.status == 'Issued'], ['status'])
        for b in books:
            b.available_copies = BookCopy.objects.filter(book=b, status='Available').count()
        Book.objects.bulk_update(books, ['available_copies'])
        return f"{len(books)} titles, {len(copies)} copies, {len(issues)} issues"

    def _hostel(self):
        from campusflow_app.models import Hostel, HostelAllocation, HostelRoom
        if Hostel.objects.exists():
            return "already seeded"
        self._load()
        allocs = []
        for name, gender, gname in (("Vivekananda Boys Hostel", 'Boys', 'Male'), ("Savitribai Girls Hostel", 'Girls', 'Female')):
            hostel = Hostel.objects.create(name=name, gender_type=gender, capacity=150, address="Dummy College Campus")
            rooms = HostelRoom.objects.bulk_create([HostelRoom(hostel=hostel, room_number=f"{f}{r:02d}", capacity=3,
                                                               rent_per_semester=D(18000))
                                                    for f in range(1, 6) for r in range(1, 11)])
            residents = [sp for sp in self.students if sp.gender == gname][::7][:120]
            for i, sp in enumerate(residents):
                room = rooms[i // 3]
                allocs.append(HostelAllocation(student=sp, room=room, allocated_date=date(sp.batch.admission_year, 8, 1) if sp.batch else date.today(),
                                               status='Allocated'))
                room.occupied_beds += 1
            HostelRoom.objects.bulk_update(rooms, ['occupied_beds'])
        HostelAllocation.objects.bulk_create(allocs)
        return f"2 hostels, {len(allocs)} residents"

    def _transport(self):
        from campusflow_app.models import BusRoute, BusSubscription
        if BusRoute.objects.exists():
            return "already seeded"
        self._load()
        routes_def = [("Route 1 — Hadapsar", ["Hadapsar", "Magarpatta", "Mundhwa", "Koregaon Park", "Campus"]),
                      ("Route 2 — Kothrud", ["Kothrud Depot", "Karve Nagar", "Deccan", "Shivajinagar", "Campus"]),
                      ("Route 3 — Pimpri", ["Pimpri", "Chinchwad", "Akurdi", "Wakad", "Campus"]),
                      ("Route 4 — Katraj", ["Katraj", "Bibwewadi", "Swargate", "Camp", "Campus"])]
        today = date.today()
        subs = []
        for i, (name, stops) in enumerate(routes_def, start=1):
            route = BusRoute.objects.create(
                name=name, driver=self._user(f'driver{i}'), conductor=self._user(f'conductor{i}'), is_active=True,
                stops=[{"name": s, "lat": 18.50 + i * 0.01 + j * 0.005, "lng": 73.80 + j * 0.01, "order": j + 1}
                       for j, s in enumerate(stops)])
            for j, sp in enumerate(self.students[i::9][:60]):
                subs.append(BusSubscription(user=sp.user, route=route, status='active', valid_from=today - timedelta(days=60),
                                            valid_until=today + timedelta(days=120), boarding_stop=stops[j % (len(stops) - 1)]))
        BusSubscription.objects.bulk_create(subs, ignore_conflicts=True)
        return f"4 routes, {len(subs)} subscriptions"

    def _inventory(self):
        from campusflow_app.models import Department, InventoryCategory, InventoryItem, InventoryTransaction, Supplier
        if InventoryItem.objects.exists():
            return "already seeded"
        items_def = {"Lab Equipment": [("Digital Multimeter", "pcs"), ("Oscilloscope", "pcs"), ("Beaker 500ml", "pcs"), ("Microscope", "pcs")],
                     "IT Hardware": [("Desktop Computer", "pcs"), ("Projector", "pcs"), ("Network Switch", "pcs"), ("Keyboard", "pcs")],
                     "Stationery": [("A4 Paper Ream", "ream"), ("Whiteboard Marker", "box"), ("Answer Booklet", "pcs")],
                     "Furniture": [("Student Bench", "pcs"), ("Faculty Chair", "pcs"), ("Steel Almirah", "pcs")],
                     "Housekeeping": [("Floor Cleaner", "litre"), ("Hand Sanitiser", "litre")]}
        suppliers = Supplier.objects.bulk_create([Supplier(name=n, contact_person=c, email=f"sales{i}@supplier.example.com",
                                                           address="Industrial Area, Pune")
                                                  for i, (n, c) in enumerate([("Shree Scientific Traders", "Mr. Shah"), ("TechWorld IT Solutions", "Ms. Rao"),
                                                                              ("Om Stationers", "Mr. Kale"), ("Comfort Furniture Works", "Mr. Bhat"),
                                                                              ("CleanPro Supplies", "Ms. Dsouza")])])
        depts = list(Department.objects.all())
        txns = []
        for ci, (cat, items) in enumerate(items_def.items()):
            category = InventoryCategory.objects.create(name=cat, description=f"{cat} stock")
            for ii, (name, unit) in enumerate(items):
                item = InventoryItem.objects.create(category=category, name=name, unit=unit, quantity=50 + ii * 20, threshold_level=10)
                txns.append(InventoryTransaction(item=item, transaction_type='Restock', quantity=item.quantity + 10,
                                                 supplier=suppliers[ci % len(suppliers)], remarks="Opening stock"))
                txns.append(InventoryTransaction(item=item, transaction_type='Issue', quantity=10,
                                                 department=depts[(ci + ii) % len(depts)], remarks="Issued to department"))
        InventoryTransaction.objects.bulk_create(txns)
        return f"{InventoryItem.objects.count()} items, {len(txns)} transactions"

    def _placements(self):
        from campusflow_app.models import PlacementApplication, RecruitmentDrive
        if RecruitmentDrive.objects.exists():
            return "already seeded"
        self._load()
        today = date.today()
        drives = RecruitmentDrive.objects.bulk_create([
            RecruitmentDrive(company_name=c, job_title=j, package_lpa=D(p), drive_date=today + timedelta(days=dd),
                             status='Completed' if dd < 0 else 'Upcoming', eligibility_criteria="60% aggregate, no active backlogs",
                             job_description=f"{j} role at {c}.")
            for c, j, p, dd in [("Infosys", "Systems Engineer", "3.6", -40), ("TCS", "Assistant System Engineer", "3.4", -25),
                                ("Persistent Systems", "Software Engineer", "6.5", -10), ("Deloitte", "Business Analyst", "7.0", 12),
                                ("Bajaj Auto", "Graduate Engineer Trainee", "5.5", 20), ("HDFC Bank", "Relationship Manager", "4.8", 30)]])
        final_year = [sp for sp in self.students if sp.batch and sp.program and sp.current_semester_number
                      and sp.current_semester_number >= sp.program.total_terms - 1]
        apps = []
        for i, sp in enumerate(final_year[:240]):
            drive = drives[i % len(drives)]
            done = drive.status == 'Completed'
            status = (['Selected', 'Rejected', 'Shortlisted', 'Rejected'][i % 4]) if done else 'Applied'
            apps.append(PlacementApplication(drive=drive, student=sp, status=status,
                                             offered_ctc_lpa=drive.package_lpa if status == 'Selected' else None))
        PlacementApplication.objects.bulk_create(apps, ignore_conflicts=True)
        return f"{len(drives)} drives, {len(apps)} applications"

    def _finance(self):
        from campusflow_app.management.commands.seed_accreditation_criteria import NAAC_CRITERIA, NBA_CRITERIA
        from campusflow_app.management.commands.seed_compliance_certificate_types import CATALOG
        from campusflow_app.models import (
            AccreditationCriterion, AuditEngagement, AuditorProfile, ComplianceCertificateType, Department, ExpenseCategory,
            ExpenseEntry, FinancialYear, FixedAsset, IncomeCategory, IncomeEntry, Supplier,
        )
        for body, catalog in (('NAAC', NAAC_CRITERIA), ('NBA', NBA_CRITERIA)):
            for code, title in catalog:
                AccreditationCriterion.objects.get_or_create(body=body, code=code, defaults={'title': title})
        for row in CATALOG:
            name, authority, renews, varies = row[:4]
            ComplianceCertificateType.objects.get_or_create(name=name, defaults={
                'issuing_authority': authority, 'renews_annually': renews, 'varies_by_state': varies})
        if FinancialYear.objects.exists():
            return "already seeded"
        today = date.today()
        y = today.year if today.month >= 4 else today.year - 1
        fy = FinancialYear.objects.create(label=f"FY {y}-{(y + 1) % 100:02d}", start_date=date(y, 4, 1), end_date=date(y + 1, 3, 31),
                                          opening_cash_balance=D(250000), opening_bank_balance=D(12500000))
        FinancialYear.objects.create(label=f"FY {y - 1}-{y % 100:02d}", start_date=date(y - 1, 4, 1), end_date=date(y, 3, 31),
                                     is_locked=True, opening_cash_balance=D(180000), opening_bank_balance=D(9800000))
        accounts = self._user('accounts')
        inc = [IncomeCategory.objects.create(name=n) for n in ('Tuition Fees', 'Examination Fees', 'Government Grants', 'Donations', 'Hostel Fees')]
        exp = [ExpenseCategory.objects.create(name=n) for n in ('Salaries', 'Electricity', 'Lab Consumables', 'Maintenance', 'Library Books', 'Events')]
        suppliers = list(Supplier.objects.all()) or [None]
        depts = list(Department.objects.all())
        IncomeEntry.objects.bulk_create([IncomeEntry(category=inc[i % len(inc)], financial_year=fy, amount=D(150000 + i * 37000),
                                                     source="Dummy income", received_date=date(y, 4 + i % 9, 5 + i % 20),
                                                     receipt_reference=f"DMY-INC-{i + 1:03d}", recorded_by=accounts) for i in range(20)])
        ExpenseEntry.objects.bulk_create([ExpenseEntry(category=exp[i % len(exp)], financial_year=fy, department=depts[i % len(depts)],
                                                       amount=D(40000 + i * 12500), vendor=suppliers[i % len(suppliers)],
                                                       payment_date=date(y, 4 + i % 9, 3 + i % 20), payment_reference=f"DMY-EXP-{i + 1:03d}",
                                                       recorded_by=accounts) for i in range(25)])
        FixedAsset.objects.bulk_create([FixedAsset(name=n, category=c, department=depts[i % len(depts)], purchase_date=date(y - 2 + i % 3, 6, 1),
                                                   purchase_cost=D(cost), depreciation_method='SLM', depreciation_rate_percent=D(10),
                                                   supplier=suppliers[i % len(suppliers)])
                                        for i, (n, c, cost) in enumerate([("Computer Lab 1 PCs", "IT Hardware", 1800000), ("College Bus MH12-AB-1234", "Vehicle", 2800000),
                                                                          ("Auditorium Sound System", "Equipment", 450000), ("Library Furniture", "Furniture", 320000),
                                                                          ("CNC Machine", "Lab Equipment", 2200000), ("Solar Panels", "Infrastructure", 1500000)])])
        auditor = AuditorProfile.objects.first()
        if auditor:
            AuditEngagement.objects.create(auditor=auditor, financial_year=fy, access_start=today - timedelta(days=10),
                                           access_end=today + timedelta(days=180), granted_by=self._user('director'))
        return f"{fy.label}, 45 ledger entries, 6 fixed assets"

    def _audit_years(self):
        """Give the previous (closed) FY its own ledger, and the CA an engagement for
        every FY, so the audit portal's year switch has something to switch to.
        Idempotent: only adds entries to a year with none, and missing engagements."""
        from campusflow_app.models import (
            AuditEngagement, AuditorProfile, Department, ExpenseCategory, ExpenseEntry, FinancialYear,
            IncomeCategory, IncomeEntry, Supplier,
        )
        auditor = AuditorProfile.objects.filter(user__username=U + 'auditor').first()
        if not auditor:
            return "no auditor account"
        accounts = self._user('accounts') or User.objects.filter(username=U + 'accounts').first()
        inc = list(IncomeCategory.objects.all())
        exp = list(ExpenseCategory.objects.all())
        suppliers = list(Supplier.objects.all()) or [None]
        depts = list(Department.objects.all())
        added = 0
        for fy in FinancialYear.objects.order_by('start_date'):
            if inc and exp and not fy.income_entries.exists():
                y = fy.start_date.year
                IncomeEntry.objects.bulk_create([IncomeEntry(
                    category=inc[i % len(inc)], financial_year=fy, amount=D(120000 + i * 31000), source="Dummy income",
                    received_date=date(y, 4 + i % 9, 5 + i % 20), receipt_reference=f"DMY-INC-{y % 100:02d}-{i + 1:03d}",
                    recorded_by=accounts) for i in range(15)])
                ExpenseEntry.objects.bulk_create([ExpenseEntry(
                    category=exp[i % len(exp)], financial_year=fy, department=depts[i % len(depts)] if depts else None,
                    amount=D(35000 + i * 11000), vendor=suppliers[i % len(suppliers)],
                    payment_date=date(y, 4 + i % 9, 3 + i % 20), payment_reference=f"DMY-EXP-{y % 100:02d}-{i + 1:03d}",
                    recorded_by=accounts) for i in range(18)])
            if not AuditEngagement.objects.filter(auditor=auditor, financial_year=fy).exists():
                today = date.today()
                AuditEngagement.objects.create(auditor=auditor, financial_year=fy, access_start=today - timedelta(days=10),
                                               access_end=today + timedelta(days=180), granted_by=self._user('director'))
                added += 1
        return f"{added} new engagements" if added else "already seeded"

    def _clearance(self):
        """Real clearance desks (each owned by the role that signs it off) and a
        final-exit no-dues request for final-semester students, so the Fee Counter
        has fee clearances to work. Idempotent."""
        from campusflow_app.models import ClearanceDesk, ClearanceRequest, StudentProfile
        from campusflow_app.services.academics import get_current_term
        from campusflow_app.services.clearance import create_clearance_request

        for order, (name, code, group, module) in enumerate([
            ("Fees", "fees", "Fee Counter", "fees"), ("Library", "library", "Librarian", "library"),
            ("Hostel", "hostel", "Hostel Warden", "hostel"), ("Department", "department", "Department Head", "none"),
        ], start=1):
            ClearanceDesk.objects.get_or_create(code=code, defaults={
                "name": name, "responsible_group": Group.objects.get(name=group), "linked_module": module, "order": order,
            })
        # Placeholder desks from the generic pass would add sign-offs nobody owns.
        ClearanceDesk.objects.filter(code__startswith="dummy-").update(is_active=False)

        ay = get_current_term().academic_year
        if ClearanceRequest.objects.filter(cycle_type=ClearanceRequest.CYCLE_FINAL_EXIT, academic_year=ay).exists():
            return "already seeded"
        final_year = [sp for sp in StudentProfile.objects.select_related('program', 'user').filter(user__username__startswith=U)
                      if sp.program and sp.current_semester_number and sp.current_semester_number >= sp.program.total_terms - 1]
        for sp in final_year[::4][:60]:
            create_clearance_request(sp, ClearanceRequest.CYCLE_FINAL_EXIT, academic_year=ay, generated_by=self._user('admin'))
        return f"4 desks, {min(60, len(final_year[::4]))} final-exit requests"

    def _announcements(self):
        from campusflow_app.models import Announcement, Department, Notification
        if Announcement.objects.exists():
            return "already seeded"
        self._load()
        rows = [("Welcome to the new academic year!", "Classes for all programmes begin as per the published timetable.", 'principal', 'high', True, None),
                ("Mid-term results published", "Mid-term results are now visible under Exams → Results.", 'admin', 'normal', False, ['student']),
                ("Fee payment deadline", "Pay semester fees before the due date to avoid late fine.", 'accounts', 'urgent', True, ['student', 'guardian']),
                ("Faculty development programme", "FDP on Outcome-Based Education next Saturday in the Seminar Hall.", 'principal', 'normal', False, ['Faculty', 'Department Head']),
                ("Placement drive: Deloitte", "Final-year students register on the TPO portal by Friday.", 'tpo', 'high', False, ['student']),
                ("Library timings extended", "Library will stay open till 9 PM during exams.", 'librarian', 'low', False, None)]
        for title, content, author, prio, pinned, roles in rows:
            Announcement.objects.create(title=title, content=content, author=self._user(author) or self._user('admin'),
                                        priority=prio, is_pinned=pinned, target_roles=roles or [], notify_parents=False)
        cse = Department.objects.filter(code='CSE').first()
        a = Announcement.objects.create(title="CSE department meeting", content="All CSE faculty: meeting on Monday 4 PM.",
                                        author=self._user('hod_cse'), priority='normal', target_roles=['Faculty'], notify_parents=False)
        if cse:
            a.target_departments.add(cse)
        notes = [Notification(recipient=sp.user, title="Fee reminder", body="Your semester fee is due soon.", category='fees')
                 for sp in self.students[:200]]
        notes += [Notification(recipient=sp.user, title="Mid-term result published", body="Check your mid-term marks.", category='exams')
                  for sp in self.students[200:400]]
        Notification.objects.bulk_create(notes)
        return f"7 announcements, {len(notes)} notifications"

    # ── generic pass: a few valid rows in every model that is still empty ──

    GENERIC_SKIP = {'TenantModulePermission'}  # a row here would override the role's default module list
    SINGLETONS = {'InstitutionProfile', 'AttendanceDetentionSettings', 'ClearanceSettings'}

    def _generic_fill(self):
        from django.apps import apps
        self._seq = 0
        filled = []
        for model in apps.get_app_config('campusflow_app').get_models():
            if model.__name__ in self.GENERIC_SKIP:
                continue
            try:
                if self._fill(model, set()):
                    filled.append(model.__name__)
            except Exception:
                pass
        self.stdout.write(f"   ✅ generic pass: {len(filled)} empty models given sample rows"
                          + (f" ({', '.join(filled)})" if filled else ""))

    def _fill(self, model, visiting, rows=5):
        """Ensure `model` has rows; returns True if it created any."""
        if model.objects.exists() or model in visiting:
            return False
        visiting = visiting | {model}
        rows = 1 if model.__name__ in self.SINGLETONS else rows
        made = 0
        for i in range(rows):
            for mode in ('rich', 'required', 'all'):
                try:
                    with transaction.atomic():
                        obj = self._build(model, i, mode, visiting)
                        if obj is None:
                            return made > 0
                        obj.save()
                        for f in model._meta.many_to_many:
                            targets = list(f.related_model.objects.all()[:3])
                            if targets:
                                getattr(obj, f.name).add(*targets)
                    made += 1
                    break
                except Exception:
                    continue
        return made > 0

    def _build(self, model, i, mode, visiting):
        obj = model()
        for f in model._meta.concrete_fields:
            if f.primary_key or getattr(f, 'auto_now', False) or getattr(f, 'auto_now_add', False):
                continue
            needs = not f.null and not f.has_default() and not (f.empty_strings_allowed and f.blank)
            if f.is_relation:
                if not needs and mode == 'required':
                    continue
                target = self._pick(model, f, i, visiting)
                if target is None:
                    if needs:
                        return None
                    continue
                setattr(obj, f.name, target)
                continue
            if f.has_default() and not needs:
                continue  # defaults keep singleton flags (is_current, is_default, ...) valid
            # 'rich'/'required': only fields the DB needs; 'all': every field (some
            # CheckConstraints need an optional field set, e.g. external_member_name)
            if needs or mode == 'all':
                value = self._value(model, f, i)
                if value is not None:
                    setattr(obj, f.attname, value)
        return obj

    def _pick(self, model, f, i, visiting):
        target_model = f.related_model
        if target_model is model:
            return None
        if not target_model.objects.exists() and target_model._meta.app_label == 'campusflow_app':
            self._fill(target_model, visiting)
        qs = target_model.objects.all()
        if target_model is User:
            qs = qs.filter(username__startswith=U)
        if f.unique:  # OneToOne / unique FK: first target not already used
            used = model.objects.values_list(f.attname, flat=True)
            qs = qs.exclude(pk__in=used)
        pks = list(qs.order_by('pk').values_list('pk', flat=True)[:50])
        if not pks:
            return None
        return target_model.objects.get(pk=pks[i % len(pks)] if not f.unique else pks[0])

    def _value(self, model, f, i):
        self._seq += 1
        n = f.name.lower()
        today = timezone.localdate()
        if f.choices:
            return list(f.choices)[i % len(f.choices)][0]
        if isinstance(f, models.BooleanField):
            return i % 2 == 0
        if isinstance(f, (models.FileField,)):
            return f"dummy/{model.__name__.lower()}_{i + 1}.pdf"
        if isinstance(f, models.UUIDField):
            return uuid.uuid4()
        if isinstance(f, models.GenericIPAddressField):
            return f"10.0.{i}.{self._seq % 250 + 1}"
        if isinstance(f, models.JSONField):
            if 'embedding' in n:
                vec = [self.rnd.gauss(0, 1) for _ in range(512)]
                norm = math.sqrt(sum(v * v for v in vec))
                return [v / norm for v in vec]
            return [] if any(k in n for k in ('list', 'items', 'scores', 'offerings', 'recommendations', 'snapshot')) else {}
        if isinstance(f, models.DateTimeField):
            return timezone.now() + self._offset(n, i)
        if isinstance(f, models.DateField):
            return today + self._offset(n, i)
        if isinstance(f, models.TimeField):
            return time(min(17, 9 + i + (1 if 'end' in n else 0)))
        if isinstance(f, models.DecimalField):
            limit = 10 ** (f.max_digits - f.decimal_places) - 1
            base = 75 if 'percent' in n else 35 if 'mark' in n else 7.5 if 'gpa' in n or 'point' in n else \
                25000 if any(k in n for k in ('amount', 'fee', 'cost', 'salary', 'pay', 'stipend', 'value')) else 10 * (i + 1)
            return D(str(min(limit, base)))
        if isinstance(f, models.FloatField):
            return 18.52 if 'lat' in n else 73.85 if ('lng' in n or 'lon' in n) else 0.85 if ('score' in n or 'confidence' in n) else 1.5 * (i + 1)
        if isinstance(f, (models.IntegerField,)):
            if 'month' in n:
                return (i % 12) + 1
            if 'year' in n:
                return today.year
            if 'semester' in n:
                return (i % 8) + 1
            return i + 1
        if isinstance(f, models.EmailField):
            return f"{U}{model.__name__.lower()}{self._seq}@{self.email_domain}"
        if isinstance(f, models.URLField):
            return f"https://example.com/{model.__name__.lower()}/{i + 1}"
        if isinstance(f, models.SlugField):
            return f"dummy-{model.__name__.lower()}-{self._seq}"[:f.max_length]
        if isinstance(f, (models.CharField, models.TextField)):
            if 'phone' in n or 'contact' in n:
                return ''  # never a real-looking number (OTP/WhatsApp safety)
            label = model._meta.verbose_name.title()
            if f.unique or any(k in n for k in ('code', 'number', 'reference', '_id', 'barcode', 'token')):
                value = f"DMY-{self._seq:05d}"
            elif isinstance(f, models.TextField):
                value = f"Sample {label.lower()} {f.verbose_name} for testing (#{i + 1})."
            else:
                value = f"Dummy {label} {i + 1}"
            return value[:f.max_length] if f.max_length else value
        return None

    @staticmethod
    def _offset(name, i):
        if any(k in name for k in ('end', 'until', 'expire', 'vacated', 'returned', 'resolution', 'closed',
                                   'completed', 'decided', 'reviewed', 'to_date', 'due')):
            return timedelta(days=30 + i)
        if any(k in name for k in ('start', 'from', 'begin')):
            return timedelta(days=-30 - i)
        return timedelta(days=-i)

    def _report(self):
        from django.apps import apps
        from campusflow_app.models import StudentProfile
        empty = [m.__name__ for m in apps.get_app_config('campusflow_app').get_models()
                 if m.__name__ not in self.GENERIC_SKIP and not m.objects.exists()]
        self.stdout.write(f"✅ Dummy college ready: {StudentProfile.objects.count()} students, "
                          f"{User.objects.filter(username__startswith=U).count()} accounts.")
        if empty:
            self.stdout.write(self.style.WARNING(f"   Still empty ({len(empty)}): {', '.join(empty)}"))
        if self.failures:
            self.stdout.write(self.style.WARNING(f"   Sections that failed (will retry next run): {', '.join(self.failures)}"))
        self.stdout.write("   Logins (password: $DUMMY_SEED_PASSWORD, default Dummy@123): dmy_director (Management), "
                          "dmy_admin (Administrator), dmy_principal, dmy_hod_cse, dmy_fac_cse_01, dmy_btcse26001 (student), "
                          "dmy_librarian, dmy_fees, dmy_warden_boys, dmy_tpo, dmy_auditor (CA)")

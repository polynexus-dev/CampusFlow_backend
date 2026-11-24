import re
from django.db import connection
from campusflow_app.models.profile import (
    TeachingStaffProfile,
    NonTeachingStaffProfile,
    ManagementProfile,
    AdministratorProfile,
    PrincipalProfile,
    DepartmentHeadProfile,
)

ROLE_PREFIX_MAP = {
    'Faculty': 'FAC',
    'Department Head': 'HOD',
    'Principal': 'PRN',
    'Administrator': 'ADM',
    'Management': 'MGT',
    'Supervisor': 'SUP',
    'Accounts Officer': 'ACT',
    'Fee Counter': 'FEE',
    'Transport Coordinator': 'TRS',
    'Driver': 'DRV',
    'Conductor': 'CND',
    'Librarian': 'LIB',
    'Hostel Warden': 'HST',
    'Store Manager': 'STR',
    'Placement Officer': 'TPO',
    'Scholarship Officer': 'SCH',
    'Admissions Officer': 'ADM-OFF',
    'Canteen Staff': 'CNT',
    'Support Staff': 'SUP',
}

def get_department_code(department):
    """
    Derives a short clean uppercase department code (e.g., 'CSE', 'MECH', 'ECE').
    If department is None, returns 'CENTRAL'.
    """
    if not department:
        return 'CENTRAL'

    dept_name = getattr(department, 'name', str(department)).strip()

    # 1. Check for standard parenthesized abbreviation like "Computer Science Engineering (CSE)"
    match = re.search(r'\(([^)]+)\)', dept_name)
    if match:
        code = re.sub(r'[^A-Za-z0-9]', '', match.group(1)).upper()
        if code:
            return code

    # 2. Extract acronym from uppercase or words
    words = [w for w in re.split(r'[\s\-_]+', dept_name) if w.lower() not in ('dept', 'department', 'of', 'and', '&')]
    if len(words) >= 2:
        acronym = "".join(w[0] for w in words).upper()
        return acronym[:6]
    elif len(words) == 1:
        clean = re.sub(r'[^A-Za-z0-9]', '', words[0]).upper()
        return clean[:4]

    return 'DEPT'


def generate_unique_employee_id(role, department=None, designation=None):
    """
    Generates a unique, clean sequential employee ID in the format:
    [DEPT]-[ROLE]-[0001]
    e.g. CSE-FAC-0001, CENTRAL-ADM-0001, CENTRAL-LIB-0001
    """
    dept_code = get_department_code(department)
    role_code = ROLE_PREFIX_MAP.get(role, 'EMP')
    
    prefix = f"{dept_code}-{role_code}-"

    # Query all employee profiles to find the highest number for this prefix
    profiles_models = [
        TeachingStaffProfile,
        NonTeachingStaffProfile,
        ManagementProfile,
        AdministratorProfile,
        PrincipalProfile,
        DepartmentHeadProfile,
    ]

    existing_ids = set()
    for model in profiles_models:
        ids = model.objects.filter(employee_id__startswith=prefix).values_list('employee_id', flat=True)
        existing_ids.update(ids)

    # Find highest sequence
    max_num = 0
    pattern = re.compile(rf"^{re.escape(prefix)}(\d+)$")
    for eid in existing_ids:
        m = pattern.match(eid)
        if m:
            num = int(m.group(1))
            if num > max_num:
                max_num = num

    # Generate next sequential ID and ensure absolute uniqueness
    next_num = max_num + 1
    while True:
        candidate_id = f"{prefix}{next_num:04d}"
        in_use = any(model.objects.filter(employee_id=candidate_id).exists() for model in profiles_models)
        if not in_use:
            return candidate_id
        next_num += 1


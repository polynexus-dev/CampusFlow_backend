from django.db import models
from django.contrib.auth.models import User

from .department import Department

# Student Profile Model (remains mostly the same, ensuring 'unique=True' is appropriate)
class StudentProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student_profile')
    student_id = models.CharField(max_length=20, unique=True, help_text="Unique student identifier within this college")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='students')
    locked_device_id = models.CharField(max_length=255, null=True, blank=True, help_text="Device ID for locking student to a specific phone")
    is_face_registered = models.BooleanField(
        default=False,
        help_text="True once all three face angles have been captured and stored.",
    )

    # Basic Information
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=10, blank=True, null=True)
    blood_group = models.CharField(max_length=5, blank=True, null=True)
    aadhaar_number = models.CharField(max_length=12, unique=True, blank=True, null=True)
    nationality = models.CharField(max_length=100, blank=True, null=True)
    religion = models.CharField(max_length=100, blank=True, null=True) # NEW
    category = models.CharField(max_length=50, blank=True, null=True) # NEW
    disability_status = models.BooleanField(default=False, blank=True, null=True) # NEW
    disability_details = models.TextField(blank=True, null=True) # NEW
    emergency_contact_name = models.CharField(max_length=255, blank=True, null=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True, null=True)

    # Contact Information
    contact_number = models.CharField(max_length=15, blank=True, null=True)
    alternate_phone_number = models.CharField(max_length=15, blank=True, null=True)
    current_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    current_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    current_city = models.CharField(max_length=100, blank=True, null=True)
    current_district = models.CharField(max_length=100, blank=True, null=True)
    current_state = models.CharField(max_length=100, blank=True, null=True)
    current_pincode = models.CharField(max_length=10, blank=True, null=True)
    permanent_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    permanent_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    permanent_city = models.CharField(max_length=100, blank=True, null=True)
    permanent_district = models.CharField(max_length=100, blank=True, null=True)
    permanent_state = models.CharField(max_length=100, blank=True, null=True)
    permanent_pincode = models.CharField(max_length=10, blank=True, null=True)

    # Academic Information
    admission_date = models.DateField(blank=True, null=True) # NEW
    admission_number = models.CharField(max_length=50, blank=True, null=True) # NEW
    program_enrolled_in = models.CharField(max_length=50,blank=True, null=True) # NEW - Assuming a 'Course' model
    batch_academic_year = models.CharField(max_length=50, blank=True, null=True) # NEW
    current_semester_year = models.CharField(max_length=50, blank=True, null=True) # NEW
    section_division = models.CharField(max_length=10, blank=True, null=True) # NEW
    previous_school_college = models.CharField(max_length=255, blank=True, null=True) # NEW
    tenth_marksheet_percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True) # NEW
    twelfth_marksheet_percentage = models.DecimalField(max_digits=5, decimal_places=2, blank=True, null=True) # NEW
    
    # Login & Security (Status in profile, Username/Password/Email in User model)
    status = models.CharField(max_length=20, default='active') # This was in staff, now added to student too

    # Additional
    profile_picture = models.ImageField(upload_to='profile_pics/students/', blank=True, null=True)
    biometric_id = models.CharField(max_length=255, unique=True, blank=True, null=True) # NEW
    hostel_transport_details = models.TextField(blank=True, null=True) # NEW
    scholarship_fee_concession_details = models.TextField(blank=True, null=True) # NEW
    medical_conditions_allergies = models.TextField(blank=True, null=True) # NEW
    extracurricular_interests = models.TextField(blank=True, null=True) # NEW


    class Meta:
        verbose_name = "Student Profile"
        verbose_name_plural = "Student Profiles"

    def __str__(self):
        return f"Student: {self.user.username} ({self.student_id})"

# Teaching Staff Profile Model (remains the same)
class TeachingStaffProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='teaching_staff_profile')
    employee_id = models.CharField(max_length=20, unique=True, help_text="Unique employee identifier across all teaching staff")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='teaching_staff')

    # Basic Information
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=10,blank=True, null=True)
    blood_group = models.CharField(max_length=5, blank=True, null=True)
    aadhaar_number = models.CharField(max_length=12, unique=True, blank=True, null=True)
    nationality = models.CharField(max_length=100, blank=True, null=True)
    emergency_contact_name = models.CharField(max_length=255, blank=True, null=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True, null=True)

    # Contact Information
    contact_number = models.CharField(max_length=15, blank=True, null=True) # Primary phone number
    alternate_phone_number = models.CharField(max_length=15, blank=True, null=True)
    current_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    current_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    current_city = models.CharField(max_length=100, blank=True, null=True)
    current_district = models.CharField(max_length=100, blank=True, null=True)
    current_state = models.CharField(max_length=100, blank=True, null=True)
    current_pincode = models.CharField(max_length=10, blank=True, null=True)
    permanent_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    permanent_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    permanent_city = models.CharField(max_length=100, blank=True, null=True)
    permanent_district = models.CharField(max_length=100, blank=True, null=True)
    permanent_state = models.CharField(max_length=100, blank=True, null=True)
    permanent_pincode = models.CharField(max_length=10, blank=True, null=True)

    # Professional Information
    date_of_joining = models.DateField(blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True)
    qualifications = models.TextField(blank=True, null=True, help_text="e.g., Ph.D., M.Tech, NET, SET")
    specializations = models.TextField(blank=True, null=True, help_text="Subjects taught or areas of specialization")
    experience_years = models.PositiveIntegerField(blank=True, null=True)
    employee_type = models.CharField(max_length=20, default='full_time')
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    pan_number = models.CharField(max_length=10, unique=True, blank=True, null=True)
    epf_esi_details = models.TextField(blank=True, null=True)

    # Login & Security (Role and Status)
    staff_role = models.CharField(max_length=50, default='lecturer', help_text="Specific role within teaching staff (e.g., Professor, HOD)")
    status = models.CharField(max_length=20, default='active')

    # Additional
    profile_picture = models.ImageField(upload_to='profile_pics/teaching_staff/', blank=True, null=True)
    office_room_number = models.CharField(max_length=20, blank=True, null=True)
    research_interests = models.TextField(blank=True, null=True)
    publications_link = models.URLField(max_length=500, blank=True, null=True)
    replacement_availability_preferences = models.TextField(blank=True, null=True, help_text="e.g., Available for substitutes on Tuesdays after 2 PM")


    class Meta:
        verbose_name = "Teaching Staff Profile"
        verbose_name_plural = "Teaching Staff Profiles"

    def __str__(self):
        return f"Teaching Staff: {self.user.username} ({self.employee_id})"

# Non-Teaching Staff Profile Model (remains the same)
class NonTeachingStaffProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='non_teaching_staff_profile')
    employee_id = models.CharField(max_length=20, unique=True, help_text="Unique employee identifier across all non-teaching staff")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='non_teaching_staff')

    # Basic Information
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=10, blank=True, null=True)
    aadhaar_number = models.CharField(max_length=12, unique=True, blank=True, null=True)
    emergency_contact_name = models.CharField(max_length=255, blank=True, null=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True, null=True)

    # Contact Information
    contact_number = models.CharField(max_length=15, blank=True, null=True)
    current_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    current_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    current_city = models.CharField(max_length=100, blank=True, null=True)
    current_district = models.CharField(max_length=100, blank=True, null=True)
    current_state = models.CharField(max_length=100, blank=True, null=True)
    current_pincode = models.CharField(max_length=10, blank=True, null=True)
    permanent_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    permanent_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    permanent_city = models.CharField(max_length=100, blank=True, null=True)
    permanent_district = models.CharField(max_length=100, blank=True, null=True)
    permanent_state = models.CharField(max_length=100, blank=True, null=True)
    permanent_pincode = models.CharField(max_length=10, blank=True, null=True)


    # Professional Information
    date_of_joining = models.DateField(blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True)
    employee_type = models.CharField(max_length=20, default='full_time')
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    pan_number = models.CharField(max_length=10, unique=True, blank=True, null=True)

    # Login & Security (Role and Status)
    staff_role = models.CharField(max_length=50, default='administrator', help_text="Specific role within non-teaching staff (e.g., Librarian, IT Support)")
    status = models.CharField(max_length=20,default='active')

    # Additional
    profile_picture = models.ImageField(upload_to='profile_pics/non_teaching_staff/', blank=True, null=True)
    assigned_responsibilities = models.TextField(blank=True, null=True)


    class Meta:
        verbose_name = "Non-Teaching Staff Profile"
        verbose_name_plural = "Non-Teaching Staff Profiles"

    def __str__(self):
        return f"Non-Teaching Staff: {self.user.username} ({self.employee_id})"
    
class ManagementProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='management_profile')
    employee_id = models.CharField(max_length=20, unique=True, help_text="Unique employee identifier for management staff")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='management_staff_in_departments', help_text="Optional: Department affiliation if applicable (e.g., Head of Finance Dept)")

    # Basic Information
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=10, blank=True, null=True)
    aadhaar_number = models.CharField(max_length=12, unique=True, blank=True, null=True, help_text="Unique Aadhaar across all users")
    emergency_contact_name = models.CharField(max_length=255, blank=True, null=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True, null=True)

    # Contact Information
    contact_number = models.CharField(max_length=15, blank=True, null=True)
    current_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    current_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    current_city = models.CharField(max_length=100, blank=True, null=True)
    current_district = models.CharField(max_length=100, blank=True, null=True)
    current_state = models.CharField(max_length=100, blank=True, null=True)
    current_pincode = models.CharField(max_length=10, blank=True, null=True)
    permanent_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    permanent_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    permanent_city = models.CharField(max_length=100, blank=True, null=True)
    permanent_district = models.CharField(max_length=100, blank=True, null=True)
    permanent_state = models.CharField(max_length=100, blank=True, null=True)
    permanent_pincode = models.CharField(max_length=10, blank=True, null=True)

    # Professional Information
    date_of_joining = models.DateField(blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True)
    employee_type = models.CharField(max_length=20,default='full_time')
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    pan_number = models.CharField(max_length=10, unique=True, blank=True, null=True, help_text="Unique PAN across all users")

    # Login & Security
    staff_role = models.CharField(max_length=50, default='director', help_text="Specific role within management staff (e.g., College Owner, T&P Officer)")
    status = models.CharField(max_length=20, default='active')

    # Additional
    profile_picture = models.ImageField(upload_to='profile_pics/management_staff/', blank=True, null=True)
    assigned_responsibilities = models.TextField(blank=True, null=True) # General field for any management tasks
    office_location_details = models.CharField(max_length=255, blank=True, null=True) # Specific office location info


    class Meta:
        verbose_name = "Management Profile"
        verbose_name_plural = "Management Profiles"

    def __str__(self):
        return f"Management: {self.user.username} ({self.employee_id})"


class AdministratorProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='administrator_profile')
    employee_id = models.CharField(max_length=20, unique=True, help_text="Unique employee identifier for administrators")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='administrators_in_departments', help_text="Optional: Department affiliation for specific admin roles")

    # --- Common Staff Information (Copy from ManagementProfile or TeachingStaffProfile) ---
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=10, blank=True, null=True)
    aadhaar_number = models.CharField(max_length=12, unique=True, blank=True, null=True)
    emergency_contact_name = models.CharField(max_length=255, blank=True, null=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True, null=True)

    contact_number = models.CharField(max_length=15, blank=True, null=True)
    current_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    current_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    current_city = models.CharField(max_length=100, blank=True, null=True)
    current_district = models.CharField(max_length=100, blank=True, null=True)
    current_state = models.CharField(max_length=100, blank=True, null=True)
    current_pincode = models.CharField(max_length=10, blank=True, null=True)
    permanent_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    permanent_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    permanent_city = models.CharField(max_length=100, blank=True, null=True)
    permanent_district = models.CharField(max_length=100, blank=True, null=True)
    permanent_state = models.CharField(max_length=100, blank=True, null=True)
    permanent_pincode = models.CharField(max_length=10, blank=True, null=True)

    date_of_joining = models.DateField(blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True, help_text="e.g., System Administrator, HR Administrator")
    employee_type = models.CharField(max_length=20, default='full_time')
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    pan_number = models.CharField(max_length=10, unique=True, blank=True, null=True)

    staff_role = models.CharField(max_length=50, default='system_admin', help_text="Specific administrative role")
    status = models.CharField(max_length=20, default='active')

    profile_picture = models.ImageField(upload_to='profile_pics/administrators/', blank=True, null=True)
    assigned_responsibilities = models.TextField(blank=True, null=True) # Specific admin tasks

    # --- Administrator specific fields (add any unique fields here) ---
    # For example:
    # security_clearance_level = models.CharField(max_length=50, blank=True, null=True)


    class Meta:
        verbose_name = "Administrator Profile"
        verbose_name_plural = "Administrator Profiles"

    def __str__(self):
        return f"Administrator: {self.user.username} ({self.employee_id})"


class DepartmentHeadProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='department_head_profile')
    employee_id = models.CharField(max_length=20, unique=True, help_text="Unique employee identifier for department heads")
    # For HOD, department is usually *mandatory* and points to the department they head
    department = models.OneToOneField(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='head_of_department', help_text="The department this person is head of.")

    # --- Common Staff Information (Copy from ManagementProfile or TeachingStaffProfile) ---
    middle_name = models.CharField(max_length=100, blank=True, null=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=10, blank=True, null=True)
    aadhaar_number = models.CharField(max_length=12, unique=True, blank=True, null=True)
    emergency_contact_name = models.CharField(max_length=255, blank=True, null=True)
    emergency_contact_relationship = models.CharField(max_length=50, blank=True, null=True)
    emergency_contact_phone = models.CharField(max_length=15, blank=True, null=True)

    contact_number = models.CharField(max_length=15, blank=True, null=True)
    current_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    current_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    current_city = models.CharField(max_length=100, blank=True, null=True)
    current_district = models.CharField(max_length=100, blank=True, null=True)
    current_state = models.CharField(max_length=100, blank=True, null=True)
    current_pincode = models.CharField(max_length=10, blank=True, null=True)
    permanent_address_line1 = models.CharField(max_length=255, blank=True, null=True)
    permanent_address_line2 = models.CharField(max_length=255, blank=True, null=True)
    permanent_city = models.CharField(max_length=100, blank=True, null=True)
    permanent_district = models.CharField(max_length=100, blank=True, null=True)
    permanent_state = models.CharField(max_length=100, blank=True, null=True)
    permanent_pincode = models.CharField(max_length=10, blank=True, null=True)

    date_of_joining = models.DateField(blank=True, null=True)
    designation = models.CharField(max_length=100, blank=True, null=True, default='Department Head')
    employee_type = models.CharField(max_length=20, default='full_time')
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    pan_number = models.CharField(max_length=10, unique=True, blank=True, null=True)

    staff_role = models.CharField(max_length=50, default='HOD', help_text="Specific role within the department head capacity")
    status = models.CharField(max_length=20, default='active')

    profile_picture = models.ImageField(upload_to='profile_pics/department_heads/', blank=True, null=True)
    # --- HOD specific fields (add any unique fields here) ---
    # e.g., A list of courses they oversee or policy documents
    # managed_courses = models.ManyToManyField(Course, blank=True)


    class Meta:
        verbose_name = "Department Head Profile"
        verbose_name_plural = "Department Head Profiles"

    def __str__(self):
        return f"Department Head: {self.user.username} ({self.employee_id})"

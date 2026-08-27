import uuid
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
    apaar_id = models.CharField(
        max_length=12, unique=True, blank=True, null=True,
        help_text="APAAR ID (Automated Permanent Academic Account Registry) — the student's ABC "
                   "(Academic Bank of Credits) account identifier. Blank until issued by the "
                   "government; nothing in this system generates one.",
    )
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

    # DPDP Compliance
    consent_given = models.BooleanField(default=False, help_text="True if privacy notice is accepted.")
    consent_timestamp = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=10, blank=True, null=True)
    parent_guardian_name = models.CharField(max_length=255, blank=True, null=True)
    parent_guardian_email = models.EmailField(blank=True, null=True)
    guardian_consent_given = models.BooleanField(default=False)

    # ── Structured academic placement ──
    # Parallel-run alongside the four free-text fields above, not a replacement
    # yet. All nullable so the auto-makemigrations on the production host stays
    # non-interactive. Nothing reads these until the backfill has run and been
    # verified; program_enrolled_in and friends remain authoritative meanwhile.
    # `department` is deliberately left untouched — it has too many readers, and
    # it becomes derivable from program.department later.
    program = models.ForeignKey(
        "campusflow_app.Program", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="students",
    )
    batch = models.ForeignKey(
        "campusflow_app.Batch", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="students",
    )
    section = models.ForeignKey(
        "campusflow_app.Section", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="students",
    )
    current_semester_number = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Curriculum position 1..N. Structured form of current_semester_year.",
    )
    regulation = models.ForeignKey(
        "campusflow_app.Regulation", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="students",
        help_text="Normally inherited from the batch. Set explicitly ONLY for a "
                  "regulation-transferred student who failed and re-joined under a newer scheme.",
    )
    academic_status = models.CharField(
        max_length=20, default="active",
        choices=[
            ("active", "Active"), ("detained", "Detained"), ("dropped", "Dropped"),
            ("graduated", "Graduated"), ("transferred", "Transferred"),
            ("on_break", "On Break (NEP exit)"),
        ],
        help_text="Academic standing. Distinct from `status`, which is account state.",
    )

    # Bus conductor ID-card scan — unique token embedded in the student's
    # printed/digital ID card QR. Regenerating invalidates old printed cards.
    qr_token = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
        help_text="Unique token for the student's ID card QR code. Regenerate to invalidate old printed cards.",
    )

    class Meta:
        verbose_name = "Student Profile"
        verbose_name_plural = "Student Profiles"

    def __str__(self):
        return f"Student: {self.user.username} ({self.student_id})"

    def regenerate_qr_token(self):
        """Call this to invalidate all existing printed ID-card QR codes for this student."""
        self.qr_token = uuid.uuid4()
        self.save(update_fields=["qr_token"])

    @property
    def effective_regulation(self):
        """
        The regulation to grade this student against: their own override if set,
        otherwise the one their batch was admitted under. Always resolve through
        here rather than reading `regulation` directly — the override exists only
        for students who failed and re-joined under a newer scheme, so the batch
        is the answer for almost everyone.
        """
        if self.regulation_id:
            return self.regulation
        return self.batch.regulation if self.batch_id else None

    # Fields whose value is entirely computed from the FKs above during save()
    # — see _sync_legacy_academic_fields. Named once here so save()'s
    # update_fields widening and the backfill command's report agree on exactly
    # what "the legacy mirror" means.
    LEGACY_ACADEMIC_MIRROR = (
        "program_enrolled_in", "batch_academic_year",
        "current_semester_year", "section_division",
    )

    def _sync_legacy_academic_fields(self, update_fields):
        """
        Parallel-run bridge, FK -> string only. Keeps every existing reader of
        the four legacy CharFields (FeeStructure string matching, the bus
        conductor's "class" label, the guardian report-card grouping) working
        unchanged while the FKs become authoritative underneath them. The
        reverse direction, string -> FK, is never inferred here — that is the
        backfill_student_academics management command's job, run explicitly
        and reviewed, never a side effect of an unrelated save().

        A mirrored field is only re-derived when its FK source was actually
        part of THIS save — update_fields is None (a full save) or the FK's
        own name is listed in update_fields. Without that restriction,
        views/promotion.py's existing pattern breaks: it sets
        current_semester_year/section_division/batch_academic_year directly
        and saves with update_fields=[exactly those three] WITHOUT touching
        current_semester_number/batch/section at all, since promotion does not
        yet operate on the FKs (that lands with promotion's own PR). Deriving
        those strings unconditionally from the student's stale, unrelated FK
        values would silently revert promotion's own write back to the
        pre-promotion semester on the very next save.

        Returns the set of legacy field names actually recomputed, so save()
        can widen its update_fields by exactly those and nothing else.
        """
        sync_all = update_fields is None
        touched = set()

        if self.batch_id and (sync_all or "batch" in update_fields):
            batch = self.batch
            if batch.program_id:
                label = batch.program.short_name or batch.program.code
                self.program_enrolled_in = label[:50]
                touched.add("program_enrolled_in")
            self.batch_academic_year = batch.name[:50]
            touched.add("batch_academic_year")

        if self.current_semester_number and (sync_all or "current_semester_number" in update_fields):
            self.current_semester_year = f"Semester {self.current_semester_number}"[:50]
            touched.add("current_semester_year")

        if self.section_id and (sync_all or "section" in update_fields):
            self.section_division = self.section.name[:10]
            touched.add("section_division")

        return touched

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        touched_mirror_fields = self._sync_legacy_academic_fields(update_fields)
        if update_fields is not None and touched_mirror_fields:
            # Widen by exactly what was recomputed above — not the full mirror
            # set — so a save that never touched a given FK never rewrites that
            # FK's mirrored string either.
            kwargs["update_fields"] = list(set(update_fields) | touched_mirror_fields)
        super().save(*args, **kwargs)

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
    has_phd = models.BooleanField(
        default=False,
        help_text="Structured flag for the NIRF TLR 'faculty with PhD' metric — qualifications above is free text and isn't reliably queryable.",
    )
    specializations = models.TextField(blank=True, null=True, help_text="Subjects taught or areas of specialization")
    experience_years = models.PositiveIntegerField(blank=True, null=True)
    employee_type = models.CharField(max_length=20, default='full_time')
    bank_account_number = models.CharField(max_length=50, blank=True, null=True)
    pan_number = models.CharField(max_length=10, unique=True, blank=True, null=True)
    epf_esi_details = models.TextField(blank=True, null=True)

    # AICTE Extension of Approval — Faculty ID (linked to PAN/Aadhaar above in the
    # actual AICTE filing) and cadre category, needed for the cadre-wise ratio
    # AICTE audits (Professor:Associate:Assistant), not just a flat headcount ratio.
    CADRE_PROFESSOR = 'professor'
    CADRE_ASSOCIATE_PROFESSOR = 'associate_professor'
    CADRE_ASSISTANT_PROFESSOR = 'assistant_professor'
    CADRE_CHOICES = [
        (CADRE_PROFESSOR, 'Professor'),
        (CADRE_ASSOCIATE_PROFESSOR, 'Associate Professor'),
        (CADRE_ASSISTANT_PROFESSOR, 'Assistant Professor'),
    ]
    aicte_faculty_id = models.CharField(
        max_length=50, unique=True, blank=True, null=True,
        help_text="AICTE-issued Faculty ID, for the annual Extension of Approval filing.",
    )
    aicte_cadre = models.CharField(
        max_length=25, choices=CADRE_CHOICES, blank=True, null=True,
        help_text="AICTE cadre category, distinct from the free-text designation above — powers the cadre-wise ratio computation.",
    )

    # Login & Security (Role and Status)
    staff_role = models.CharField(max_length=50, default='lecturer', help_text="Specific role within teaching staff (e.g., Professor, HOD)")
    status = models.CharField(max_length=20, default='active')

    # Additional
    profile_picture = models.ImageField(upload_to='profile_pics/teaching_staff/', blank=True, null=True)
    office_room_number = models.CharField(max_length=20, blank=True, null=True)
    research_interests = models.TextField(blank=True, null=True)
    publications_link = models.URLField(max_length=500, blank=True, null=True)
    replacement_availability_preferences = models.TextField(blank=True, null=True, help_text="e.g., Available for substitutes on Tuesdays after 2 PM")
    max_weekly_teaching_hours = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text="Optional cap used by timetable generation to avoid overloading this faculty member; unset = no limit.",
    )

    # DPDP Compliance
    consent_given = models.BooleanField(default=False, help_text="True if privacy notice is accepted.")
    consent_timestamp = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=10, blank=True, null=True)

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

    # DPDP Compliance
    consent_given = models.BooleanField(default=False, help_text="True if privacy notice is accepted.")
    consent_timestamp = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=10, blank=True, null=True)

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

    # DPDP Compliance
    consent_given = models.BooleanField(default=False, help_text="True if privacy notice is accepted.")
    consent_timestamp = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=10, blank=True, null=True)

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

    # DPDP Compliance
    consent_given = models.BooleanField(default=False, help_text="True if privacy notice is accepted.")
    consent_timestamp = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=10, blank=True, null=True)

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

    # DPDP Compliance
    consent_given = models.BooleanField(default=False, help_text="True if privacy notice is accepted.")
    consent_timestamp = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=10, blank=True, null=True)

    class Meta:
        verbose_name = "Department Head Profile"
        verbose_name_plural = "Department Head Profiles"

    def __str__(self):
        return f"Department Head: {self.user.username} ({self.employee_id})"


class GuardianProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='guardian_profile')
    guardian_id = models.CharField(max_length=20, unique=True, help_text="Unique guardian identifier")
    students = models.ManyToManyField(StudentProfile, related_name='guardians', help_text="Linked children")
    contact_number = models.CharField(max_length=15, blank=True, null=True)
    alternate_phone_number = models.CharField(max_length=15, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, default='active')

    # DPDP Compliance
    consent_given = models.BooleanField(default=False, help_text="True if privacy notice is accepted.")
    consent_timestamp = models.DateTimeField(null=True, blank=True)
    consent_version = models.CharField(max_length=10, blank=True, null=True)

    class Meta:
        verbose_name = "Guardian Profile"
        verbose_name_plural = "Guardian Profiles"

    def __str__(self):
        return f"Guardian: {self.user.username} ({self.guardian_id})"

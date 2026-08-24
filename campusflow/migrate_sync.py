import os
import shutil
import sys


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        # Fallback for Windows legacy terminal codepages (cp1252)
        print(msg.encode("ascii", errors="ignore").decode("ascii"))


# Explicit whitelist of clean, canonical migration files tracked in version control.
# Any python file in migrations folders not matching this set is an un-reconciled
# stray from legacy branches and will be automatically purged on container start.
CANONICAL_MIGRATIONS = {
    "tenants": {
        "__init__.py",
        "0001_initial.py",
        "0002_tenant_permitted_email_domain.py",
        "0003_tenant_email_smtp_host_tenant_email_smtp_password_and_more.py",
        "0004_tenant_billing_employee_discount_and_more.py",
        "0005_tenant_timezone.py",
        "0006_tenant_subscribed_modules.py",
        "0007_alter_tenant_subscribed_modules.py",
        "0008_tenant_logo.py",
        "0009_tenant_cashfree_app_id_tenant_cashfree_secret_key_and_more.py",
        "0010_tenant_mobikwik_merchant_id_and_more.py",
        "0011_tenant_convenience_fee_percent_and_more.py",
        "0012_tenant_billing_cycle_tenant_subscription_end_date_and_more.py",
        "0013_tenant_is_demo.py",
        "0014_alter_invoice_bank_receipt.py",
        "0015_tenant_tenant_type.py",
    },
    "campusflow_app": {
        "__init__.py",
        "0001_initial.py",
        "0002_alter_attendance_unique_together_and_more.py",
        "0003_examtype_leavetype_announcement_auditlog_exam_and_more.py",
        "0004_assignment_assignmentsubmission.py",
        "0005_manualattendancerequest.py",
        "0006_feecategory_tenantmodulepermission_busroute_and_more.py",
        "0007_book_hostel_inventorycategory_recruitmentdrive_and_more.py",
        "0008_busroute_conductor.py",
        "0009_alter_attendance_check_in_time.py",
        "0010_scannedpaper_mask_code_scannedpaper_question_scores.py",
        "0011_exam_question_paper_url_exam_question_structure.py",
        "0012_alter_feepayment_payment_method_and_more.py",
        "0013_administratorprofile_consent_given_and_more.py",
        "0013_guardianprofile.py",
        "0014_bus_trip.py",
        "0014_bustrip_boarded_count_bustrip_expected_count_and_more.py",
        "0015_attendance_is_half_day_attendancecorrectionrequest.py",
        "0015_faceembedding_sample_count_faceembedding_updated_at_and_more.py",
        "0016_announcement_notify_parents_and_more.py",
        "0016_compliancecertificatetype_compliancecertificate.py",
        "0017_exam_results_published_exam_results_published_at_and_more.py",
        "0018_studentconsent.py",
        "0019_promotionbatch_promotionrecord.py",
        "0020_parentlinkrequest.py",
        "0021_exam_paper_finalized_exam_paper_finalized_at_and_more.py",
        "0022_academicyear_term_exam_term_schedule_term_and_more.py",
        "0023_batch_section_course_canonical_code_and_more.py",
        "0024_studentfeeinvoice_uniq_invoice_per_student_per_structure.py",
        "0025_courseoffering_studentacademicsummary_and_more.py",
        "0026_courseoutcome_examquestion_course_outcome_and_more.py",
        "0027_expensecategory_incomecategory_and_more.py",
        "0028_classroom_capacity_exam_answer_key_and_more.py",
        "0029_placementapplication_offered_ctc_lpa_and_more.py",
        "0030_statutorycommittee_committeemembership_and_more.py",
        "0031_scannedpaper_scanned_file_and_more.py",
        "0032_studentinsightsnapshot.py",
        "0033_question_ai_generated_papersetvariant.py",
        "0034_syllabuscoverageentry.py",
        "0035_alter_auditlog_action.py",
    },
}


def purge_non_canonical_migrations():
    for app_name, valid_set in CANONICAL_MIGRATIONS.items():
        dirs_to_check = [
            f"/app/{app_name}/migrations",
            f"/tmp/clean_migrations/{app_name}/migrations",
            "/tmp/clean_migrations",
        ]
        for target_dir in dirs_to_check:
            if not os.path.exists(target_dir):
                continue
            for filename in os.listdir(target_dir):
                if filename == "__pycache__":
                    continue
                if filename.endswith(".py") and filename not in valid_set:
                    file_path = os.path.join(target_dir, filename)
                    try:
                        os.remove(file_path)
                        _print(
                            f"   🧹 Purged obsolete non-canonical migration file: "
                            f"{app_name}/{filename}"
                        )
                    except Exception as e:
                        _print(f"   ⚠️ Failed to purge {filename}: {e}")


def sync_directory(clean_dir, target_dir, app_name):
    if not os.path.exists(clean_dir):
        return

    valid_set = CANONICAL_MIGRATIONS.get(app_name, set())

    clean_files = {f for f in os.listdir(clean_dir) if f in valid_set}

    if os.path.exists(target_dir):
        for filename in os.listdir(target_dir):
            if filename == "__pycache__":
                continue
            if filename not in clean_files:
                file_path = os.path.join(target_dir, filename)
                try:
                    if os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                    else:
                        os.remove(file_path)
                    _print(f"   🧹 Removed stray file/folder in {app_name}: {filename}")
                except Exception as e:
                    _print(f"   ⚠️ Failed to remove {filename}: {e}")

    for filename in clean_files:
        target_path = os.path.join(target_dir, filename)
        clean_path = os.path.join(clean_dir, filename)
        if not os.path.exists(target_path):
            try:
                if os.path.isdir(clean_path):
                    shutil.copytree(clean_path, target_path)
                else:
                    shutil.copy2(clean_path, target_path)
                _print(f"   📥 Restored missing migration file in {app_name}: {filename}")
            except Exception as e:
                _print(f"   ⚠️ Failed to restore {filename}: {e}")


def sync_migrations():
    purge_non_canonical_migrations()

    base_clean_dir = "/tmp/clean_migrations"

    if not os.path.exists(base_clean_dir):
        _print(
            "ℹ️ No clean migrations backup found "
            "(running in local dev without docker build). Skipping sync."
        )
        return

    _print("🔄 Syncing migration files with repository version...")

    # Legacy fallback check (if clean_migrations contains files directly)
    if os.path.exists(os.path.join(base_clean_dir, "__init__.py")) or any(
        f.endswith(".py")
        for f in os.listdir(base_clean_dir)
        if os.path.isfile(os.path.join(base_clean_dir, f))
    ):
        sync_directory(base_clean_dir, "/app/campusflow_app/migrations", "campusflow_app")
        _print("✅ Migration files synced successfully.")
        return

    # Structured multi-app sync
    apps = ["campusflow_app", "tenants"]
    for app in apps:
        clean_app_dir = os.path.join(base_clean_dir, app, "migrations")
        target_app_dir = os.path.join("/app", app, "migrations")
        sync_directory(clean_app_dir, target_app_dir, app)

    _print("✅ Migration files synced successfully.")


if __name__ == "__main__":
    sync_migrations()





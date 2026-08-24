import os
import shutil
import sys


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        # Fallback for Windows legacy terminal codepages (cp1252)
        print(msg.encode("ascii", errors="ignore").decode("ascii"))


# Known stray/obsolete migration files created from legacy merged branches
KNOWN_STRAY_FILES = {
    "tenants": [
        "0010_tenant_cashfree_app_id_tenant_cashfree_secret_key_and_more.py",
        "0009_tenant_billing_cycle_tenant_subscription_end_date_and_more.py",
    ]
}


def purge_known_strays():
    for app_name, filenames in KNOWN_STRAY_FILES.items():
        target_dir = f"/app/{app_name}/migrations"
        if os.path.exists(target_dir):
            for filename in filenames:
                file_path = os.path.join(target_dir, filename)
                if os.path.exists(file_path):
                    try:
                        os.remove(file_path)
                        _print(f"   🧹 Purged obsolete stray migration file: {app_name}/{filename}")
                    except Exception as e:
                        _print(f"   ⚠️ Failed to purge {filename}: {e}")


def sync_directory(clean_dir, target_dir, app_name):
    if not os.path.exists(clean_dir):
        return

    stray_names = set(KNOWN_STRAY_FILES.get(app_name, []))

    # Remove known strays from clean backup directory if present
    for stray in stray_names:
        clean_stray_path = os.path.join(clean_dir, stray)
        if os.path.exists(clean_stray_path):
            try:
                os.remove(clean_stray_path)
            except Exception:
                pass

    clean_files = set(os.listdir(clean_dir)) - stray_names

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

    purge_known_strays()

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




import os
import shutil
import sys


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        # Fallback for Windows legacy terminal codepages (cp1252)
        print(msg.encode("ascii", errors="ignore").decode("ascii"))


def sync_directory(clean_dir, target_dir, app_name):
    if not os.path.exists(clean_dir):
        return

    clean_files = set(os.listdir(clean_dir))

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



import os
import shutil

def sync_migrations():
    clean_dir = '/tmp/clean_migrations'
    target_dir = '/app/campusflow_app/migrations'

    if not os.path.exists(clean_dir):
        print("ℹ️ No clean migrations backup found (running in local dev without docker build). Skipping sync.")
        return

    print("🔄 Syncing migration files with repository version...")

    # Get list of clean files in the built docker image
    clean_files = set(os.listdir(clean_dir))

    # Delete any stray files in the mounted target directory
    for filename in os.listdir(target_dir):
        if filename == '__pycache__':
            continue
        if filename not in clean_files:
            file_path = os.path.join(target_dir, filename)
            try:
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.remove(file_path)
                print(f"   🧹 Removed stray file/folder: {filename}")
            except Exception as e:
                print(f"   ⚠️ Failed to remove {filename}: {e}")

    # Copy missing clean files back to the mounted target directory
    for filename in clean_files:
        target_path = os.path.join(target_dir, filename)
        clean_path = os.path.join(clean_dir, filename)
        if not os.path.exists(target_path):
            try:
                if os.path.isdir(clean_path):
                    shutil.copytree(clean_path, target_path)
                else:
                    shutil.copy2(clean_path, target_path)
                print(f"   📥 Restored missing migration file: {filename}")
            except Exception as e:
                print(f"   ⚠️ Failed to restore {filename}: {e}")

    print("✅ Migration files synced successfully.")

if __name__ == '__main__':
    sync_migrations()

import ast
import os
import shutil
import subprocess
import sys


def _print(msg):
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("ascii", errors="ignore").decode("ascii"))


def is_git_tracked(file_path):
    """Check if a file is tracked in git version control."""
    try:
        res = subprocess.run(
            ["git", "ls-files", "--error-unmatch", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=os.path.dirname(os.path.abspath(file_path)) or None,
        )
        return res.returncode == 0
    except Exception:
        return True  # Fallback if git binary is missing in runtime container


def parse_migration_file_info(file_path):
    """
    Parse dependencies and AddField operations from a Django migration file AST
    without executing or importing Django models.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            tree = ast.parse(f.read(), filename=file_path)

        dependencies = []
        add_fields = []

        for node in tree.body:
            if isinstance(node, ast.ClassDef) and node.name == "Migration":
                for item in node.body:
                    if isinstance(item, ast.Assign):
                        for target in item.targets:
                            if isinstance(target, ast.Name):
                                # Extract dependencies list
                                if target.id == "dependencies" and isinstance(
                                    item.value, ast.List
                                ):
                                    for elt in item.value.elts:
                                        if (
                                            isinstance(elt, ast.Tuple)
                                            and len(elt.elts) == 2
                                        ):
                                            app = getattr(
                                                elt.elts[0],
                                                "s",
                                                getattr(elt.elts[0], "value", None),
                                            )
                                            mig = getattr(
                                                elt.elts[1],
                                                "s",
                                                getattr(elt.elts[1], "value", None),
                                            )
                                            if app and mig:
                                                dependencies.append((app, mig))

                                # Extract operations to find AddField operations
                                if target.id == "operations" and isinstance(
                                    item.value, ast.List
                                ):
                                    for op in item.value.elts:
                                        if (
                                            isinstance(op, ast.Call)
                                            and isinstance(op.func, ast.Attribute)
                                            and op.func.attr == "AddField"
                                        ):
                                            model_name = None
                                            field_name = None
                                            for kw in op.keywords:
                                                if kw.arg == "model_name":
                                                    model_name = getattr(
                                                        kw.value,
                                                        "s",
                                                        getattr(kw.value, "value", None),
                                                    )
                                                elif kw.arg == "name":
                                                    field_name = getattr(
                                                        kw.value,
                                                        "s",
                                                        getattr(kw.value, "value", None),
                                                    )
                                            if model_name and field_name:
                                                add_fields.append(
                                                    (model_name.lower(), field_name)
                                                )
        return dependencies, add_fields
    except Exception:
        return [], []


def prune_invalid_or_clashing_migrations(app_dirs):
    """
    Dynamically inspects migration directories and prunes:
    1. Numeric prefix clashes (e.g. two files starting with '0010_'), preferring git-tracked files.
    2. Orphaned migration files whose dependencies point to non-existent parent nodes.
    """
    for app_name, mig_dir in app_dirs.items():
        if not os.path.exists(mig_dir):
            continue

        files = [
            f for f in os.listdir(mig_dir) if f.endswith(".py") and f != "__init__.py"
        ]

        # Group by numeric prefix (e.g., '0009', '0010')
        by_prefix = {}
        for filename in files:
            prefix = filename.split("_")[0]
            by_prefix.setdefault(prefix, []).append(filename)

        # 1. Resolve duplicate prefix clashes
        for prefix, file_list in by_prefix.items():
            if len(file_list) > 1:
                _print(
                    f"⚠️ Migration prefix clash in '{app_name}' for '{prefix}': {file_list}"
                )
                tracked = [
                    f
                    for f in file_list
                    if is_git_tracked(os.path.join(mig_dir, f))
                ]
                untracked = [
                    f
                    for f in file_list
                    if not is_git_tracked(os.path.join(mig_dir, f))
                ]

                # If tracked files exist, purge untracked clashes
                to_delete = untracked if tracked else file_list[1:]
                for filename in to_delete:
                    file_path = os.path.join(mig_dir, filename)
                    try:
                        os.remove(file_path)
                        _print(f"   🧹 Pruned clashing migration file: {app_name}/{filename}")
                    except Exception as e:
                        _print(f"   ⚠️ Failed to remove {filename}: {e}")

        # Re-scan remaining files after prefix clash cleanup
        remaining_files = set(
            f for f in os.listdir(mig_dir) if f.endswith(".py") and f != "__init__.py"
        )
        existing_stems = {f[:-3] for f in remaining_files}

        # 2. Resolve orphaned dependencies (parent node missing)
        for filename in list(remaining_files):
            file_path = os.path.join(mig_dir, filename)
            deps, _ = parse_migration_file_info(file_path)

            for dep_app, dep_mig in deps:
                if dep_app == app_name and dep_mig != "__first__":
                    if dep_mig not in existing_stems:
                        _print(
                            f"⚠️ Orphaned dependency in {app_name}/{filename}: "
                            f"parent '{dep_mig}' does not exist!"
                        )
                        try:
                            os.remove(file_path)
                            _print(
                                f"   🧹 Pruned orphaned migration file: {app_name}/{filename}"
                            )
                            break
                        except Exception as e:
                            _print(f"   ⚠️ Failed to remove {filename}: {e}")


def reconcile_database_columns_and_migrations(app_dirs):
    """
    Connects to PostgreSQL and inspects target tables.
    If a migration attempts to AddField for a column that ALREADY exists in PostgreSQL,
    marks the migration as applied in django_migrations table so Django skips re-adding it.
    """
    host = os.environ.get("POSTGRES_HOST", "db")
    port = os.environ.get("POSTGRES_PORT", "5432")
    user = os.environ.get("POSTGRES_USER", "postgres")
    password = os.environ.get("POSTGRES_PASSWORD", "postgres")
    dbname = os.environ.get("POSTGRES_DB", "campusflow")

    try:
        import psycopg2

        conn = psycopg2.connect(
            host=host, port=port, user=user, password=password, dbname=dbname
        )
        conn.autocommit = True
        cur = conn.cursor()

        # Ensure django_migrations table exists
        cur.execute(
            "SELECT EXISTS ("
            "SELECT FROM information_schema.tables WHERE table_name = 'django_migrations'"
            ");"
        )
        if not cur.fetchone()[0]:
            conn.close()
            return

        for app_name, mig_dir in app_dirs.items():
            if not os.path.exists(mig_dir):
                continue

            # Fetch applied migrations in DB
            cur.execute(
                "SELECT name FROM django_migrations WHERE app = %s;",
                (app_name,),
            )
            applied_in_db = {row[0] for row in cur.fetchall()}

            # Clean obsolete database records for migration files that no longer exist on disk
            existing_stems = {
                f[:-3]
                for f in os.listdir(mig_dir)
                if f.endswith(".py") and f != "__init__.py"
            }
            for db_mig_name in list(applied_in_db):
                if db_mig_name != "__first__" and db_mig_name not in existing_stems:
                    cur.execute(
                        "DELETE FROM django_migrations WHERE app = %s AND name = %s;",
                        (app_name, db_mig_name),
                    )
                    _print(
                        f"   🧹 Cleaned obsolete migration record from DB: "
                        f"{app_name}/{db_mig_name}"
                    )
                    applied_in_db.remove(db_mig_name)

            # Inspect unapplied migration files in chronological order
            unapplied_files = sorted([
                f
                for f in os.listdir(mig_dir)
                if f.endswith(".py")
                and f != "__init__.py"
                and f[:-3] not in applied_in_db
            ])

            for filename in unapplied_files:
                stem = filename[:-3]
                file_path = os.path.join(mig_dir, filename)
                _, add_fields = parse_migration_file_info(file_path)

                if not add_fields:
                    continue

                # Check if all columns added by this migration already exist in DB relation
                all_fields_exist = True
                for model_name, field_name in add_fields:
                    table_name = (
                        f"{app_name}_{model_name}"
                        if not model_name.startswith(app_name)
                        else model_name
                    )
                    cur.execute(
                        "SELECT EXISTS ("
                        "SELECT FROM information_schema.columns "
                        "WHERE table_name = %s AND column_name = %s"
                        ");",
                        (table_name, field_name),
                    )
                    col_exists = cur.fetchone()[0]
                    if not col_exists:
                        all_fields_exist = False
                        break

                if all_fields_exist:
                    cur.execute(
                        "INSERT INTO django_migrations (app, name, applied) "
                        "VALUES (%s, %s, NOW());",
                        (app_name, stem),
                    )
                    _print(
                        f"   ⏩ Columns already exist in DB table. "
                        f"Skipped duplicate creation & marked migration applied: "
                        f"{app_name}/{stem}"
                    )

        conn.close()
    except Exception as e:
        _print(f"   ℹ️ Database migration check skipped or deferred: {e}")


def sync_directory(clean_dir, target_dir, app_name):
    if not os.path.exists(clean_dir):
        return

    if os.path.exists(target_dir):
        clean_files = set(os.listdir(clean_dir))
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

    for filename in os.listdir(clean_dir):
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
    app_dirs = {
        "tenants": "/app/tenants/migrations",
        "campusflow_app": "/app/campusflow_app/migrations",
    }

    # 1. Dynamically prune filesystem clashes & broken dependency nodes
    prune_invalid_or_clashing_migrations(app_dirs)

    # 2. Dynamically check DB columns & skip existing fields
    reconcile_database_columns_and_migrations(app_dirs)

    base_clean_dir = "/tmp/clean_migrations"
    if not os.path.exists(base_clean_dir):
        _print(
            "ℹ️ No clean migrations backup found "
            "(running in local dev without docker build). Skipping sync."
        )
        return

    _print("🔄 Syncing migration files with repository version...")

    # Legacy single-app fallback check
    if os.path.exists(os.path.join(base_clean_dir, "__init__.py")) or any(
        f.endswith(".py")
        for f in os.listdir(base_clean_dir)
        if os.path.isfile(os.path.join(base_clean_dir, f))
    ):
        sync_directory(
            base_clean_dir, "/app/campusflow_app/migrations", "campusflow_app"
        )
        _print("✅ Migration files synced successfully.")
        return

    # Multi-app sync from build backup
    for app_name, target_dir in app_dirs.items():
        clean_app_dir = os.path.join(base_clean_dir, app_name, "migrations")
        sync_directory(clean_app_dir, target_dir, app_name)

    _print("✅ Migration files synced successfully.")


if __name__ == "__main__":
    sync_migrations()







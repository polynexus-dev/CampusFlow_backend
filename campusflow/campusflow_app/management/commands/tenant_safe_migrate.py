from django.core.management.commands.migrate import Command as BaseMigrateCommand
from django.db import DEFAULT_DB_ALIAS, connections
from django.db.migrations.executor import MigrationExecutor
from django.db.migrations.operations.special import RunPython, RunSQL


def _is_safe_for_soft_apply(migration):
    """
    Eligible unless the migration contains RunPython/RunSQL -- the two
    operation types that run arbitrary code/data mutations rather than a
    pure schema-shape change. Skipping those via soft-apply could silently
    drop a data backfill (see 0014_bustrip_boarded_count..., which mixes
    AddField with a RunPython backfill + a uniqueness AlterField that
    depends on it having run).

    Everything else Django ships (CreateModel, AddField, AlterField,
    RemoveField, DeleteModel, AddIndex, ...) is a pure schema-shape change:
    detect_soft_applied() below only actually *verifies* the CreateModel/
    AddField ones against live DB introspection (real column names, FK
    `_id` suffixes, M2M through-tables, etc.); any other op type in the
    same migration is simply not checked either way, so a migration that's
    NOT soft-applied still runs those for real exactly as it would without
    this broadening -- e.g. 0012_alter_feepayment_payment_method_and_more
    mixes CreateModel/AddField with a harmless AlterField, and must be
    eligible here or it goes straight to a real CREATE TABLE and collides
    with the table that already exists.
    """
    return bool(migration.operations) and not any(
        isinstance(op, (RunPython, RunSQL)) for op in migration.operations
    )


def _broaden_soft_apply(executor):
    """
    Django's --fake-initial soft-apply detection (find that a migration's
    tables/columns already exist and mark it applied instead of re-running
    it) normally only ever runs for each app's very *first* migration. This
    extends that detection to any LATER migration made entirely of
    CreateModel/AddField ops, so a migration whose tables/columns already
    exist in a schema (e.g. because it was renamed/renumbered after already
    being applied there under an old name) gets correctly fake-applied
    instead of crashing on "already exists".
    """
    for migration in executor.loader.graph.nodes.values():
        if (
            migration is not None
            and migration.initial is None
            and _is_safe_for_soft_apply(migration)
        ):
            migration.initial = True


def _find_dependency_holes(executor, app_label=None):
    """
    A "hole" is a migration that is NOT recorded applied in this schema even
    though something that depends on it IS recorded applied -- the only way
    that can happen is a prior out-of-band write to django_migrations (see
    git history of migrate_sync.py for how that used to happen here), since
    the normal apply path can never produce it: it always walks the graph in
    dependency order, applying (or soft-applying) a migration's parents
    before the migration itself.

    Deliberately narrower than "every unapplied migration": a fresh app/
    tenant with nothing applied yet has plenty of unapplied migrations that
    are perfectly normal and must NOT be touched here -- they're just what
    the upcoming, ordinary migrate call is about to apply anyway. Only a
    node with an already-applied child is actually a broken invariant.
    """
    applied = set(executor.loader.applied_migrations)
    holes = [
        key
        for key in executor.loader.graph.nodes
        if key not in applied
        and (app_label is None or key[0] == app_label)
        and any(child in applied for child in executor.loader.graph.node_map[key].children)
    ]
    return sorted(holes)


class Command(BaseMigrateCommand):
    """
    Drop-in replacement for Django's `migrate`, wired in for every
    django-tenants schema via TENANT_BASE_MIGRATE_COMMAND (settings.py).

    Runs one extra step before the normal migrate: if this schema has a
    migration recorded applied while one of its dependencies isn't (only
    possible from a prior out-of-band write to django_migrations), it
    targets just that missing dependency with a real migrate call --
    applying it for real, or fake-applying it via the broadened soft-apply
    detection below if its tables/columns already exist -- so the normal
    migrate that follows sees a consistent history instead of crashing on
    InconsistentMigrationHistory. A schema with no such drift (the normal
    case, always, for a fresh boot) takes this branch as a no-op.
    """

    def handle(self, *args, **options):
        original_init = MigrationExecutor.__init__

        def patched_init(executor_self, connection, progress_callback=None):
            original_init(executor_self, connection, progress_callback)
            _broaden_soft_apply(executor_self)

        MigrationExecutor.__init__ = patched_init
        try:
            # self.verbosity is normally set by the base handle() itself,
            # but _heal_dependency_holes() (which uses it via the shared
            # migration_progress_callback) runs before that -- set it here
            # too so a real apply during healing can report progress.
            self.verbosity = options["verbosity"]
            self._heal_dependency_holes(options)
            return super().handle(*args, **options)
        finally:
            MigrationExecutor.__init__ = original_init

    def _heal_dependency_holes(self, options):
        connection = connections[options.get("database") or DEFAULT_DB_ALIAS]
        executor = MigrationExecutor(connection, self.migration_progress_callback)
        holes = _find_dependency_holes(executor, options.get("app_label"))
        if not holes:
            return

        if self.verbosity >= 1:
            self.stdout.write(
                self.style.WARNING(
                    "  Found migration(s) recorded applied ahead of their "
                    "dependencies in this schema -- self-healing before the "
                    "normal migrate runs: "
                    + ", ".join(f"{app}.{name}" for app, name in holes)
                )
            )
        executor.migrate(holes, fake=False, fake_initial=True)

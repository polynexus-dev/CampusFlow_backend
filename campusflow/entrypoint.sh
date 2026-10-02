#!/bin/bash
set -e

echo "⏳ Waiting for PostgreSQL to be ready..."
while ! pg_isready -h db -U postgres > /dev/null 2>&1; do
    echo "   PostgreSQL is not ready yet — retrying in 2s..."
    sleep 2
done
echo "✅ PostgreSQL is ready!"

# -1. docker-compose.yml mounts the repo as a live volume, so requirements.txt
#     changes show up immediately on restart, but the installed packages
#     baked into the image at build time don't — reinstall here so a plain
#     restart (not a rebuild) can't end up running against stale deps.
echo "📦 Syncing installed packages with requirements.txt..."
pip install -r requirements.txt

# 0. Migration files are committed to git. migrate_sync.py rewrites/deletes
#    migration files and is only for recovering a drifted dev database, so it
#    no longer runs on every boot — set RUN_MIGRATION_SYNC=1 to run it once.
if [ "${RUN_MIGRATION_SYNC:-0}" = "1" ]; then
    echo "🔄 Running migration file reconciliation (RUN_MIGRATION_SYNC=1)..."
    python migrate_sync.py
fi

# 0.5. Never generate migrations on the server: a model change without a
#      committed migration is a bug, so stop here instead of inventing one.
echo "🔄 Checking that every model change has a committed migration..."
if ! python manage.py makemigrations --check --dry-run; then
    echo "❌ Model changes without a committed migration. Run makemigrations locally, commit, and redeploy."
    exit 1
fi

# 0.9. Create any schema migrate_schemas expects but Postgres doesn't have
#      (public, or a tenant whose schema was dropped / not restored), which
#      would otherwise fail with "no schema has been selected to create in".
echo "🔄 Ensuring every tenant schema exists..."
python manage.py ensure_schemas

# 1. Run shared (public) schema migrations
echo "🔄 Running shared schema migrations..."
python manage.py migrate_schemas --shared --fake-initial

# 2. Run tenant schema migrations (for any existing tenants)
echo "🔄 Running tenant schema migrations..."
python manage.py migrate_schemas --fake-initial


# 3. Create the public tenant and domain if they don't exist yet
echo "🔄 Ensuring public tenant exists..."
python manage.py shell -c "
from tenants.models import Tenant, Domain
if not Tenant.objects.filter(schema_name='public').exists():
    t = Tenant(schema_name='public', name='Public Tenant', code='public')
    t.save()
    Domain.objects.create(domain='localhost', tenant=t, is_primary=True)
    print('   ✅ Public tenant + localhost domain created.')
else:
    print('   ✅ Public tenant already exists.')
"

# 4. Create the SaaS superuser in the public schema, only from env vars.
#    (This used to create admin/admin on every fresh database.)
if [ -n "${DJANGO_SUPERUSER_USERNAME:-}" ] && [ -n "${DJANGO_SUPERUSER_PASSWORD:-}" ]; then
    echo "🔄 Ensuring public superuser ${DJANGO_SUPERUSER_USERNAME} exists..."
    python manage.py shell -c "
import os
from django_tenants.utils import schema_context
from django.contrib.auth.models import User
with schema_context('public'):
    username = os.environ['DJANGO_SUPERUSER_USERNAME']
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username, os.environ.get('DJANGO_SUPERUSER_EMAIL', ''), os.environ['DJANGO_SUPERUSER_PASSWORD'])
        print('   ✅ Superuser created.')
    else:
        print('   ✅ Superuser already exists.')
"
else
    echo "ℹ️  DJANGO_SUPERUSER_USERNAME/PASSWORD not set — skipping superuser creation."
fi

# 4.5. Demo tenant (~2,400 fake students) only where explicitly wanted,
#      e.g. the public sales-demo server. Set SEED_DEMO_DATA=1 there.
if [ "${SEED_DEMO_DATA:-0}" = "1" ]; then
    echo "🔄 Ensuring demo tenant data is seeded (SEED_DEMO_DATA=1)..."
    python seed_demo_data.py
fi

# 5. Collect static files for the admin panel / DRF browsable API
echo "🔄 Collecting static files..."
python manage.py collectstatic --noinput

# 6. Start the server
# uvicorn (ASGI) instead of `runserver` — runserver is single-process/dev-only
# and can't handle concurrent requests properly. uvicorn[standard] handles
# both HTTP and the Django Channels websocket (bus tracking) through the same
# ASGI app. --workers gives multiple processes for real concurrency; override
# via WEB_CONCURRENCY if the host has more/fewer CPU cores.
echo "🚀 Starting CampusFlow server..."
exec uvicorn campusflow.asgi:application --host 0.0.0.0 --port 8000 --workers "${WEB_CONCURRENCY:-4}"

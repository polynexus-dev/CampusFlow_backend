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

# 0. Sync migrations to clear any drifted files
python migrate_sync.py

# 0.5. Make new migrations for any model changes.
#      --noinput is essential: there is no TTY here, so a model change that
#      needs an interactive answer (a non-nullable field with no default, or a
#      rename Django cannot infer) would otherwise hang the boot forever.
#      With it, such a change fails loudly instead. Keep new fields nullable
#      or defaulted so this step stays non-interactive.
echo "🔄 Auto-generating migrations for any updated models..."
python manage.py makemigrations --noinput


# 1. Run shared (public) schema migrations
echo "🔄 Running shared schema migrations..."
python manage.py migrate_schemas --shared

# 2. Run tenant schema migrations (for any existing tenants)
echo "🔄 Running tenant schema migrations..."
python manage.py migrate_schemas

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

# 4. Create a default superuser in the public schema (if not exists)
echo "🔄 Ensuring public superuser exists..."
python manage.py shell -c "
from django_tenants.utils import schema_context
from django.contrib.auth.models import User
with schema_context('public'):
    if not User.objects.filter(username='admin').exists():
        User.objects.create_superuser('admin', 'admin@campusflow.com', 'admin')
        print('   ✅ Superuser \"admin\" created (password: admin).')
    else:
        print('   ✅ Superuser \"admin\" already exists.')
"

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

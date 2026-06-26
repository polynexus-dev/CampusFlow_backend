#!/bin/bash
set -e

echo "⏳ Waiting for PostgreSQL to be ready..."
while ! pg_isready -h db -U postgres > /dev/null 2>&1; do
    echo "   PostgreSQL is not ready yet — retrying in 2s..."
    sleep 2
done
echo "✅ PostgreSQL is ready!"

# 0. Sync migrations to clear any drifted files
python migrate_sync.py

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
echo "🚀 Starting CampusFlow server..."
exec python manage.py runserver 0.0.0.0:8000

#!/bin/bash
set -e

echo "⏳ Waiting for Redis to be ready..."
until python -c "import redis, sys; redis.from_url('${REDIS_URL:-redis://redis:6379/0}').ping()" > /dev/null 2>&1; do
    echo "   Redis is not ready yet — retrying in 2s..."
    sleep 2
done
echo "✅ Redis is ready!"

# Mirrors entrypoint.sh's reasoning: the repo is a live-mounted volume, so
# requirements.txt changes show up on restart but the image's baked-in
# packages don't — reinstall here so a restart can't run against stale deps.
echo "📦 Syncing installed packages with requirements.txt..."
pip install -r requirements.txt

# This worker only runs the DB-free face-recognition pipeline (see
# campusflow_app/tasks.py) — no migrations/collectstatic needed here.
#
# --concurrency: each worker process loads its own copy of the InsightFace
# model into memory, so this is a memory/CPU tradeoff, not just a speed
# knob. Start low (default 2) and raise via CELERY_CONCURRENCY once you've
# checked actual RAM headroom on the host — don't just match CPU core count
# blindly the way you might for a stateless web worker.
echo "🚀 Starting Celery worker..."
exec celery -A campusflow worker --loglevel=info --concurrency="${CELERY_CONCURRENCY:-2}"

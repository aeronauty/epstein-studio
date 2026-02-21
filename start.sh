#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

PORT="${PORT:-9000}"

export DB_HOST="${DB_HOST:-127.0.0.1}"
export DB_PORT="${DB_PORT:-5432}"
export DB_NAME="${DB_NAME:-epstein}"
export DB_USER="${DB_USER:-postgres}"
export DB_PASSWORD="${DB_PASSWORD:-postgres}"
export DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY:-dev-insecure-key-change-in-prod}"
export DJANGO_DEBUG="${DJANGO_DEBUG:-1}"
export ALLOWED_HOSTS="${ALLOWED_HOSTS:-*}"
export CSRF_TRUSTED_ORIGINS="${CSRF_TRUSTED_ORIGINS:-http://localhost:$PORT}"

# Ensure Postgres is running
if ! docker compose ps --status running db 2>/dev/null | grep -q db; then
    echo "Starting Postgres..."
    docker compose up -d db
    sleep 2
fi

# Activate venv
source .venv/bin/activate

# Run migrations
python backend/manage.py migrate --run-syncdb 2>&1 | grep -v "No migrations to apply" || true

# Kill any existing Django runserver on this port
lsof -ti :"$PORT" | xargs kill -9 2>/dev/null || true

echo "Starting server on http://localhost:$PORT"
exec python backend/manage.py runserver "$PORT"

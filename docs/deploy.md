# Deployment Guide

## Stack
- VPS with Ubuntu
- `nginx` on host
- Django + gunicorn in Docker
- Postgres in Docker

## Required Environment
- Ensure `.env` contains production values.
- Ensure `DJANGO_SECRET_KEY` is set.
- Ensure allowed hosts and CSRF trusted origins match deployed domains.

## Deploy Flow
1. Pull latest code on server.
2. Build and start containers:
   - `docker-compose up --build -d`
3. Run migrations:
   - `docker-compose exec web uv run python backend/manage.py migrate`
4. Collect static files:
   - `docker-compose exec web uv run python backend/manage.py collectstatic --noinput`
5. (Optional/ops) Refresh PDF index:
   - `docker-compose exec web uv run python backend/manage.py index_pdfs`

## Why `collectstatic` Matters
- Production uses Django static handling with hashed filenames.
- New or changed static assets must be collected after deploy.
- If skipped, users may see stale UI or missing assets.

## Nginx Notes
- Proxy app traffic to gunicorn container port.
- Serve static/media from configured paths or via app strategy in use.
- Keep TLS certs valid and auto-renewed.

## Post-Deploy Checks
- `curl -I https://your-domain`
- Open `/browse/` and a document page.
- Confirm CSS/JS updates appear without hard refresh.

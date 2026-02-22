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
5. Download spaCy model (first deploy or after model update):
   - `docker-compose exec web uv run python -m spacy download en_core_web_lg`
6. (Optional) Run analysis pipeline:
   - `docker-compose exec web uv run python backend/manage.py extract_entities`
   - `docker-compose exec web uv run python backend/manage.py load_candidates --fetch`
   - `docker-compose exec web uv run python backend/manage.py match_candidates`
7. Build documentation site:
   - `cd docs-site && npm install && npm run build`
   - Output goes to `docs-site/build/`, served by nginx at `/docs/`.

## Why `collectstatic` Matters

- Production uses Django static handling with hashed filenames.
- New or changed static assets must be collected after deploy.
- If skipped, users may see stale UI or missing assets.

## Nginx Notes

- Proxy app traffic to gunicorn container port.
- Serve static/media from configured paths or via app strategy in use.
- Add a location block for `/docs/` pointing to `docs-site/build/`.
- Keep TLS certs valid and auto-renewed.

## Post-Deploy Checks

- `curl -I https://your-domain`
- Open `/` and verify stats load.
- Open `/redactions-demo/` and confirm redaction grid renders.
- Open `/entities/` and `/matches/` to verify data.
- Open `/docs/` and verify documentation site loads.
- Confirm CSS/JS updates appear without hard refresh.

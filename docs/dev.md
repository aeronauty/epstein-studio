# Development Guide

## Environment
- Python environment and tooling are managed with `uv`.
- Main Django entry point: `backend/manage.py`.
- Main app: `backend/apps/epstein_ui`.

## Local Setup
1. Install dependencies:
   - `uv sync`
2. Run migrations:
   - `uv run python backend/manage.py migrate`
3. Start dev server:
   - `uv run python backend/manage.py runserver`

## Common Commands
- Create migrations:
  - `uv run python backend/manage.py makemigrations`
- Apply migrations:
  - `uv run python backend/manage.py migrate`
- Collect static:
  - `uv run python backend/manage.py collectstatic --noinput`
- Reindex PDFs:
  - `uv run python backend/manage.py index_pdfs`

## Paths You Will Touch Most
- Templates: `backend/apps/epstein_ui/templates/epstein_ui/`
- Static JS/CSS: `backend/apps/epstein_ui/static/epstein_ui/`
- Views: `backend/apps/epstein_ui/views.py`
- URLs: `backend/apps/epstein_ui/urls.py`
- Models: `backend/apps/epstein_ui/models.py`

## Static Asset Rules
- Prefer `{% static %}` in templates.
- Avoid hardcoded `/static/...` paths where template resolution is possible.
- If JS creates static URLs dynamically, use a template-injected static base.

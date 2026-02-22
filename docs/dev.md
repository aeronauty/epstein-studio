# Development Guide

## Environment

- Python environment and tooling are managed with `uv`.
- Main Django entry point: `backend/manage.py`.
- Main app: `backend/apps/epstein_ui`.

## Local Setup

1. Install dependencies:
   - `uv sync`
2. Download spaCy model:
   - `uv run python -m spacy download en_core_web_lg`
3. Run migrations:
   - `uv run python backend/manage.py migrate`
4. Start dev server:
   - `uv run python backend/manage.py runserver`

## Common Commands

- Create migrations:
  - `uv run python backend/manage.py makemigrations`
- Apply migrations:
  - `uv run python backend/manage.py migrate`
- Collect static:
  - `uv run python backend/manage.py collectstatic --noinput`

## Analysis Pipeline Commands

- Extract named entities (NER):
  - `uv run python backend/manage.py extract_entities`
  - Options: `--run-id`, `--model`, `--clear`, `--batch-size`
- Load candidate name lists:
  - `uv run python backend/manage.py load_candidates --fetch`
  - Options: `--fetch` (live API), `--clear`
- Run batch candidate matching:
  - `uv run python backend/manage.py match_candidates`
  - Options: `--clear`, `--doc`, `--limit`, `--top`, `--min-width`

See `docs/operations.md` for full option details.

## Paths You Will Touch Most

- Templates: `backend/apps/epstein_ui/templates/epstein_ui/`
- Static JS/CSS: `backend/apps/epstein_ui/static/epstein_ui/`
- Views: `backend/apps/epstein_ui/views.py`
- URLs: `backend/apps/epstein_ui/urls.py`
- Models: `backend/apps/epstein_ui/models.py`
- Management commands: `backend/apps/epstein_ui/management/commands/`

## External Tools

- `tools/redaction_extractor/`: standalone Python pipeline for detecting redaction bars in PDFs. Has its own `requirements.txt` and entry point (`extract.py`). Writes results to the database (ExtractionRun, ExtractedDocument, RedactionRecord).

## Documentation Site

- Source: `docs-site/` (Docusaurus).
- Build: `cd docs-site && npm install && npm run build`.
- Dev server: `cd docs-site && npm start`.

## Static Asset Rules

- Prefer `{% static %}` in templates.
- Avoid hardcoded `/static/...` paths where template resolution is possible.
- If JS creates static URLs dynamically, use a template-injected static base.

# Operations Playbook

## Management Commands

### Extract Entities (NER)

Runs spaCy NER over all documents in an extraction run and writes `DocumentEntity` rows.

- Local:
  - `uv run python backend/manage.py extract_entities`
- Docker:
  - `docker-compose exec web uv run python backend/manage.py extract_entities`
- Options:
  - `--run-id N`: process a specific extraction run (default: latest).
  - `--model NAME`: spaCy model (default: `en_core_web_lg`).
  - `--clear`: delete existing entities before extracting.
  - `--batch-size N`: spaCy pipe batch size (default: 50).

### Load Candidates

Populates `CandidateList` with names from external sources and curated data.

- Local:
  - `uv run python backend/manage.py load_candidates --fetch`
- Docker:
  - `docker-compose exec web uv run python backend/manage.py load_candidates --fetch`
- Options:
  - `--fetch`: hit the Epstein Exposed API and Black Book site for live data. Without this flag, uses cached data from a previous `--fetch` run.
  - `--clear`: remove all existing candidate lists first.
- Always-loaded curated lists: Key Locations, Key Organisations.

### Match Candidates (Batch)

Runs the full candidate scoring pipeline across all redactions.

- Local:
  - `uv run python backend/manage.py match_candidates`
- Docker:
  - `docker-compose exec web uv run python backend/manage.py match_candidates`
- Options:
  - `--clear`: delete existing candidate matches first.
  - `--doc DOC_ID`: limit to one document.
  - `--limit N`: process at most N redactions (0 = all).
  - `--top N`: store top N candidates per redaction (default: 20).
  - `--min-width PTS`: skip redactions narrower than this (default: 10.0).
- Creates a `BatchRun` record and updates progress during execution.

### Index PDFs (Legacy)

Syncs the `PdfDocument` table with files on disk.

- `uv run python backend/manage.py index_pdfs`
- Note: this command references models that were removed in migration 0015. It may need updating to work with the current schema.

## Full Pipeline Run

To run the complete analysis pipeline after data import:

```bash
# 1. Extract entities
uv run python backend/manage.py extract_entities

# 2. Load candidate lists (first time: use --fetch; subsequent: omit for cached data)
uv run python backend/manage.py load_candidates --fetch

# 3. Run batch matching
uv run python backend/manage.py match_candidates
```

To rerun from scratch:

```bash
uv run python backend/manage.py extract_entities --clear
uv run python backend/manage.py load_candidates --clear --fetch
uv run python backend/manage.py match_candidates --clear
```

## Static/UI Update Issues

Symptoms:
- Users only see new UI after hard refresh.

Checks:
1. Ensure static URLs are not hardcoded where manifest resolution is expected.
2. Run collectstatic after deploy:
   - `uv run python backend/manage.py collectstatic --noinput`
   - or Docker equivalent.
3. Verify browser receives updated static file URLs/content.

## Common Runtime Checks

- App process health:
  - `docker-compose ps`
- App logs:
  - `docker-compose logs --tail=200 web`
- DB logs:
  - `docker-compose logs --tail=200 db`

## Recovery Pattern (Safe)

1. Pull latest code.
2. `docker-compose up --build -d`
3. `docker-compose exec web uv run python backend/manage.py migrate`
4. `docker-compose exec web uv run python backend/manage.py collectstatic --noinput`
5. `docker-compose exec web uv run python -m spacy download en_core_web_lg`
6. Re-run analysis pipeline as needed (see above).

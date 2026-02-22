# Epstein Studio

An open-source toolkit for extracting, analysing, and de-redacting court documents from the Epstein case files. Uses computer vision, font fingerprinting, and NLP to identify what lies beneath the black bars.

**Live at [epstein-studio.com](https://epstein-studio.com)** | **[Documentation](https://epstein-studio.com/docs/)**

---

## What Is This

Epstein Studio processes thousands of redacted PDF court documents through an automated pipeline that detects redaction bars (via PyMuPDF and OpenCV), extracts named entities with spaCy NER, and scores candidate texts that could fit under each redaction using font-width analysis, ascender/descender leakage detection, and contextual NLP.

### Features

- **Redaction Extraction** -- Detect redaction bars using PyMuPDF metadata and OpenCV pixel analysis, with confidence scoring and multiline grouping
- **Interactive Redaction Viewer** -- Browse redactions in a grid, zoom/pan page images, inspect redaction context (text before/after)
- **Font Analysis** -- Overlay text spans from the surrounding PDF, identify the font via per-character width fingerprinting (RMSE matching against candidate fonts)
- **Text Identification** -- Predict gap type (name, date, location, etc.) from context, filter candidates by rendered width, score by leakage letterform analysis, NLP plausibility, and corpus frequency
- **Named Entity Browser** -- Browse all entities extracted from the documents via spaCy NER, filtered by type (PERSON, ORG, GPE, etc.)
- **Candidate List Management** -- Import candidate names from the Epstein Exposed API, Black Book contacts, and curated lists; or add custom lists via the UI
- **Batch Matching** -- Run candidate scoring across all redactions with font identification, width filtering, and multi-signal scoring; results browseable with ranked candidates per redaction

---

## Tech Stack

| Layer | Tech |
|-------|------|
| Backend | Django 5.2 |
| Database | PostgreSQL 16 |
| PDF Rendering | poppler-utils (pdftoppm), PyMuPDF |
| OCR | Tesseract |
| NLP | spaCy (en_core_web_lg) |
| Server | Gunicorn |
| Frontend | Vanilla JS, server-rendered templates |
| Package Manager | uv |
| Deployment | Docker Compose |

---

## Getting Started

### Prerequisites

- Python 3.9+
- PostgreSQL
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- System packages: `poppler-utils`, `tesseract-ocr`

### Local Development

```bash
# install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# install dependencies
uv sync

# set up your environment
cp .env.example .env  # then edit with your DB credentials

# download the spaCy model
uv run python -m spacy download en_core_web_lg

# run migrations
uv run python backend/manage.py migrate

# start the dev server
uv run python backend/manage.py runserver
```

### Analysis Pipeline

After the server is running and extraction data has been imported:

```bash
# extract named entities from documents (requires a completed extraction run)
uv run python backend/manage.py extract_entities

# load candidate name lists from external sources
uv run python backend/manage.py load_candidates --fetch

# run batch candidate matching across all redactions
uv run python backend/manage.py match_candidates
```

### Docker

```bash
# bring up postgres + web server
docker compose up --build

# run migrations inside the container
docker compose exec web uv run python backend/manage.py migrate

# download spaCy model
docker compose exec web uv run python -m spacy download en_core_web_lg
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `DJANGO_SECRET_KEY` | Django secret key |
| `DB_NAME` | PostgreSQL database name |
| `DB_USER` | PostgreSQL user |
| `DB_PASSWORD` | PostgreSQL password |
| `DB_HOST` | Database host (default: `db` in Docker, `localhost` for local) |
| `DB_PORT` | Database port (default: `5432`) |
| `ALLOWED_HOSTS` | Comma-separated list of allowed hostnames |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated list of trusted origins |
| `DATA_DIR` | Path to the directory containing PDF files |

---

## Project Structure

```
epstein-studio/
├── backend/
│   ├── manage.py
│   ├── backend/                    # Django project config
│   │   ├── settings.py
│   │   ├── urls.py
│   │   └── wsgi.py
│   ├── apps/
│   │   └── epstein_ui/            # Main application
│   │       ├── models.py          # Extraction runs, redactions, entities, candidates
│   │       ├── views.py           # Page views and JSON API endpoints
│   │       ├── urls.py            # URL routing
│   │       ├── templates/         # start, redactions_demo, entities, matches
│   │       ├── static/            # style.css, redactions_demo.js, entities.js, matches.js
│   │       └── management/commands/
│   │           ├── extract_entities.py
│   │           ├── load_candidates.py
│   │           └── match_candidates.py
│   └── email_header_extractor/
│       └── extract_headers.py     # OCR-based email header extraction utility
├── tools/
│   └── redaction_extractor/       # Standalone redaction detection pipeline
│       ├── extract.py
│       └── redaction_extractor/   # Detection, merging, leakage, image cropping
├── docs-site/                     # Docusaurus documentation site
├── docs/                          # Markdown docs (source for Docusaurus)
├── pyproject.toml
├── uv.lock
├── Dockerfile
└── docker-compose.yml
```

---

## Contributing

This is an open investigation tool. If you want to help:

1. Fork the repo
2. Create a branch
3. Make your changes
4. Open a PR

---

## License

MIT LICENSE

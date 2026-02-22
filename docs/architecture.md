# Architecture Overview

## High-Level

- Django monolith with server-rendered templates and static JS.
- Redaction extraction pipeline (external tool) writes results to the database.
- Management commands run NER extraction, candidate loading, and batch matching.
- Frontend provides interactive browsing, font analysis, and text identification.

## Main Components

- Web app:
  - Templates and static assets under `backend/apps/epstein_ui/`.
- API-like JSON endpoints:
  - Implemented in `backend/apps/epstein_ui/views.py`.
- Routing:
  - `backend/apps/epstein_ui/urls.py`.
- Data models:
  - `backend/apps/epstein_ui/models.py`.
- Management commands:
  - `backend/apps/epstein_ui/management/commands/`.
- External tool:
  - `tools/redaction_extractor/` -- standalone pipeline that detects redaction bars in PDFs.

## Core Data Domains

### PDF Index
- **PdfDocument**: filename and path for each indexed PDF on disk.

### Redaction Extraction
- **ExtractionRun**: a batch run of the redaction extractor (status, timestamps, parameters, aggregate counts).
- **ExtractedDocument**: per-document results within a run (linked to ExtractionRun and optionally to PdfDocument).
- **RedactionRecord**: one detected redaction bar with full geometry (points and pixels), detection method, confidence, estimated character count, font metrics, surrounding text, leakage flags, multiline info, and cropped image paths.

### NER and Candidate Matching
- **DocumentEntity**: a named entity extracted from a document via spaCy NER (text, type, page, count).
- **CandidateList**: a user-provided or externally-fetched list of candidate names/words stored as JSON.
- **RedactionCandidate**: a scored candidate match for a specific redaction (total score, width fit, NLP score, leakage score, corpus/doc frequency, width ratio, rank).
- **BatchRun**: tracks a batch matching run (progress, total matches, fonts identified).

## Frontend Structure

### Pages
| Page | Template | JS |
|------|----------|----|
| Landing | `start.html` | (none) |
| Redaction browser | `redactions_demo.html` | `redactions_demo.js` |
| Entity browser | `entities.html` | `entities.js` |
| Matches browser | `matches.html` | `matches.js` |

### Shared
- `style.css`: dark theme with CSS custom properties, responsive layouts.

### URL Map
| Path | View | Purpose |
|------|------|---------|
| `/` | `start_page` | Landing with stats |
| `/redactions-demo/` | `redactions_demo` | Redaction grid page |
| `/redactions-list/` | `redactions_list` | Paginated redactions JSON |
| `/redactions/<id>/` | `redaction_detail` | Single redaction JSON |
| `/redactions/<id>/page-image/` | `redaction_page_image` | Rendered PDF page PNG |
| `/redactions/<id>/font-analysis/` | `redaction_font_analysis` | Text spans + font map |
| `/redactions/<id>/font-optimize/` | `redaction_font_optimize` | Per-char width fingerprinting |
| `/redactions/<id>/text-candidates/` | `redaction_text_candidates` | Gap prediction + scored candidates |
| `/redactions-image/<path>` | `redaction_image` | Serve cropped image |
| `/entities/` | `entities_page` | Entity browser page |
| `/entities/list/` | `entities_list` | Paginated entities JSON |
| `/entities/detail/<text>/` | `entity_detail` | Occurrences for one entity |
| `/entities/candidates/` | `candidate_lists` | GET list / POST create candidate lists |
| `/entities/candidates/<id>/delete/` | `candidate_list_delete` | Delete a candidate list |
| `/matches/` | `matches_page` | Matches browser page |
| `/matches/list/` | `matches_list` | Paginated match results JSON |
| `/matches/stats/` | `matches_stats` | Top candidates aggregation |

## Analysis Pipeline

The full pipeline runs in sequence:

1. **Redaction extraction** (`tools/redaction_extractor/`): scan PDFs, detect redaction bars via PyMuPDF and OpenCV, write ExtractionRun + ExtractedDocument + RedactionRecord to the database.
2. **Entity extraction** (`extract_entities` command): run spaCy NER over document text, write DocumentEntity rows.
3. **Candidate loading** (`load_candidates` command): populate CandidateList from external APIs (Epstein Exposed, Black Book), curated lists, or user input.
4. **Batch matching** (`match_candidates` command): for each redaction, identify the font via width fingerprinting, predict gap type from context, filter candidates by rendered width, analyse leakage letterforms, score and rank candidates, write RedactionCandidate rows.

## Management Commands

| Command | Purpose |
|---------|---------|
| `extract_entities` | NER extraction via spaCy (`--run-id`, `--model`, `--clear`, `--batch-size`) |
| `load_candidates` | Load candidate lists (`--fetch` for live API, `--clear`) |
| `match_candidates` | Batch candidate matching (`--clear`, `--doc`, `--limit`, `--top`, `--min-width`) |
| `index_pdfs` | Legacy PDF index sync (references removed models; may need updating) |

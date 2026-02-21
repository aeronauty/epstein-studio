"""
Database writer for redaction extraction results.

Writes CorpusResult to PostgreSQL using psycopg2. Table schema matches
Django models in backend/apps/epstein_ui/models.py.
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import CorpusResult, ExtractionParams

logger = logging.getLogger(__name__)

# Table names (must match Django app label + model name)
TABLE_EXTRACTION_RUN = "epstein_ui_extractionrun"
TABLE_EXTRACTED_DOCUMENT = "epstein_ui_extracteddocument"
TABLE_REDACTION_RECORD = "epstein_ui_redactionrecord"
TABLE_PDF_DOCUMENT = "epstein_ui_pdfdocument"


def _params_to_dict(params: ExtractionParams) -> dict:
    """Convert ExtractionParams to JSON-serializable dict."""
    return {
        "threshold": params.threshold,
        "min_aspect_ratio": params.min_aspect_ratio,
        "min_area": params.min_area,
        "border_padding": params.border_padding,
        "dpi": params.dpi,
        "context_chars": params.context_chars,
        "iou_threshold": params.iou_threshold,
        "margin_threshold": params.margin_threshold,
        "line_height_tolerance": params.line_height_tolerance,
    }


def _resolve_pdf_document_id(conn, file_path: str) -> Optional[int]:
    """
    Look up PdfDocument id by path or filename.
    Returns None if no match.
    """
    filename = Path(file_path).name
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id FROM epstein_ui_pdfdocument
            WHERE path = %s OR filename = %s
            LIMIT 1
            """,
            (file_path, filename),
        )
        row = cur.fetchone()
        return row[0] if row else None


def write_to_database(
    corpus: CorpusResult,
    params: ExtractionParams,
    db_url: str,
) -> int:
    """
    Write extraction results to PostgreSQL.

    Args:
        corpus: Complete corpus results from extraction
        params: Extraction parameters used
        db_url: PostgreSQL connection URL (e.g. postgresql://user:pass@host:5432/dbname)

    Returns:
        The extraction_run_id (primary key of the created ExtractionRun row)

    Raises:
        ImportError: If psycopg2 is not installed
        Exception: On database errors (transaction is rolled back)
    """
    try:
        import psycopg2
        from psycopg2.extras import Json, execute_values
    except ImportError as e:
        raise ImportError(
            "psycopg2-binary is required for database output. "
            "Install with: pip install psycopg2-binary"
        ) from e

    started_at = datetime.now()
    params_dict = _params_to_dict(params)

    with psycopg2.connect(db_url) as conn:
        with conn.cursor() as cur:
            # Insert ExtractionRun
            cur.execute(
                f"""
                INSERT INTO {TABLE_EXTRACTION_RUN}
                (started_at, completed_at, status, parameters, total_documents, total_pages, total_redactions)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    started_at,
                    started_at,
                    "completed",
                    Json(params_dict),
                    corpus.total_documents,
                    corpus.total_pages,
                    corpus.total_redactions,
                ),
            )
            run_id = cur.fetchone()[0]

            # Build doc_id -> extracted_document_id mapping
            doc_ids = {}

            for doc in corpus.documents:
                pdf_doc_id = _resolve_pdf_document_id(conn, doc.file_path)

                cur.execute(
                    f"""
                    INSERT INTO {TABLE_EXTRACTED_DOCUMENT}
                    (extraction_run_id, pdf_document_id, doc_id, file_path, total_pages, error)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        run_id,
                        pdf_doc_id,
                        doc.doc_id,
                        doc.file_path,
                        doc.total_pages,
                        doc.error or "",
                    ),
                )
                extracted_doc_id = cur.fetchone()[0]
                doc_ids[id(doc)] = extracted_doc_id

            # Bulk insert RedactionRecord rows
            redaction_rows = []
            for doc in corpus.documents:
                extracted_doc_id = doc_ids[id(doc)]
                for page in doc.pages:
                    for r in page.redactions:
                        redaction_rows.append(
                            (
                                extracted_doc_id,
                                r.page_num,
                                r.redaction_index,
                                r.bbox_points[0],
                                r.bbox_points[1],
                                r.bbox_points[2],
                                r.bbox_points[3],
                                r.width_points,
                                r.height_points,
                                r.bbox_pixels[0],
                                r.bbox_pixels[1],
                                r.bbox_pixels[2],
                                r.bbox_pixels[3],
                                r.width_pixels,
                                r.height_pixels,
                                r.detection_method,
                                r.confidence,
                                r.estimated_chars,
                                r.font_size_nearby,
                                r.avg_char_width,
                                r.text_before or "",
                                r.text_after or "",
                                r.has_ascender_leakage,
                                r.has_descender_leakage,
                                r.leakage_pixels_top,
                                r.leakage_pixels_bottom,
                                r.is_multiline,
                                r.multiline_group_id or "",
                                r.line_index_in_group,
                                r.image_tight or "",
                                r.image_context or "",
                            )
                        )

            if redaction_rows:
                execute_values(
                    cur,
                    f"""
                    INSERT INTO {TABLE_REDACTION_RECORD}
                    (extracted_document_id, page_num, redaction_index,
                     bbox_x0_points, bbox_y0_points, bbox_x1_points, bbox_y1_points,
                     width_points, height_points,
                     bbox_x0_pixels, bbox_y0_pixels, bbox_x1_pixels, bbox_y1_pixels,
                     width_pixels, height_pixels,
                     detection_method, confidence,
                     estimated_chars, font_size_nearby, avg_char_width,
                     text_before, text_after,
                     has_ascender_leakage, has_descender_leakage,
                     leakage_pixels_top, leakage_pixels_bottom,
                     is_multiline, multiline_group_id, line_index_in_group,
                     image_tight, image_context)
                    VALUES %s
                    """,
                    redaction_rows,
                    page_size=500,
                )

        conn.commit()

    logger.info(
        "Wrote extraction run %s: %d documents, %d redactions",
        run_id,
        corpus.total_documents,
        corpus.total_redactions,
    )
    return run_id

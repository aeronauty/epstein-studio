"""
Output generation for catalogue.json, catalogue.csv, and summary.json.

Handles serialization of redaction data and aggregate statistics.
"""

import json
import csv
from pathlib import Path
from datetime import datetime
from typing import Any
from statistics import mean, median, stdev

from .models import Redaction, DocumentResult, CorpusResult, ExtractionParams


def write_catalogue_json(
    corpus: CorpusResult,
    params: ExtractionParams,
    output_path: Path
) -> None:
    """
    Write the full catalogue to JSON format.
    
    Args:
        corpus: Complete corpus results
        params: Extraction parameters used
        output_path: Path to write JSON file
    """
    # Build the catalogue structure
    catalogue = {
        "extraction_timestamp": datetime.now().isoformat(),
        "parameters": {
            "threshold": params.threshold,
            "min_aspect_ratio": params.min_aspect_ratio,
            "min_area": params.min_area,
            "border_padding": params.border_padding,
            "dpi": params.dpi,
            "context_chars": params.context_chars,
            "iou_threshold": params.iou_threshold,
        },
        "summary": {
            "total_documents": corpus.total_documents,
            "total_pages": corpus.total_pages,
            "total_redactions": corpus.total_redactions,
        },
        "documents": []
    }
    
    # Add each document
    for doc in corpus.documents:
        doc_data = {
            "doc_id": doc.doc_id,
            "file_path": doc.file_path,
            "total_pages": doc.total_pages,
            "total_redactions": doc.total_redactions,
            "error": doc.error,
            "pages": []
        }
        
        for page in doc.pages:
            page_data = {
                "page_num": page.page_num,
                "redaction_count": len(page.redactions),
                "error": page.error,
                "redactions": [r.to_dict() for r in page.redactions]
            }
            doc_data["pages"].append(page_data)
        
        catalogue["documents"].append(doc_data)
    
    # Write to file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(catalogue, f, indent=2, ensure_ascii=False)


def write_catalogue_csv(
    corpus: CorpusResult,
    output_path: Path
) -> None:
    """
    Write the catalogue to CSV format (flat, one row per redaction).
    
    Args:
        corpus: Complete corpus results
        output_path: Path to write CSV file
    """
    # Collect all redactions
    all_redactions = corpus.all_redactions
    
    if not all_redactions:
        # Write empty file with headers
        fieldnames = list(Redaction(
            doc_id="", page_num=0, redaction_index=0,
            bbox_points=(0, 0, 0, 0), width_points=0, height_points=0,
            bbox_pixels=(0, 0, 0, 0), width_pixels=0, height_pixels=0,
            detection_method="", confidence=0
        ).to_csv_row().keys())
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
        return
    
    # Get fieldnames from first redaction
    fieldnames = list(all_redactions[0].to_csv_row().keys())
    
    # Write CSV
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for redaction in all_redactions:
            writer.writerow(redaction.to_csv_row())


def calculate_distribution_stats(values: list[float]) -> dict[str, Any]:
    """
    Calculate distribution statistics for a list of values.
    
    Args:
        values: List of numeric values
        
    Returns:
        Dictionary with distribution statistics
    """
    if not values:
        return {
            "count": 0,
            "mean": 0,
            "median": 0,
            "std": 0,
            "min": 0,
            "max": 0,
        }
    
    return {
        "count": len(values),
        "mean": round(mean(values), 2),
        "median": round(median(values), 2),
        "std": round(stdev(values), 2) if len(values) > 1 else 0,
        "min": min(values),
        "max": max(values),
    }


def calculate_histogram(
    values: list[float],
    buckets: list[tuple[float, float]]
) -> list[dict]:
    """
    Calculate histogram for a list of values.
    
    Args:
        values: List of numeric values
        buckets: List of (min, max) tuples defining bucket ranges
        
    Returns:
        List of bucket dictionaries with counts
    """
    result = []
    for bucket_min, bucket_max in buckets:
        count = sum(1 for v in values if bucket_min <= v < bucket_max)
        result.append({
            "range": f"{bucket_min}-{bucket_max}",
            "min": bucket_min,
            "max": bucket_max,
            "count": count,
        })
    return result


def write_summary_json(
    corpus: CorpusResult,
    params: ExtractionParams,
    output_path: Path
) -> None:
    """
    Write aggregate statistics to summary.json.
    
    Args:
        corpus: Complete corpus results
        params: Extraction parameters used
        output_path: Path to write summary file
    """
    all_redactions = corpus.all_redactions
    
    # Calculate per-document stats
    redactions_per_doc = [d.total_redactions for d in corpus.documents]
    
    # Calculate character count distribution
    char_counts = [r.estimated_chars for r in all_redactions]
    char_buckets = [
        (0, 5), (5, 10), (10, 20), (20, 50), (50, 100), (100, 200), (200, float('inf'))
    ]
    
    # Calculate detection method breakdown
    method_counts = {"pymupdf": 0, "opencv": 0, "both": 0}
    for r in all_redactions:
        method = r.detection_method.lower()
        if method in method_counts:
            method_counts[method] += 1
    
    # Calculate leakage stats
    ascender_hits = sum(1 for r in all_redactions if r.has_ascender_leakage)
    descender_hits = sum(1 for r in all_redactions if r.has_descender_leakage)
    
    # Calculate multiline stats
    multiline_redactions = [r for r in all_redactions if r.is_multiline]
    multiline_groups = set(r.multiline_group_id for r in multiline_redactions if r.multiline_group_id)
    
    # Calculate size stats
    widths_points = [r.width_points for r in all_redactions]
    heights_points = [r.height_points for r in all_redactions]
    
    # Build summary
    summary = {
        "extraction_timestamp": datetime.now().isoformat(),
        "parameters": {
            "threshold": params.threshold,
            "min_aspect_ratio": params.min_aspect_ratio,
            "dpi": params.dpi,
        },
        "corpus_stats": {
            "total_documents": corpus.total_documents,
            "total_pages": corpus.total_pages,
            "total_redactions": corpus.total_redactions,
            "documents_with_errors": sum(1 for d in corpus.documents if d.error),
        },
        "redactions_per_document": calculate_distribution_stats(redactions_per_doc),
        "character_count": {
            "distribution": calculate_distribution_stats(char_counts),
            "histogram": calculate_histogram(char_counts, char_buckets),
        },
        "detection_method_breakdown": {
            "pymupdf_only": method_counts["pymupdf"],
            "opencv_only": method_counts["opencv"],
            "both_methods": method_counts["both"],
        },
        "leakage_stats": {
            "ascender_hits": ascender_hits,
            "descender_hits": descender_hits,
            "total_with_leakage": ascender_hits + descender_hits,
            "leakage_rate": round(
                (ascender_hits + descender_hits) / len(all_redactions), 4
            ) if all_redactions else 0,
        },
        "multiline_stats": {
            "total_multiline_redactions": len(multiline_redactions),
            "total_multiline_groups": len(multiline_groups),
            "multiline_rate": round(
                len(multiline_redactions) / len(all_redactions), 4
            ) if all_redactions else 0,
        },
        "size_stats": {
            "width_points": calculate_distribution_stats(widths_points),
            "height_points": calculate_distribution_stats(heights_points),
        },
    }
    
    # Write to file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)


def write_all_outputs(
    corpus: CorpusResult,
    params: ExtractionParams,
    output_dir: Path
) -> dict[str, Path]:
    """
    Write all output files (catalogue.json, catalogue.csv, summary.json).
    
    Args:
        corpus: Complete corpus results
        params: Extraction parameters used
        output_dir: Base output directory
        
    Returns:
        Dictionary mapping output type to file path
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    
    paths = {
        "catalogue_json": output_dir / "catalogue.json",
        "catalogue_csv": output_dir / "catalogue.csv",
        "summary_json": output_dir / "summary.json",
    }
    
    write_catalogue_json(corpus, params, paths["catalogue_json"])
    write_catalogue_csv(corpus, paths["catalogue_csv"])
    write_summary_json(corpus, params, paths["summary_json"])
    
    return paths


def write_document_json(
    doc: DocumentResult,
    params: ExtractionParams,
    output_path: Path
) -> None:
    """
    Write a single document's results to JSON.
    
    Useful for incremental processing.
    
    Args:
        doc: Document results
        params: Extraction parameters used
        output_path: Path to write JSON file
    """
    data = {
        "extraction_timestamp": datetime.now().isoformat(),
        "parameters": {
            "threshold": params.threshold,
            "min_aspect_ratio": params.min_aspect_ratio,
            "dpi": params.dpi,
        },
        "doc_id": doc.doc_id,
        "file_path": doc.file_path,
        "total_pages": doc.total_pages,
        "total_redactions": doc.total_redactions,
        "error": doc.error,
        "pages": [
            {
                "page_num": page.page_num,
                "redaction_count": len(page.redactions),
                "error": page.error,
                "redactions": [r.to_dict() for r in page.redactions]
            }
            for page in doc.pages
        ]
    }
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

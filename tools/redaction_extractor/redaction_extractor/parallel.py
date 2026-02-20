"""
Multiprocessing orchestration for parallel PDF processing.

Handles parallel processing of multiple PDFs using multiprocessing Pool,
with progress tracking and error handling.
"""

import multiprocessing
from pathlib import Path
from typing import Optional, Callable
import logging

import fitz

from .models import (
    Redaction, PageResult, DocumentResult, CorpusResult, 
    ExtractionParams, MergedDetection, DetectionMethod
)
from .pdf_extractor import extract_pdf_redactions
from .pixel_detector import render_page_to_image, detect_pixel_redactions, points_to_pixels
from .detection_merger import merge_detections
from .context_analyzer import analyze_context
from .leakage_detector import analyze_leakage
from .multiline_merger import merge_multiline_redactions
from .image_cropper import extract_and_save_crops


logger = logging.getLogger(__name__)


def process_page(
    page: fitz.Page,
    page_num: int,
    doc_id: str,
    params: ExtractionParams,
    output_dir: Optional[Path] = None
) -> PageResult:
    """
    Process a single page to extract redactions.
    
    Args:
        page: PyMuPDF page object
        page_num: Page number (1-indexed)
        doc_id: Document identifier
        params: Extraction parameters
        output_dir: Output directory for images (optional)
        
    Returns:
        PageResult with all detected redactions
    """
    try:
        # Get page dimensions
        page_rect = page.rect
        page_width = page_rect.width
        page_height = page_rect.height
        
        # Extract using PyMuPDF
        pdf_detections = extract_pdf_redactions(page, params.min_aspect_ratio)
        
        # Render page to image for pixel detection
        page_image = render_page_to_image(page, params.dpi)
        page_height_pixels = page_image.shape[0]
        
        # Detect using OpenCV
        pixel_detections = detect_pixel_redactions(
            page_image,
            page_height_pixels,
            params.dpi,
            params.threshold,
            params.min_aspect_ratio,
            params.min_area
        )
        
        # Merge detections
        merged = merge_detections(
            pdf_detections,
            pixel_detections,
            params.iou_threshold
        )
        
        # Convert to Redaction objects with full analysis
        redactions = []
        for i, detection in enumerate(merged):
            # Convert bbox to pixels
            bbox_pixels = points_to_pixels(
                detection.bbox,
                page_height,
                params.dpi
            )
            
            # Analyze context and estimate characters
            context = analyze_context(page, detection.bbox, params.context_chars)
            
            # Analyze leakage
            leakage = analyze_leakage(page_image, bbox_pixels)
            
            # Create Redaction object
            redaction = Redaction(
                doc_id=doc_id,
                page_num=page_num,
                redaction_index=i,
                bbox_points=detection.bbox,
                width_points=detection.width,
                height_points=detection.height,
                bbox_pixels=bbox_pixels,
                width_pixels=bbox_pixels[2] - bbox_pixels[0],
                height_pixels=bbox_pixels[3] - bbox_pixels[1],
                detection_method=detection.method.value,
                confidence=detection.confidence,
                estimated_chars=context.estimated_chars,
                font_size_nearby=context.font_size_nearby,
                avg_char_width=context.avg_char_width,
                text_before=context.text_before,
                text_after=context.text_after,
                has_ascender_leakage=leakage.has_ascender_leakage,
                has_descender_leakage=leakage.has_descender_leakage,
                leakage_pixels_top=leakage.leakage_pixels_top,
                leakage_pixels_bottom=leakage.leakage_pixels_bottom,
            )
            
            # Extract and save images if output directory provided
            if output_dir is not None:
                tight_path, context_path = extract_and_save_crops(
                    page_image,
                    bbox_pixels,
                    doc_id,
                    page_num,
                    i,
                    output_dir,
                    params.border_padding
                )
                redaction.image_tight = tight_path
                redaction.image_context = context_path
            
            redactions.append(redaction)
        
        # Detect and mark multi-line redactions
        if redactions:
            merge_multiline_redactions(
                redactions,
                page_width,
                params.margin_threshold,
                params.line_height_tolerance
            )
        
        return PageResult(page_num=page_num, redactions=redactions)
    
    except Exception as e:
        logger.error(f"Error processing page {page_num}: {e}")
        return PageResult(page_num=page_num, error=str(e))


def process_document(
    pdf_path: Path,
    params: ExtractionParams,
    output_dir: Optional[Path] = None
) -> DocumentResult:
    """
    Process a single PDF document.
    
    Args:
        pdf_path: Path to the PDF file
        params: Extraction parameters
        output_dir: Output directory for images (optional)
        
    Returns:
        DocumentResult with all pages processed
    """
    doc_id = pdf_path.stem
    
    try:
        doc = fitz.open(str(pdf_path))
        total_pages = len(doc)
        
        pages = []
        for page_num in range(total_pages):
            page = doc[page_num]
            result = process_page(
                page,
                page_num + 1,  # 1-indexed
                doc_id,
                params,
                output_dir
            )
            pages.append(result)
        
        doc.close()
        
        return DocumentResult(
            doc_id=doc_id,
            file_path=str(pdf_path),
            total_pages=total_pages,
            pages=pages
        )
    
    except Exception as e:
        logger.error(f"Error processing document {pdf_path}: {e}")
        return DocumentResult(
            doc_id=doc_id,
            file_path=str(pdf_path),
            error=str(e)
        )


def _process_document_wrapper(args: tuple) -> DocumentResult:
    """
    Wrapper for multiprocessing - unpacks arguments.
    """
    pdf_path, params, output_dir = args
    return process_document(pdf_path, params, output_dir)


def process_corpus(
    input_dir: Path,
    output_dir: Path,
    params: ExtractionParams,
    workers: int = 4,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    subset: Optional[int] = None
) -> CorpusResult:
    """
    Process all PDFs in a directory using parallel processing.
    
    Args:
        input_dir: Directory containing PDF files
        output_dir: Directory for output files
        params: Extraction parameters
        workers: Number of parallel workers
        progress_callback: Optional callback for progress updates (current, total)
        subset: If set, only process the first N PDFs (for testing)
        
    Returns:
        CorpusResult with all documents processed
    """
    # Find all PDF files
    pdf_files = sorted(input_dir.glob("**/*.pdf"))
    if subset is not None:
        pdf_files = pdf_files[:subset]
    total_files = len(pdf_files)
    
    if total_files == 0:
        logger.warning(f"No PDF files found in {input_dir}")
        return CorpusResult()
    
    logger.info(f"Found {total_files} PDF files to process")
    
    # Prepare arguments for each document
    args_list = [(pdf, params, output_dir) for pdf in pdf_files]
    
    # Process in parallel
    documents = []
    
    if workers <= 1:
        # Single-threaded processing
        for i, args in enumerate(args_list):
            result = _process_document_wrapper(args)
            documents.append(result)
            if progress_callback:
                progress_callback(i + 1, total_files)
    else:
        # Multi-process parallel processing
        with multiprocessing.Pool(workers) as pool:
            # Use imap for progress tracking
            for i, result in enumerate(pool.imap(_process_document_wrapper, args_list)):
                documents.append(result)
                if progress_callback:
                    progress_callback(i + 1, total_files)
    
    return CorpusResult(documents=documents)


def process_corpus_with_tqdm(
    input_dir: Path,
    output_dir: Path,
    params: ExtractionParams,
    workers: int = 4,
    subset: Optional[int] = None
) -> CorpusResult:
    """
    Process corpus with tqdm progress bar.
    
    Args:
        input_dir: Directory containing PDF files
        output_dir: Directory for output files
        params: Extraction parameters
        workers: Number of parallel workers
        subset: If set, only process the first N PDFs (for testing)
        
    Returns:
        CorpusResult with all documents processed
    """
    try:
        from tqdm import tqdm
    except ImportError:
        logger.warning("tqdm not available, falling back to basic progress")
        return process_corpus(input_dir, output_dir, params, workers, subset=subset)
    
    # Find all PDF files
    pdf_files = sorted(input_dir.glob("**/*.pdf"))
    if subset is not None:
        pdf_files = pdf_files[:subset]
    total_files = len(pdf_files)
    
    if total_files == 0:
        logger.warning(f"No PDF files found in {input_dir}")
        return CorpusResult()
    
    # Prepare arguments
    args_list = [(pdf, params, output_dir) for pdf in pdf_files]
    
    documents = []
    
    if workers <= 1:
        # Single-threaded with progress bar
        for args in tqdm(args_list, desc="Processing PDFs", unit="file"):
            result = _process_document_wrapper(args)
            documents.append(result)
    else:
        # Multi-process with progress bar
        with multiprocessing.Pool(workers) as pool:
            results = list(tqdm(
                pool.imap(_process_document_wrapper, args_list),
                total=total_files,
                desc="Processing PDFs",
                unit="file"
            ))
            documents = results
    
    return CorpusResult(documents=documents)


def get_processing_stats(corpus: CorpusResult) -> dict:
    """
    Get statistics about the processing run.
    
    Args:
        corpus: Completed corpus result
        
    Returns:
        Dictionary with processing statistics
    """
    successful_docs = [d for d in corpus.documents if d.error is None]
    failed_docs = [d for d in corpus.documents if d.error is not None]
    
    pages_with_errors = sum(
        1 for d in successful_docs 
        for p in d.pages 
        if p.error is not None
    )
    
    return {
        "total_documents": corpus.total_documents,
        "successful_documents": len(successful_docs),
        "failed_documents": len(failed_docs),
        "total_pages": corpus.total_pages,
        "pages_with_errors": pages_with_errors,
        "total_redactions": corpus.total_redactions,
        "failed_doc_ids": [d.doc_id for d in failed_docs],
    }

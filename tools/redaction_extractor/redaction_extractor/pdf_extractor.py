"""
PyMuPDF-based redaction extraction from PDF structure.

Extracts redaction candidates from:
- Redact annotations (PDF_ANNOT_REDACT)
- Rectangle annotations with dark fill
- Drawing commands (filled rectangles)
"""

import fitz
from typing import Optional

from .models import RawDetection, DetectionMethod


# Color threshold for considering a fill as "dark" (0-1 scale, 0 is black)
DARK_COLOR_THRESHOLD = 0.15


def is_dark_color(color: Optional[tuple]) -> bool:
    """
    Check if a color is dark enough to be a potential redaction.
    
    Args:
        color: RGB tuple (0-1 scale) or None
        
    Returns:
        True if color is dark (close to black)
    """
    if color is None:
        return False
    
    # Handle grayscale (single value)
    if isinstance(color, (int, float)):
        return color < DARK_COLOR_THRESHOLD
    
    # Handle RGB tuple
    if len(color) >= 3:
        # Use luminance formula: 0.299*R + 0.587*G + 0.114*B
        luminance = 0.299 * color[0] + 0.587 * color[1] + 0.114 * color[2]
        return luminance < DARK_COLOR_THRESHOLD
    
    return False


def extract_from_annotations(page: fitz.Page) -> list[RawDetection]:
    """
    Extract redaction candidates from page annotations.
    
    Looks for:
    - Redact annotations (explicit redaction markers)
    - Square/Rectangle annotations with dark fill
    - Highlight annotations with dark color
    
    Args:
        page: PyMuPDF page object
        
    Returns:
        List of raw detections from annotations
    """
    detections = []
    
    for annot in page.annots() or []:
        annot_type = annot.type[0]  # Numeric annotation type
        annot_name = annot.type[1]  # String name
        
        # Explicit redact annotation
        if annot_type == fitz.PDF_ANNOT_REDACT:
            rect = annot.rect
            detections.append(RawDetection(
                bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                method=DetectionMethod.PYMUPDF,
                confidence=1.0,
                annotation_type="redact"
            ))
            continue
        
        # Square or rectangle annotation with dark fill
        if annot_type in (fitz.PDF_ANNOT_SQUARE, fitz.PDF_ANNOT_POLYGON):
            colors = annot.colors
            fill_color = colors.get("fill") if colors else None
            
            if is_dark_color(fill_color):
                rect = annot.rect
                detections.append(RawDetection(
                    bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                    method=DetectionMethod.PYMUPDF,
                    confidence=0.9,
                    annotation_type=annot_name
                ))
            continue
        
        # Highlight with very dark color (unusual but possible)
        if annot_type == fitz.PDF_ANNOT_HIGHLIGHT:
            colors = annot.colors
            stroke_color = colors.get("stroke") if colors else None
            
            if is_dark_color(stroke_color):
                rect = annot.rect
                detections.append(RawDetection(
                    bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                    method=DetectionMethod.PYMUPDF,
                    confidence=0.7,
                    annotation_type="highlight_dark"
                ))
    
    return detections


def extract_from_drawings(page: fitz.Page, min_aspect_ratio: float = 2.0) -> list[RawDetection]:
    """
    Extract redaction candidates from page drawing commands.
    
    Looks for filled rectangles with dark color that have
    a horizontal aspect ratio (wider than tall).
    
    Args:
        page: PyMuPDF page object
        min_aspect_ratio: Minimum width/height ratio to consider
        
    Returns:
        List of raw detections from drawings
    """
    detections = []
    
    try:
        drawings = page.get_drawings()
    except Exception:
        # Some PDFs may have issues with drawing extraction
        return detections
    
    for drawing in drawings:
        # We're looking for filled rectangles
        if drawing.get("fill") is None:
            continue
        
        fill_color = drawing.get("fill")
        if not is_dark_color(fill_color):
            continue
        
        # Get the bounding rectangle of the drawing
        rect = drawing.get("rect")
        if rect is None:
            continue
        
        # Convert to fitz.Rect if needed
        if not isinstance(rect, fitz.Rect):
            rect = fitz.Rect(rect)
        
        width = rect.width
        height = rect.height
        
        # Skip if too small (noise)
        if width < 10 or height < 3:
            continue
        
        # Check aspect ratio - redaction bars are typically wide and short
        if height > 0 and width / height >= min_aspect_ratio:
            detections.append(RawDetection(
                bbox=(rect.x0, rect.y0, rect.x1, rect.y1),
                method=DetectionMethod.PYMUPDF,
                confidence=0.85,
                annotation_type="drawing_rect"
            ))
    
    return detections


def extract_from_text_backgrounds(page: fitz.Page) -> list[RawDetection]:
    """
    Extract redaction candidates from text spans with dark backgrounds.
    
    Some PDFs implement redactions as text with black background
    and black foreground (hiding the text visually).
    
    Args:
        page: PyMuPDF page object
        
    Returns:
        List of raw detections from text backgrounds
    """
    detections = []
    
    try:
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    except Exception:
        return detections
    
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:  # Text block
            continue
        
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                # Check if span has a dark background color
                # This is stored in the "color" field as background when available
                bbox = span.get("bbox")
                if bbox is None:
                    continue
                
                # Check for spans where text color matches background (hidden text)
                color = span.get("color")
                if color is not None and is_dark_color(_int_to_rgb(color)):
                    # This might be redacted text - dark text could indicate
                    # intentionally obscured content
                    width = bbox[2] - bbox[0]
                    height = bbox[3] - bbox[1]
                    
                    # Only consider if it has redaction-like dimensions
                    if width > 20 and height > 5 and height < 30:
                        detections.append(RawDetection(
                            bbox=tuple(bbox),
                            method=DetectionMethod.PYMUPDF,
                            confidence=0.6,
                            annotation_type="text_dark"
                        ))
    
    return detections


def _int_to_rgb(color_int: int) -> tuple[float, float, float]:
    """Convert integer color to RGB tuple (0-1 scale)."""
    r = ((color_int >> 16) & 0xFF) / 255.0
    g = ((color_int >> 8) & 0xFF) / 255.0
    b = (color_int & 0xFF) / 255.0
    return (r, g, b)


def extract_pdf_redactions(
    page: fitz.Page,
    min_aspect_ratio: float = 2.0
) -> list[RawDetection]:
    """
    Extract all redaction candidates from a PDF page using PyMuPDF.
    
    Combines results from:
    - Annotations (redact, square, highlight)
    - Drawing commands (filled rectangles)
    - Text backgrounds (dark text spans)
    
    Args:
        page: PyMuPDF page object
        min_aspect_ratio: Minimum width/height for drawing detection
        
    Returns:
        List of raw detections from all PDF structure sources
    """
    detections = []
    
    # Extract from annotations
    detections.extend(extract_from_annotations(page))
    
    # Extract from drawings
    detections.extend(extract_from_drawings(page, min_aspect_ratio))
    
    # NOTE: extract_from_text_backgrounds() is intentionally disabled.
    # It only checks foreground text color (dark = potential redaction) but
    # PyMuPDF's text dict does not expose per-span background color, so it
    # cannot distinguish normal black text from black-on-black hidden text.
    # This produced 100% false positives (every word on the page).
    # Pixel-level detection via OpenCV already covers this case correctly.
    
    return detections

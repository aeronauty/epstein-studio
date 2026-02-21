"""
Context extraction and character count estimation.

Uses PyMuPDF text extraction to:
- Find text spans near redactions
- Extract surrounding context (~200 chars before/after)
- Estimate character count based on font metrics
"""

import fitz
from typing import Optional
from dataclasses import dataclass


@dataclass
class TextSpan:
    """A text span with position and font information."""
    text: str
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1
    font_size: float
    font_name: str
    char_width: float  # Average character width
    
    @property
    def x0(self) -> float:
        return self.bbox[0]
    
    @property
    def y0(self) -> float:
        return self.bbox[1]
    
    @property
    def x1(self) -> float:
        return self.bbox[2]
    
    @property
    def y1(self) -> float:
        return self.bbox[3]


@dataclass
class ContextResult:
    """Result of context extraction and character estimation."""
    text_before: str
    text_after: str
    estimated_chars: int
    font_size_nearby: Optional[float]
    avg_char_width: Optional[float]


def extract_text_spans(page: fitz.Page) -> list[TextSpan]:
    """
    Extract all text spans from a page with their positions and font info.
    
    Args:
        page: PyMuPDF page object
        
    Returns:
        List of TextSpan objects sorted by reading order
    """
    spans = []
    
    try:
        text_dict = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
    except Exception:
        return spans
    
    for block in text_dict.get("blocks", []):
        if block.get("type") != 0:  # Text block
            continue
        
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                text = span.get("text", "")
                if not text.strip():
                    continue
                
                bbox = span.get("bbox")
                if bbox is None:
                    continue
                
                font_size = span.get("size", 12.0)
                font_name = span.get("font", "unknown")
                
                # Calculate average character width
                span_width = bbox[2] - bbox[0]
                char_count = len(text)
                char_width = span_width / char_count if char_count > 0 else font_size * 0.5
                
                spans.append(TextSpan(
                    text=text,
                    bbox=tuple(bbox),
                    font_size=font_size,
                    font_name=font_name,
                    char_width=char_width
                ))
    
    # Sort by reading order: top-to-bottom, then left-to-right
    spans.sort(key=lambda s: (s.y0, s.x0))
    
    return spans


def find_nearby_spans(
    spans: list[TextSpan],
    redaction_bbox: tuple[float, float, float, float],
    proximity: float = 50.0
) -> list[TextSpan]:
    """
    Find text spans near a redaction.
    
    Args:
        spans: List of text spans on the page
        redaction_bbox: (x0, y0, x1, y1) of the redaction
        proximity: Maximum distance in points to consider "nearby"
        
    Returns:
        List of spans within proximity of the redaction
    """
    rx0, ry0, rx1, ry1 = redaction_bbox
    nearby = []
    
    for span in spans:
        # Check if span is within proximity of redaction
        # Expand redaction bbox by proximity and check intersection
        if (span.x1 >= rx0 - proximity and 
            span.x0 <= rx1 + proximity and
            span.y1 >= ry0 - proximity and 
            span.y0 <= ry1 + proximity):
            nearby.append(span)
    
    return nearby


def find_same_line_spans(
    spans: list[TextSpan],
    redaction_bbox: tuple[float, float, float, float],
    vertical_tolerance: float = 5.0
) -> list[TextSpan]:
    """
    Find text spans on the same line as a redaction.
    
    Args:
        spans: List of text spans on the page
        redaction_bbox: (x0, y0, x1, y1) of the redaction
        vertical_tolerance: Maximum vertical distance to consider same line
        
    Returns:
        List of spans on the same line
    """
    rx0, ry0, rx1, ry1 = redaction_bbox
    redaction_center_y = (ry0 + ry1) / 2
    
    same_line = []
    for span in spans:
        span_center_y = (span.y0 + span.y1) / 2
        if abs(span_center_y - redaction_center_y) <= vertical_tolerance:
            same_line.append(span)
    
    return same_line


def estimate_character_count(
    redaction_bbox: tuple[float, float, float, float],
    nearby_spans: list[TextSpan]
) -> tuple[int, Optional[float], Optional[float]]:
    """
    Estimate the number of characters covered by a redaction.
    
    Uses font metrics from nearby text to estimate character width,
    then divides redaction width by average character width.
    
    Args:
        redaction_bbox: (x0, y0, x1, y1) of the redaction
        nearby_spans: Text spans near the redaction
        
    Returns:
        Tuple of (estimated_chars, font_size, avg_char_width)
    """
    if not nearby_spans:
        # Fallback: assume standard 12pt font, ~6pt average char width
        redaction_width = redaction_bbox[2] - redaction_bbox[0]
        estimated = int(redaction_width / 6.0)
        return (max(1, estimated), None, None)
    
    # Calculate weighted average character width from nearby spans
    total_chars = 0
    total_width = 0.0
    font_sizes = []
    
    for span in nearby_spans:
        char_count = len(span.text)
        total_chars += char_count
        total_width += span.char_width * char_count
        font_sizes.append(span.font_size)
    
    if total_chars == 0:
        redaction_width = redaction_bbox[2] - redaction_bbox[0]
        return (max(1, int(redaction_width / 6.0)), None, None)
    
    avg_char_width = total_width / total_chars
    avg_font_size = sum(font_sizes) / len(font_sizes)
    
    # Estimate character count
    redaction_width = redaction_bbox[2] - redaction_bbox[0]
    estimated_chars = int(redaction_width / avg_char_width)
    
    return (max(1, estimated_chars), avg_font_size, avg_char_width)


def extract_context(
    spans: list[TextSpan],
    redaction_bbox: tuple[float, float, float, float],
    context_chars: int = 200
) -> tuple[str, str]:
    """
    Extract text context before and after a redaction.
    
    Args:
        spans: List of text spans on the page (sorted by reading order)
        redaction_bbox: (x0, y0, x1, y1) of the redaction
        context_chars: Number of characters to extract on each side
        
    Returns:
        Tuple of (text_before, text_after)
    """
    rx0, ry0, rx1, ry1 = redaction_bbox
    redaction_center = ((rx0 + rx1) / 2, (ry0 + ry1) / 2)
    
    # Classify spans as before or after the redaction
    before_spans = []
    after_spans = []
    
    for span in spans:
        span_center = ((span.x0 + span.x1) / 2, (span.y0 + span.y1) / 2)
        
        # Compare by reading order (y first, then x)
        if span_center[1] < redaction_center[1] - 5:
            # Span is above redaction
            before_spans.append(span)
        elif span_center[1] > redaction_center[1] + 5:
            # Span is below redaction
            after_spans.append(span)
        else:
            # Same line - use x position
            if span_center[0] < redaction_center[0]:
                before_spans.append(span)
            else:
                after_spans.append(span)
    
    # Build context strings
    before_text = " ".join(s.text for s in before_spans)
    after_text = " ".join(s.text for s in after_spans)
    
    # Trim to context_chars
    if len(before_text) > context_chars:
        before_text = "..." + before_text[-(context_chars - 3):]
    if len(after_text) > context_chars:
        after_text = after_text[:context_chars - 3] + "..."
    
    return (before_text.strip(), after_text.strip())


def analyze_context(
    page: fitz.Page,
    redaction_bbox: tuple[float, float, float, float],
    context_chars: int = 200
) -> ContextResult:
    """
    Perform full context analysis for a redaction.
    
    Args:
        page: PyMuPDF page object
        redaction_bbox: (x0, y0, x1, y1) of the redaction
        context_chars: Number of context characters to extract
        
    Returns:
        ContextResult with text context and character estimation
    """
    # Extract all text spans
    spans = extract_text_spans(page)
    
    # Find nearby spans for font metrics
    nearby = find_nearby_spans(spans, redaction_bbox, proximity=50.0)
    
    # If no nearby spans, try same-line spans with wider tolerance
    if not nearby:
        nearby = find_same_line_spans(spans, redaction_bbox, vertical_tolerance=20.0)
    
    # Estimate character count
    estimated_chars, font_size, char_width = estimate_character_count(
        redaction_bbox, nearby
    )
    
    # Extract context
    text_before, text_after = extract_context(spans, redaction_bbox, context_chars)
    
    return ContextResult(
        text_before=text_before,
        text_after=text_after,
        estimated_chars=estimated_chars,
        font_size_nearby=font_size,
        avg_char_width=char_width
    )

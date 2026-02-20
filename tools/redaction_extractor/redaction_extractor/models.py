"""
Data models for redaction extraction.

Defines dataclasses for raw detections, merged detections, and final redaction entities.
"""

from dataclasses import dataclass, field, asdict
from typing import Optional
from enum import Enum


class DetectionMethod(Enum):
    """Source of redaction detection."""
    PYMUPDF = "pymupdf"
    OPENCV = "opencv"
    BOTH = "both"


@dataclass
class RawDetection:
    """
    A raw detection from a single method (PyMuPDF or OpenCV).
    
    Coordinates are in PDF points (72 per inch).
    """
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points
    method: DetectionMethod
    confidence: float = 1.0
    annotation_type: Optional[str] = None  # For PyMuPDF: annotation subtype
    
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
    
    @property
    def width(self) -> float:
        return self.x1 - self.x0
    
    @property
    def height(self) -> float:
        return self.y1 - self.y0
    
    @property
    def area(self) -> float:
        return self.width * self.height
    
    @property
    def aspect_ratio(self) -> float:
        if self.height == 0:
            return float('inf')
        return self.width / self.height


@dataclass
class MergedDetection:
    """
    A detection after merging PyMuPDF and OpenCV results.
    """
    bbox: tuple[float, float, float, float]  # x0, y0, x1, y1 in PDF points
    method: DetectionMethod
    confidence: float
    pymupdf_match: Optional[RawDetection] = None
    opencv_match: Optional[RawDetection] = None
    
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
    
    @property
    def width(self) -> float:
        return self.x1 - self.x0
    
    @property
    def height(self) -> float:
        return self.y1 - self.y0


@dataclass
class Redaction:
    """
    A fully processed redaction with all analysis complete.
    """
    # Identification
    doc_id: str
    page_num: int
    redaction_index: int
    
    # Geometry in PDF points
    bbox_points: tuple[float, float, float, float]  # x0, y0, x1, y1
    width_points: float
    height_points: float
    
    # Geometry in pixels (at render DPI)
    bbox_pixels: tuple[int, int, int, int]  # x0, y0, x1, y1
    width_pixels: int
    height_pixels: int
    
    # Detection metadata
    detection_method: str  # "pymupdf", "opencv", or "both"
    confidence: float
    
    # Character estimation
    estimated_chars: int = 0
    font_size_nearby: Optional[float] = None
    avg_char_width: Optional[float] = None
    
    # Context
    text_before: str = ""
    text_after: str = ""
    
    # Leakage analysis
    has_ascender_leakage: bool = False
    has_descender_leakage: bool = False
    leakage_pixels_top: int = 0
    leakage_pixels_bottom: int = 0
    
    # Multi-line grouping
    is_multiline: bool = False
    multiline_group_id: Optional[str] = None
    line_index_in_group: Optional[int] = None
    
    # Image paths (relative to output directory)
    image_tight: str = ""
    image_context: str = ""
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)
    
    def to_csv_row(self) -> dict:
        """Convert to flat dictionary for CSV output."""
        return {
            "doc_id": self.doc_id,
            "page_num": self.page_num,
            "redaction_index": self.redaction_index,
            "bbox_x0_points": self.bbox_points[0],
            "bbox_y0_points": self.bbox_points[1],
            "bbox_x1_points": self.bbox_points[2],
            "bbox_y1_points": self.bbox_points[3],
            "width_points": self.width_points,
            "height_points": self.height_points,
            "bbox_x0_pixels": self.bbox_pixels[0],
            "bbox_y0_pixels": self.bbox_pixels[1],
            "bbox_x1_pixels": self.bbox_pixels[2],
            "bbox_y1_pixels": self.bbox_pixels[3],
            "width_pixels": self.width_pixels,
            "height_pixels": self.height_pixels,
            "detection_method": self.detection_method,
            "confidence": self.confidence,
            "estimated_chars": self.estimated_chars,
            "font_size_nearby": self.font_size_nearby,
            "avg_char_width": self.avg_char_width,
            "text_before": self.text_before,
            "text_after": self.text_after,
            "has_ascender_leakage": self.has_ascender_leakage,
            "has_descender_leakage": self.has_descender_leakage,
            "leakage_pixels_top": self.leakage_pixels_top,
            "leakage_pixels_bottom": self.leakage_pixels_bottom,
            "is_multiline": self.is_multiline,
            "multiline_group_id": self.multiline_group_id,
            "line_index_in_group": self.line_index_in_group,
            "image_tight": self.image_tight,
            "image_context": self.image_context,
        }


@dataclass
class PageResult:
    """Results from processing a single page."""
    page_num: int
    redactions: list[Redaction] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class DocumentResult:
    """Results from processing a single document."""
    doc_id: str
    file_path: str
    total_pages: int = 0
    pages: list[PageResult] = field(default_factory=list)
    error: Optional[str] = None
    
    @property
    def total_redactions(self) -> int:
        return sum(len(p.redactions) for p in self.pages)
    
    @property
    def all_redactions(self) -> list[Redaction]:
        redactions = []
        for page in self.pages:
            redactions.extend(page.redactions)
        return redactions


@dataclass
class CorpusResult:
    """Results from processing an entire corpus of documents."""
    documents: list[DocumentResult] = field(default_factory=list)
    
    @property
    def total_documents(self) -> int:
        return len(self.documents)
    
    @property
    def total_pages(self) -> int:
        return sum(d.total_pages for d in self.documents)
    
    @property
    def total_redactions(self) -> int:
        return sum(d.total_redactions for d in self.documents)
    
    @property
    def all_redactions(self) -> list[Redaction]:
        redactions = []
        for doc in self.documents:
            redactions.extend(doc.all_redactions)
        return redactions


@dataclass
class ExtractionParams:
    """Parameters for redaction extraction."""
    threshold: int = 30  # Pixel darkness threshold (0-255)
    min_aspect_ratio: float = 3.0  # Minimum width/height for bars
    min_area: int = 500  # Minimum area in pixels
    border_padding: int = 50  # Context crop padding
    dpi: int = 150  # Render DPI
    context_chars: int = 200  # Characters of context before/after
    iou_threshold: float = 0.7  # IoU threshold for merging detections
    margin_threshold: float = 50  # Points from margin for multiline detection
    line_height_tolerance: float = 5  # Points tolerance for line height matching

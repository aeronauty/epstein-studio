"""
Leakage detection for partial letterforms at redaction borders.

Analyzes pixels at the top and bottom edges of redaction bars to detect
ascender leakage (tops of letters like b, d, f, h, k, l, t) and
descender leakage (bottoms of letters like g, j, p, q, y).
"""

import cv2
import numpy as np
from dataclasses import dataclass
from typing import Optional


@dataclass
class LeakageResult:
    """Result of leakage analysis."""
    has_ascender_leakage: bool
    has_descender_leakage: bool
    leakage_pixels_top: int
    leakage_pixels_bottom: int
    top_edge_variance: float
    bottom_edge_variance: float


def extract_edge_band(
    image: np.ndarray,
    bbox_pixels: tuple[int, int, int, int],
    edge: str,
    band_height: int = 5
) -> Optional[np.ndarray]:
    """
    Extract a band of pixels at the edge of a redaction.
    
    Args:
        image: Page image (grayscale or BGR)
        bbox_pixels: (x0, y0, x1, y1) in pixel coordinates
        edge: "top" or "bottom"
        band_height: Height of the band to extract
        
    Returns:
        numpy array of the edge band, or None if out of bounds
    """
    x0, y0, x1, y1 = bbox_pixels
    img_height, img_width = image.shape[:2]
    
    # Ensure coordinates are valid
    x0 = max(0, x0)
    x1 = min(img_width, x1)
    y0 = max(0, y0)
    y1 = min(img_height, y1)
    
    if x1 <= x0 or y1 <= y0:
        return None
    
    if edge == "top":
        # Band above the redaction
        band_y0 = max(0, y0 - band_height)
        band_y1 = y0
    else:  # bottom
        # Band below the redaction
        band_y0 = y1
        band_y1 = min(img_height, y1 + band_height)
    
    if band_y1 <= band_y0:
        return None
    
    return image[band_y0:band_y1, x0:x1]


def analyze_edge_band(
    band: np.ndarray,
    background_threshold: int = 240,
    dark_threshold: int = 50
) -> tuple[int, float]:
    """
    Analyze an edge band for non-background pixels.
    
    Looks for pixels that are neither pure black (part of redaction)
    nor pure white (background), which could indicate letterforms.
    
    Args:
        band: Edge band image (grayscale)
        background_threshold: Pixels above this are considered background
        dark_threshold: Pixels below this are considered redaction
        
    Returns:
        Tuple of (non_background_pixels, variance)
    """
    if band is None or band.size == 0:
        return (0, 0.0)
    
    # Convert to grayscale if needed
    if len(band.shape) == 3:
        band = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    
    # Count pixels that are neither black nor white
    # These are potential letterforms
    mask = (band > dark_threshold) & (band < background_threshold)
    non_bg_pixels = np.sum(mask)
    
    # Calculate variance in the band (high variance = possible text)
    variance = float(np.var(band))
    
    return (int(non_bg_pixels), variance)


def detect_vertical_strokes(
    band: np.ndarray,
    min_stroke_height: int = 2
) -> int:
    """
    Detect vertical strokes in an edge band (potential letter stems).
    
    Args:
        band: Edge band image (grayscale)
        min_stroke_height: Minimum height for a stroke
        
    Returns:
        Number of detected vertical strokes
    """
    if band is None or band.size == 0:
        return 0
    
    # Convert to grayscale if needed
    if len(band.shape) == 3:
        band = cv2.cvtColor(band, cv2.COLOR_BGR2GRAY)
    
    # Threshold to binary
    _, binary = cv2.threshold(band, 128, 255, cv2.THRESH_BINARY_INV)
    
    # Look for vertical connected components
    # Apply vertical morphological operation to emphasize vertical strokes
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, min_stroke_height))
    vertical = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    
    # Count connected components
    num_labels, _ = cv2.connectedComponents(vertical)
    
    # Subtract 1 for background
    return max(0, num_labels - 1)


def analyze_leakage(
    page_image: np.ndarray,
    bbox_pixels: tuple[int, int, int, int],
    edge_band: int = 5,
    min_leakage_pixels: int = 10,
    min_variance: float = 100.0
) -> LeakageResult:
    """
    Analyze a redaction for letterform leakage at borders.
    
    Checks both top edge (for ascenders) and bottom edge (for descenders).
    
    Args:
        page_image: Page rendered as numpy array
        bbox_pixels: (x0, y0, x1, y1) in pixel coordinates
        edge_band: Height of edge band to analyze
        min_leakage_pixels: Minimum non-background pixels to flag as leakage
        min_variance: Minimum variance to flag as leakage
        
    Returns:
        LeakageResult with analysis
    """
    # Convert to grayscale for analysis
    if len(page_image.shape) == 3:
        gray = cv2.cvtColor(page_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = page_image
    
    # Extract edge bands
    top_band = extract_edge_band(gray, bbox_pixels, "top", edge_band)
    bottom_band = extract_edge_band(gray, bbox_pixels, "bottom", edge_band)
    
    # Analyze top edge (ascender detection)
    top_pixels, top_variance = analyze_edge_band(top_band)
    top_strokes = detect_vertical_strokes(top_band) if top_band is not None else 0
    
    # Analyze bottom edge (descender detection)
    bottom_pixels, bottom_variance = analyze_edge_band(bottom_band)
    bottom_strokes = detect_vertical_strokes(bottom_band) if bottom_band is not None else 0
    
    # Determine if there's significant leakage
    # Consider both pixel count and variance
    has_ascender = (
        top_pixels >= min_leakage_pixels or 
        top_variance >= min_variance or
        top_strokes >= 2
    )
    
    has_descender = (
        bottom_pixels >= min_leakage_pixels or 
        bottom_variance >= min_variance or
        bottom_strokes >= 2
    )
    
    return LeakageResult(
        has_ascender_leakage=has_ascender,
        has_descender_leakage=has_descender,
        leakage_pixels_top=top_pixels,
        leakage_pixels_bottom=bottom_pixels,
        top_edge_variance=top_variance,
        bottom_edge_variance=bottom_variance
    )


def analyze_leakage_detailed(
    page_image: np.ndarray,
    bbox_pixels: tuple[int, int, int, int],
    edge_band: int = 5
) -> dict:
    """
    Perform detailed leakage analysis with additional metrics.
    
    Useful for debugging and calibration.
    
    Args:
        page_image: Page rendered as numpy array
        bbox_pixels: (x0, y0, x1, y1) in pixel coordinates
        edge_band: Height of edge band to analyze
        
    Returns:
        Dictionary with detailed analysis metrics
    """
    # Convert to grayscale
    if len(page_image.shape) == 3:
        gray = cv2.cvtColor(page_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = page_image
    
    # Extract edge bands
    top_band = extract_edge_band(gray, bbox_pixels, "top", edge_band)
    bottom_band = extract_edge_band(gray, bbox_pixels, "bottom", edge_band)
    
    result = {
        "bbox_pixels": bbox_pixels,
        "edge_band_height": edge_band,
    }
    
    # Analyze top band
    if top_band is not None and top_band.size > 0:
        result["top"] = {
            "size": top_band.shape,
            "mean": float(np.mean(top_band)),
            "std": float(np.std(top_band)),
            "min": int(np.min(top_band)),
            "max": int(np.max(top_band)),
            "non_bg_pixels": analyze_edge_band(top_band)[0],
            "variance": analyze_edge_band(top_band)[1],
            "vertical_strokes": detect_vertical_strokes(top_band),
        }
    else:
        result["top"] = None
    
    # Analyze bottom band
    if bottom_band is not None and bottom_band.size > 0:
        result["bottom"] = {
            "size": bottom_band.shape,
            "mean": float(np.mean(bottom_band)),
            "std": float(np.std(bottom_band)),
            "min": int(np.min(bottom_band)),
            "max": int(np.max(bottom_band)),
            "non_bg_pixels": analyze_edge_band(bottom_band)[0],
            "variance": analyze_edge_band(bottom_band)[1],
            "vertical_strokes": detect_vertical_strokes(bottom_band),
        }
    else:
        result["bottom"] = None
    
    return result

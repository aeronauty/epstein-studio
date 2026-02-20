"""
OpenCV-based pixel-level redaction detection.

Detects black/dark bars in rendered PDF pages using image processing:
1. Convert to grayscale
2. Threshold for dark pixels
3. Find contours
4. Filter by aspect ratio and area
"""

import cv2
import numpy as np
from typing import Optional

from .models import RawDetection, DetectionMethod


def render_page_to_image(page, dpi: int = 150) -> np.ndarray:
    """
    Render a PyMuPDF page to a numpy array (BGR format for OpenCV).
    
    Args:
        page: PyMuPDF page object
        dpi: Resolution for rendering
        
    Returns:
        numpy array in BGR format
    """
    # Calculate zoom factor from DPI (PyMuPDF default is 72 DPI)
    zoom = dpi / 72.0
    mat = __import__('fitz').Matrix(zoom, zoom)
    
    # Render page to pixmap
    pix = page.get_pixmap(matrix=mat, alpha=False)
    
    # Convert to numpy array
    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(
        pix.height, pix.width, pix.n
    )
    
    # Convert RGB to BGR for OpenCV
    if pix.n == 3:
        img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    elif pix.n == 4:
        img = cv2.cvtColor(img, cv2.COLOR_RGBA2BGR)
    
    return img


def detect_dark_regions(
    image: np.ndarray,
    threshold: int = 30
) -> np.ndarray:
    """
    Create a binary mask of dark regions in the image.
    
    Args:
        image: Input image (BGR or grayscale)
        threshold: Pixel values below this are considered dark (0-255)
        
    Returns:
        Binary mask where white (255) indicates dark regions
    """
    # Convert to grayscale if needed
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    # Threshold: pixels below threshold become white in mask
    _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY_INV)
    
    # Apply morphological operations to clean up noise
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    
    return mask


def find_rectangular_contours(
    mask: np.ndarray,
    min_aspect_ratio: float = 3.0,
    min_area: int = 500,
    max_area: Optional[int] = None
) -> list[tuple[int, int, int, int]]:
    """
    Find rectangular contours that match redaction bar characteristics.
    
    Args:
        mask: Binary mask of dark regions
        min_aspect_ratio: Minimum width/height ratio
        min_area: Minimum contour area in pixels
        max_area: Maximum contour area in pixels (None for no limit)
        
    Returns:
        List of bounding boxes as (x, y, width, height)
    """
    # Find contours
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    rectangles = []
    
    for contour in contours:
        # Get bounding rectangle
        x, y, w, h = cv2.boundingRect(contour)
        area = w * h
        
        # Filter by area
        if area < min_area:
            continue
        if max_area is not None and area > max_area:
            continue
        
        # Filter by aspect ratio (redaction bars are wide and short)
        if h == 0:
            continue
        aspect_ratio = w / h
        
        if aspect_ratio < min_aspect_ratio:
            continue
        
        # Additional check: the contour should fill most of its bounding box
        # (redactions are solid rectangles, not sparse shapes)
        contour_area = cv2.contourArea(contour)
        fill_ratio = contour_area / area if area > 0 else 0
        
        if fill_ratio < 0.7:  # At least 70% filled
            continue
        
        rectangles.append((x, y, w, h))
    
    return rectangles


def pixels_to_points(
    bbox_pixels: tuple[int, int, int, int],
    page_height_pixels: int,
    dpi: int
) -> tuple[float, float, float, float]:
    """
    Convert pixel coordinates to PyMuPDF points.
    
    Both PyMuPDF and pixel coordinates use top-left origin with Y
    increasing downward, so no Y-flip is needed -- only a scale.
    
    Args:
        bbox_pixels: (x, y, width, height) in pixels, origin top-left
        page_height_pixels: Total page height in pixels (unused, kept for API compat)
        dpi: Render DPI used
        
    Returns:
        (x0, y0, x1, y1) in PyMuPDF points, origin top-left
    """
    x, y, w, h = bbox_pixels
    scale = 72.0 / dpi  # Convert pixels to points
    
    x0 = x * scale
    y0 = y * scale
    x1 = (x + w) * scale
    y1 = (y + h) * scale
    
    return (x0, y0, x1, y1)


def points_to_pixels(
    bbox_points: tuple[float, float, float, float],
    page_height_points: float,
    dpi: int
) -> tuple[int, int, int, int]:
    """
    Convert PyMuPDF points to pixel coordinates.
    
    Both coordinate systems use top-left origin, so no Y-flip is needed.
    
    Args:
        bbox_points: (x0, y0, x1, y1) in PyMuPDF points, origin top-left
        page_height_points: Total page height in points (unused, kept for API compat)
        dpi: Render DPI to use
        
    Returns:
        (x0, y0, x1, y1) in pixels, origin top-left
    """
    x0, y0, x1, y1 = bbox_points
    scale = dpi / 72.0  # Convert points to pixels
    
    px0 = int(x0 * scale)
    py0 = int(y0 * scale)
    px1 = int(x1 * scale)
    py1 = int(y1 * scale)
    
    return (px0, py0, px1, py1)


def detect_pixel_redactions(
    page_image: np.ndarray,
    page_height_pixels: int,
    dpi: int = 150,
    threshold: int = 30,
    min_aspect_ratio: float = 3.0,
    min_area: int = 500
) -> list[RawDetection]:
    """
    Detect redaction bars in a page image using pixel analysis.
    
    Args:
        page_image: Page rendered as numpy array (BGR)
        page_height_pixels: Height of the page image
        dpi: DPI used for rendering
        threshold: Darkness threshold (0-255)
        min_aspect_ratio: Minimum width/height ratio for bars
        min_area: Minimum area in pixels
        
    Returns:
        List of raw detections with coordinates in PDF points
    """
    # Create mask of dark regions
    mask = detect_dark_regions(page_image, threshold)
    
    # Find rectangular contours
    rectangles = find_rectangular_contours(
        mask,
        min_aspect_ratio=min_aspect_ratio,
        min_area=min_area
    )
    
    # Convert to RawDetection objects
    detections = []
    for rect in rectangles:
        # Convert pixel coords to PDF points
        bbox_points = pixels_to_points(rect, page_height_pixels, dpi)
        
        # Calculate confidence based on how "perfect" the rectangle is
        x, y, w, h = rect
        aspect = w / h if h > 0 else 0
        
        # Higher aspect ratio = higher confidence (more bar-like)
        confidence = min(0.95, 0.7 + (aspect / 20.0))
        
        detections.append(RawDetection(
            bbox=bbox_points,
            method=DetectionMethod.OPENCV,
            confidence=confidence,
            annotation_type=None
        ))
    
    return detections


def calibrate_threshold(
    page_image: np.ndarray,
    sample_regions: int = 100
) -> dict:
    """
    Analyze page to help calibrate threshold parameter.
    
    Returns statistics about dark pixel values in the image.
    
    Args:
        page_image: Page rendered as numpy array (BGR)
        sample_regions: Number of sample points to analyze
        
    Returns:
        Dictionary with calibration statistics
    """
    # Convert to grayscale
    if len(page_image.shape) == 3:
        gray = cv2.cvtColor(page_image, cv2.COLOR_BGR2GRAY)
    else:
        gray = page_image
    
    # Get histogram of dark pixels (0-50 range)
    hist = cv2.calcHist([gray], [0], None, [51], [0, 51])
    hist = hist.flatten()
    
    # Find peaks in the histogram
    total_dark = np.sum(hist)
    
    # Statistics
    stats = {
        "dark_pixel_count": int(total_dark),
        "dark_pixel_ratio": float(total_dark / gray.size),
        "histogram_0_10": int(np.sum(hist[0:11])),
        "histogram_11_20": int(np.sum(hist[11:21])),
        "histogram_21_30": int(np.sum(hist[21:31])),
        "histogram_31_40": int(np.sum(hist[31:41])),
        "histogram_41_50": int(np.sum(hist[41:51])),
    }
    
    # Suggest threshold based on histogram
    cumsum = np.cumsum(hist)
    for i, val in enumerate(cumsum):
        if val > total_dark * 0.9:  # 90% of dark pixels
            stats["suggested_threshold"] = i
            break
    else:
        stats["suggested_threshold"] = 30
    
    return stats

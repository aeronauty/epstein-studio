"""
Detection merger for cross-referencing PyMuPDF and OpenCV results.

Merges detections from both methods:
- Matches detections with high IoU (Intersection over Union)
- Detections found by both methods get higher confidence
- Unique detections from either method are kept
- Deduplicates overlapping boxes
"""

from typing import Optional

from .models import RawDetection, MergedDetection, DetectionMethod


def calculate_iou(
    bbox1: tuple[float, float, float, float],
    bbox2: tuple[float, float, float, float]
) -> float:
    """
    Calculate Intersection over Union (IoU) between two bounding boxes.
    
    Args:
        bbox1: (x0, y0, x1, y1) first bounding box
        bbox2: (x0, y0, x1, y1) second bounding box
        
    Returns:
        IoU value between 0 and 1
    """
    # Get intersection coordinates
    x0 = max(bbox1[0], bbox2[0])
    y0 = max(bbox1[1], bbox2[1])
    x1 = min(bbox1[2], bbox2[2])
    y1 = min(bbox1[3], bbox2[3])
    
    # Check for no intersection
    if x1 <= x0 or y1 <= y0:
        return 0.0
    
    # Calculate areas
    intersection = (x1 - x0) * (y1 - y0)
    area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
    area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
    union = area1 + area2 - intersection
    
    if union <= 0:
        return 0.0
    
    return intersection / union


def merge_bboxes(
    bbox1: tuple[float, float, float, float],
    bbox2: tuple[float, float, float, float]
) -> tuple[float, float, float, float]:
    """
    Merge two bounding boxes by taking their union.
    
    Args:
        bbox1: (x0, y0, x1, y1) first bounding box
        bbox2: (x0, y0, x1, y1) second bounding box
        
    Returns:
        Merged bounding box
    """
    return (
        min(bbox1[0], bbox2[0]),
        min(bbox1[1], bbox2[1]),
        max(bbox1[2], bbox2[2]),
        max(bbox1[3], bbox2[3])
    )


def find_best_match(
    detection: RawDetection,
    candidates: list[RawDetection],
    iou_threshold: float = 0.7
) -> Optional[tuple[int, float]]:
    """
    Find the best matching detection from a list of candidates.
    
    Args:
        detection: Detection to match
        candidates: List of candidate detections
        iou_threshold: Minimum IoU to consider a match
        
    Returns:
        Tuple of (index, iou) for best match, or None if no match
    """
    best_idx = None
    best_iou = 0.0
    
    for i, candidate in enumerate(candidates):
        iou = calculate_iou(detection.bbox, candidate.bbox)
        if iou > best_iou and iou >= iou_threshold:
            best_iou = iou
            best_idx = i
    
    if best_idx is not None:
        return (best_idx, best_iou)
    return None


def merge_detections(
    pdf_detections: list[RawDetection],
    pixel_detections: list[RawDetection],
    iou_threshold: float = 0.7
) -> list[MergedDetection]:
    """
    Cross-reference and merge detections from both methods.
    
    Algorithm:
    1. For each PyMuPDF detection, find matching OpenCV detection
    2. Matched pairs become "both" method with boosted confidence
    3. Unmatched detections are kept with original confidence
    4. Final deduplication pass for remaining overlaps
    
    Args:
        pdf_detections: Detections from PyMuPDF extraction
        pixel_detections: Detections from OpenCV pixel analysis
        iou_threshold: Minimum IoU for matching
        
    Returns:
        List of merged detections
    """
    merged = []
    used_pixel_indices = set()
    
    # Match PyMuPDF detections with OpenCV detections
    for pdf_det in pdf_detections:
        match = find_best_match(pdf_det, pixel_detections, iou_threshold)
        
        if match is not None:
            idx, iou = match
            pixel_det = pixel_detections[idx]
            used_pixel_indices.add(idx)
            
            # Merge the bounding boxes
            merged_bbox = merge_bboxes(pdf_det.bbox, pixel_det.bbox)
            
            # Boost confidence for detections found by both methods
            # Base confidence is average of both, plus bonus for agreement
            base_confidence = (pdf_det.confidence + pixel_det.confidence) / 2
            agreement_bonus = 0.1 * iou  # More bonus for higher IoU
            confidence = min(1.0, base_confidence + agreement_bonus)
            
            merged.append(MergedDetection(
                bbox=merged_bbox,
                method=DetectionMethod.BOTH,
                confidence=confidence,
                pymupdf_match=pdf_det,
                opencv_match=pixel_det
            ))
        else:
            # No match - keep PyMuPDF detection alone
            merged.append(MergedDetection(
                bbox=pdf_det.bbox,
                method=DetectionMethod.PYMUPDF,
                confidence=pdf_det.confidence,
                pymupdf_match=pdf_det,
                opencv_match=None
            ))
    
    # Add unmatched OpenCV detections
    for i, pixel_det in enumerate(pixel_detections):
        if i not in used_pixel_indices:
            merged.append(MergedDetection(
                bbox=pixel_det.bbox,
                method=DetectionMethod.OPENCV,
                confidence=pixel_det.confidence,
                pymupdf_match=None,
                opencv_match=pixel_det
            ))
    
    # Deduplicate any remaining overlapping boxes
    merged = deduplicate_overlaps(merged, iou_threshold)
    
    return merged


def deduplicate_overlaps(
    detections: list[MergedDetection],
    iou_threshold: float = 0.7
) -> list[MergedDetection]:
    """
    Remove duplicate detections that overlap significantly.
    
    When two detections overlap, keep the one with higher confidence.
    
    Args:
        detections: List of merged detections
        iou_threshold: IoU threshold for considering duplicates
        
    Returns:
        Deduplicated list of detections
    """
    if len(detections) <= 1:
        return detections
    
    # Sort by confidence (highest first)
    sorted_dets = sorted(detections, key=lambda d: d.confidence, reverse=True)
    
    keep = []
    for det in sorted_dets:
        # Check if this detection overlaps with any kept detection
        is_duplicate = False
        for kept_det in keep:
            iou = calculate_iou(det.bbox, kept_det.bbox)
            if iou >= iou_threshold:
                is_duplicate = True
                break
        
        if not is_duplicate:
            keep.append(det)
    
    return keep


def non_max_suppression(
    detections: list[MergedDetection],
    iou_threshold: float = 0.5
) -> list[MergedDetection]:
    """
    Apply non-maximum suppression to remove overlapping detections.
    
    More aggressive than deduplicate_overlaps, using lower IoU threshold.
    Useful for cleanup when many similar detections exist.
    
    Args:
        detections: List of merged detections
        iou_threshold: IoU threshold for suppression
        
    Returns:
        Filtered list of detections
    """
    if len(detections) == 0:
        return []
    
    # Sort by confidence (highest first)
    sorted_dets = sorted(detections, key=lambda d: d.confidence, reverse=True)
    
    keep = []
    for det in sorted_dets:
        # Check overlap with all kept detections
        should_keep = True
        for kept in keep:
            iou = calculate_iou(det.bbox, kept.bbox)
            if iou > iou_threshold:
                should_keep = False
                break
        
        if should_keep:
            keep.append(det)
    
    return keep


def filter_by_confidence(
    detections: list[MergedDetection],
    min_confidence: float = 0.5
) -> list[MergedDetection]:
    """
    Filter detections by minimum confidence threshold.
    
    Args:
        detections: List of merged detections
        min_confidence: Minimum confidence to keep
        
    Returns:
        Filtered list of detections
    """
    return [d for d in detections if d.confidence >= min_confidence]

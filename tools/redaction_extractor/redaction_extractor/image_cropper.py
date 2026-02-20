"""
Image extraction for redaction crops.

Extracts two types of crops for each redaction:
1. Tight crop: Exact bounding box of the redaction
2. Context crop: Bounding box expanded with padding for surrounding context
"""

import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Tuple
from PIL import Image


def crop_region(
    image: np.ndarray,
    bbox: Tuple[int, int, int, int],
    padding: int = 0
) -> Optional[np.ndarray]:
    """
    Crop a region from an image.
    
    Args:
        image: Source image as numpy array
        bbox: (x0, y0, x1, y1) in pixel coordinates
        padding: Extra pixels to include around the bbox
        
    Returns:
        Cropped image region, or None if bbox is invalid
    """
    img_height, img_width = image.shape[:2]
    x0, y0, x1, y1 = bbox
    
    # Apply padding
    x0 = max(0, x0 - padding)
    y0 = max(0, y0 - padding)
    x1 = min(img_width, x1 + padding)
    y1 = min(img_height, y1 + padding)
    
    # Validate coordinates after clamping
    if x1 <= x0 or y1 <= y0:
        return None
    
    crop = image[y0:y1, x0:x1].copy()
    
    # Guard against degenerate crops (zero-dimension after slicing)
    if crop.size == 0 or crop.shape[0] == 0 or crop.shape[1] == 0:
        return None
    
    return crop


def crop_redaction_images(
    page_image: np.ndarray,
    bbox_pixels: Tuple[int, int, int, int],
    border_padding: int = 50
) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
    """
    Extract tight and context crops for a redaction.
    
    Args:
        page_image: Page rendered as numpy array
        bbox_pixels: (x0, y0, x1, y1) in pixel coordinates
        border_padding: Padding for context crop in pixels
        
    Returns:
        Tuple of (tight_crop, context_crop) as numpy arrays
    """
    # Tight crop: exact bounding box
    tight = crop_region(page_image, bbox_pixels, padding=0)
    
    # Context crop: expanded bounding box
    context = crop_region(page_image, bbox_pixels, padding=border_padding)
    
    return (tight, context)


def save_crop(
    crop: np.ndarray,
    output_path: Path,
    format: str = "PNG"
) -> bool:
    """
    Save a crop to disk.
    
    Args:
        crop: Image array to save
        output_path: Path to save to
        format: Image format (PNG, JPEG, etc.)
        
    Returns:
        True if successful, False otherwise
    """
    try:
        # Ensure parent directory exists
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Convert BGR to RGB if needed (OpenCV uses BGR)
        if len(crop.shape) == 3 and crop.shape[2] == 3:
            crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        else:
            crop_rgb = crop
        
        # Save using PIL for better format support
        img = Image.fromarray(crop_rgb)
        img.save(str(output_path), format=format)
        
        return True
    except Exception:
        return False


def generate_crop_filename(
    doc_id: str,
    page_num: int,
    redaction_index: int,
    crop_type: str
) -> str:
    """
    Generate a standardized filename for a crop.
    
    Args:
        doc_id: Document identifier
        page_num: Page number (1-indexed)
        redaction_index: Redaction index on the page (0-indexed)
        crop_type: "tight" or "context"
        
    Returns:
        Filename string
    """
    # Sanitize doc_id for filesystem
    safe_doc_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in doc_id)
    
    return f"{safe_doc_id}_p{page_num}_r{redaction_index}_{crop_type}.png"


def extract_and_save_crops(
    page_image: np.ndarray,
    bbox_pixels: Tuple[int, int, int, int],
    doc_id: str,
    page_num: int,
    redaction_index: int,
    output_dir: Path,
    border_padding: int = 50
) -> Tuple[str, str]:
    """
    Extract crops and save them to disk.
    
    Args:
        page_image: Page rendered as numpy array
        bbox_pixels: (x0, y0, x1, y1) in pixel coordinates
        doc_id: Document identifier
        page_num: Page number (1-indexed)
        redaction_index: Redaction index on the page
        output_dir: Base output directory
        border_padding: Padding for context crop
        
    Returns:
        Tuple of (tight_path, context_path) relative to output_dir
    """
    # Create images subdirectory
    images_dir = output_dir / "images"
    images_dir.mkdir(parents=True, exist_ok=True)
    
    # Extract crops
    tight, context = crop_redaction_images(page_image, bbox_pixels, border_padding)
    
    # Generate filenames
    tight_filename = generate_crop_filename(doc_id, page_num, redaction_index, "tight")
    context_filename = generate_crop_filename(doc_id, page_num, redaction_index, "context")
    
    tight_path = images_dir / tight_filename
    context_path = images_dir / context_filename
    
    # Save crops
    tight_saved = False
    context_saved = False
    
    if tight is not None and tight.size > 0:
        tight_saved = save_crop(tight, tight_path)
    
    if context is not None and context.size > 0:
        context_saved = save_crop(context, context_path)
    
    # Return relative paths
    tight_rel = f"images/{tight_filename}" if tight_saved else ""
    context_rel = f"images/{context_filename}" if context_saved else ""
    
    return (tight_rel, context_rel)


def create_composite_image(
    crops: list[np.ndarray],
    max_width: int = 1000,
    padding: int = 10,
    background_color: Tuple[int, int, int] = (255, 255, 255)
) -> Optional[np.ndarray]:
    """
    Create a composite image from multiple crops.
    
    Useful for visualizing all redactions from a document or page.
    
    Args:
        crops: List of crop images
        max_width: Maximum width of composite
        padding: Padding between crops
        background_color: Background color (RGB)
        
    Returns:
        Composite image as numpy array
    """
    if not crops:
        return None
    
    # Filter out None and empty crops
    valid_crops = [c for c in crops if c is not None and c.size > 0]
    if not valid_crops:
        return None
    
    # Calculate layout
    current_x = padding
    current_y = padding
    row_height = 0
    positions = []
    
    for crop in valid_crops:
        h, w = crop.shape[:2]
        
        # Check if we need a new row
        if current_x + w + padding > max_width and current_x > padding:
            current_x = padding
            current_y += row_height + padding
            row_height = 0
        
        positions.append((current_x, current_y, w, h))
        current_x += w + padding
        row_height = max(row_height, h)
    
    # Calculate total size
    total_width = max(pos[0] + pos[2] for pos in positions) + padding
    total_height = max(pos[1] + pos[3] for pos in positions) + padding
    
    # Create composite
    composite = np.full(
        (total_height, total_width, 3),
        background_color,
        dtype=np.uint8
    )
    
    # Place crops
    for crop, (x, y, w, h) in zip(valid_crops, positions):
        # Ensure crop is 3-channel
        if len(crop.shape) == 2:
            crop = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
        elif crop.shape[2] == 4:
            crop = cv2.cvtColor(crop, cv2.COLOR_BGRA2BGR)
        
        composite[y:y+h, x:x+w] = crop
    
    return composite


def get_crop_stats(crops: list[np.ndarray]) -> dict:
    """
    Calculate statistics about a list of crops.
    
    Args:
        crops: List of crop images
        
    Returns:
        Dictionary with crop statistics
    """
    valid = [c for c in crops if c is not None and c.size > 0]
    
    if not valid:
        return {
            "total_crops": 0,
            "avg_width": 0,
            "avg_height": 0,
            "min_width": 0,
            "max_width": 0,
            "min_height": 0,
            "max_height": 0,
        }
    
    widths = [c.shape[1] for c in valid]
    heights = [c.shape[0] for c in valid]
    
    return {
        "total_crops": len(valid),
        "avg_width": sum(widths) / len(widths),
        "avg_height": sum(heights) / len(heights),
        "min_width": min(widths),
        "max_width": max(widths),
        "min_height": min(heights),
        "max_height": max(heights),
    }

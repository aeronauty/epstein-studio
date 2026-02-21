"""
Multi-line redaction detection and merging.

Detects when a redaction continues across a line break and groups
these into single logical entities. A multi-line redaction is detected
when:
1. A redaction bar ends near the right margin
2. The next redaction bar starts near the left margin
3. They appear on consecutive lines (similar vertical spacing)
"""

import uuid
from typing import Optional
from dataclasses import dataclass

from .models import Redaction


@dataclass
class MultilineGroup:
    """A group of redactions that form a single multi-line redaction."""
    group_id: str
    redactions: list[Redaction]
    
    @property
    def total_estimated_chars(self) -> int:
        return sum(r.estimated_chars for r in self.redactions)


def estimate_line_height(redactions: list[Redaction]) -> float:
    """
    Estimate typical line height from a list of redactions.
    
    Uses the heights of the redaction bars as a proxy for line height.
    
    Args:
        redactions: List of redactions to analyze
        
    Returns:
        Estimated line height in points
    """
    if not redactions:
        return 14.0  # Default line height
    
    heights = [r.height_points for r in redactions]
    
    # Use median height, scaled up slightly (bars are usually shorter than line)
    heights.sort()
    median_idx = len(heights) // 2
    median_height = heights[median_idx]
    
    # Line height is typically 1.2-1.5x the text/bar height
    return median_height * 1.3


def is_at_right_margin(
    redaction: Redaction,
    page_width: float,
    margin_threshold: float = 50.0
) -> bool:
    """
    Check if a redaction ends near the right margin.
    
    Args:
        redaction: Redaction to check
        page_width: Width of the page in points
        margin_threshold: Maximum distance from margin in points
        
    Returns:
        True if redaction ends near right margin
    """
    right_edge = redaction.bbox_points[2]  # x1
    distance_from_right = page_width - right_edge
    return distance_from_right <= margin_threshold


def is_at_left_margin(
    redaction: Redaction,
    left_margin: float = 50.0,
    margin_threshold: float = 50.0
) -> bool:
    """
    Check if a redaction starts near the left margin.
    
    Args:
        redaction: Redaction to check
        left_margin: Typical left margin in points
        margin_threshold: Maximum distance from margin in points
        
    Returns:
        True if redaction starts near left margin
    """
    left_edge = redaction.bbox_points[0]  # x0
    return left_edge <= left_margin + margin_threshold


def is_on_next_line(
    redaction1: Redaction,
    redaction2: Redaction,
    line_height: float,
    tolerance: float = 5.0
) -> bool:
    """
    Check if redaction2 is on the line immediately below redaction1.
    
    Args:
        redaction1: First redaction (should be above)
        redaction2: Second redaction (should be below)
        line_height: Expected line height in points
        tolerance: Tolerance for line height matching in points
        
    Returns:
        True if redaction2 is on the next line
    """
    # Get vertical positions (PDF coordinates: y increases upward)
    y1_bottom = redaction1.bbox_points[1]  # y0 of first redaction
    y2_top = redaction2.bbox_points[3]     # y1 of second redaction
    
    # The gap between them should be approximately one line height
    # (or close to zero if tightly spaced)
    vertical_gap = y1_bottom - y2_top
    
    # Check if the gap is reasonable for line spacing
    # Gap should be between 0 and 2x line height
    if vertical_gap < -tolerance:  # redaction2 is above redaction1
        return False
    if vertical_gap > line_height * 2:  # Too far apart
        return False
    
    return True


def find_multiline_groups(
    redactions: list[Redaction],
    page_width: float,
    margin_threshold: float = 50.0,
    line_height_tolerance: float = 5.0
) -> list[MultilineGroup]:
    """
    Find groups of redactions that form multi-line redactions.
    
    Args:
        redactions: List of redactions on a page
        page_width: Width of the page in points
        margin_threshold: Distance from margin to consider "at margin"
        line_height_tolerance: Tolerance for line height matching
        
    Returns:
        List of MultilineGroup objects
    """
    if len(redactions) < 2:
        return []
    
    # Sort redactions by vertical position (top to bottom in reading order)
    # PDF coordinates have y increasing upward, so sort by -y1 (descending y1)
    sorted_redactions = sorted(
        redactions,
        key=lambda r: (-r.bbox_points[3], r.bbox_points[0])  # -y1, x0
    )
    
    # Estimate line height
    line_height = estimate_line_height(redactions)
    
    # Find groups
    groups = []
    used_indices = set()
    
    for i, redaction in enumerate(sorted_redactions):
        if i in used_indices:
            continue
        
        # Check if this redaction ends at right margin
        if not is_at_right_margin(redaction, page_width, margin_threshold):
            continue
        
        # Look for continuation on next line
        group_members = [redaction]
        current = redaction
        
        for j in range(i + 1, len(sorted_redactions)):
            if j in used_indices:
                continue
            
            next_red = sorted_redactions[j]
            
            # Check if next redaction starts at left margin
            if not is_at_left_margin(next_red, margin_threshold=margin_threshold):
                continue
            
            # Check if it's on the next line
            if not is_on_next_line(current, next_red, line_height, line_height_tolerance):
                continue
            
            # Found a continuation
            group_members.append(next_red)
            used_indices.add(j)
            
            # Check if this one also ends at right margin (could continue further)
            if is_at_right_margin(next_red, page_width, margin_threshold):
                current = next_red
            else:
                break  # End of multi-line group
        
        # Only create a group if we found continuations
        if len(group_members) > 1:
            used_indices.add(i)
            groups.append(MultilineGroup(
                group_id=str(uuid.uuid4())[:8],
                redactions=group_members
            ))
    
    return groups


def merge_multiline_redactions(
    redactions: list[Redaction],
    page_width: float,
    margin_threshold: float = 50.0,
    line_height_tolerance: float = 5.0
) -> list[Redaction]:
    """
    Update redactions with multi-line grouping information.
    
    Modifies the redactions in place to set:
    - is_multiline: True for redactions part of a group
    - multiline_group_id: Unique ID for the group
    - line_index_in_group: Position within the group (0-indexed)
    
    Args:
        redactions: List of redactions to process
        page_width: Width of the page in points
        margin_threshold: Distance from margin to consider "at margin"
        line_height_tolerance: Tolerance for line height matching
        
    Returns:
        The same list of redactions with multi-line info updated
    """
    # Find groups
    groups = find_multiline_groups(
        redactions,
        page_width,
        margin_threshold,
        line_height_tolerance
    )
    
    # Create a map of redaction to group info
    redaction_to_group = {}
    for group in groups:
        for i, red in enumerate(group.redactions):
            # Use bbox as key (tuples are hashable)
            key = red.bbox_points
            redaction_to_group[key] = (group.group_id, i, len(group.redactions))
    
    # Update redactions
    for redaction in redactions:
        key = redaction.bbox_points
        if key in redaction_to_group:
            group_id, line_idx, total_lines = redaction_to_group[key]
            redaction.is_multiline = True
            redaction.multiline_group_id = group_id
            redaction.line_index_in_group = line_idx
    
    return redactions


def get_multiline_stats(redactions: list[Redaction]) -> dict:
    """
    Get statistics about multi-line redactions.
    
    Args:
        redactions: List of redactions to analyze
        
    Returns:
        Dictionary with multi-line statistics
    """
    multiline = [r for r in redactions if r.is_multiline]
    
    if not multiline:
        return {
            "total_multiline_redactions": 0,
            "total_multiline_groups": 0,
            "avg_lines_per_group": 0,
            "max_lines_in_group": 0,
        }
    
    # Count unique groups
    groups = {}
    for r in multiline:
        if r.multiline_group_id:
            if r.multiline_group_id not in groups:
                groups[r.multiline_group_id] = []
            groups[r.multiline_group_id].append(r)
    
    lines_per_group = [len(g) for g in groups.values()]
    
    return {
        "total_multiline_redactions": len(multiline),
        "total_multiline_groups": len(groups),
        "avg_lines_per_group": sum(lines_per_group) / len(lines_per_group) if lines_per_group else 0,
        "max_lines_in_group": max(lines_per_group) if lines_per_group else 0,
    }

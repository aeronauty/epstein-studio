import hashlib
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, JsonResponse
from django.shortcuts import render
from django.db.models import Q
from django.db.utils import OperationalError, ProgrammingError

from .models import (
    PdfDocument,
    ExtractionRun,
    ExtractedDocument,
    RedactionRecord,
)


def start_page(request):
    """Landing page with basic stats."""
    try:
        total_pdfs = PdfDocument.objects.count()
        total_redactions = RedactionRecord.objects.count()
    except (OperationalError, ProgrammingError):
        total_pdfs = 0
        total_redactions = 0

    return render(request, "epstein_ui/start.html", {
        "total_pdfs": total_pdfs,
        "total_redactions": total_redactions,
    })


# ---------------------------------------------------------------------------
# Redaction demo views
# ---------------------------------------------------------------------------

def redactions_demo(request):
    """Render the redaction demo browse page."""
    total = RedactionRecord.objects.count()
    return render(request, "epstein_ui/redactions_demo.html", {"total_redactions": total})


def redactions_list(request):
    """Return paginated redaction records as JSON."""
    try:
        page_num = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page_num = 1
    page_size = 24
    sort = (request.GET.get("sort") or "estimated_chars").lower()
    query = (request.GET.get("q") or "").strip()
    method_filter = (request.GET.get("detection_method") or "").strip().lower()
    run_id = request.GET.get("run_id")

    qs = RedactionRecord.objects.select_related(
        "extracted_document", "extracted_document__extraction_run"
    )

    if run_id:
        try:
            qs = qs.filter(extracted_document__extraction_run_id=int(run_id))
        except ValueError:
            pass
    else:
        latest_run = ExtractionRun.objects.order_by("-started_at").first()
        if latest_run:
            qs = qs.filter(extracted_document__extraction_run=latest_run)

    if query:
        qs = qs.filter(Q(text_before__icontains=query) | Q(text_after__icontains=query))
    if method_filter in ("pymupdf", "opencv", "both"):
        qs = qs.filter(detection_method=method_filter)

    sort_map = {
        "estimated_chars": "-estimated_chars",
        "estimated_chars_asc": "estimated_chars",
        "doc": "extracted_document__doc_id",
        "page": "page_num",
        "confidence": "-confidence",
        "detection_method": "detection_method",
    }
    qs = qs.order_by(sort_map.get(sort, "-estimated_chars"), "pk")

    total = qs.count()
    start = (page_num - 1) * page_size
    end = start + page_size
    records = list(qs[start:end])

    items = []
    for r in records:
        items.append({
            "id": r.pk,
            "doc_id": r.extracted_document.doc_id,
            "page_num": r.page_num,
            "redaction_index": r.redaction_index,
            "estimated_chars": r.estimated_chars,
            "detection_method": r.detection_method,
            "confidence": round(r.confidence, 2),
            "text_before_snippet": (r.text_before or "")[:80],
            "text_after_snippet": (r.text_after or "")[:80],
            "image_context": r.image_context,
            "image_tight": r.image_tight,
            "width_points": round(r.width_points, 1),
            "height_points": round(r.height_points, 1),
        })

    return JsonResponse({
        "items": items,
        "total": total,
        "page": page_num,
        "has_more": end < total,
    })


def redaction_detail(request, pk):
    """Return full detail JSON for a single redaction."""
    try:
        r = RedactionRecord.objects.select_related(
            "extracted_document", "extracted_document__extraction_run"
        ).get(pk=pk)
    except RedactionRecord.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    doc = r.extracted_document
    run = doc.extraction_run

    dpi = 150
    if isinstance(run.parameters, dict):
        dpi = run.parameters.get("dpi", 150)

    return JsonResponse({
        "id": r.pk,
        "doc_id": doc.doc_id,
        "file_path": doc.file_path,
        "extraction_run_id": run.pk,
        "run_started_at": run.started_at.isoformat(),
        "dpi": dpi,
        "page_num": r.page_num,
        "redaction_index": r.redaction_index,
        "bbox_x0_points": r.bbox_x0_points,
        "bbox_y0_points": r.bbox_y0_points,
        "bbox_x1_points": r.bbox_x1_points,
        "bbox_y1_points": r.bbox_y1_points,
        "width_points": round(r.width_points, 2),
        "height_points": round(r.height_points, 2),
        "bbox_x0_pixels": r.bbox_x0_pixels,
        "bbox_y0_pixels": r.bbox_y0_pixels,
        "bbox_x1_pixels": r.bbox_x1_pixels,
        "bbox_y1_pixels": r.bbox_y1_pixels,
        "width_pixels": r.width_pixels,
        "height_pixels": r.height_pixels,
        "detection_method": r.detection_method,
        "confidence": round(r.confidence, 4),
        "estimated_chars": r.estimated_chars,
        "font_size_nearby": r.font_size_nearby,
        "avg_char_width": r.avg_char_width,
        "text_before": r.text_before,
        "text_after": r.text_after,
        "has_ascender_leakage": r.has_ascender_leakage,
        "has_descender_leakage": r.has_descender_leakage,
        "leakage_pixels_top": r.leakage_pixels_top,
        "leakage_pixels_bottom": r.leakage_pixels_bottom,
        "is_multiline": r.is_multiline,
        "multiline_group_id": r.multiline_group_id,
        "line_index_in_group": r.line_index_in_group,
        "image_tight": r.image_tight,
        "image_context": r.image_context,
    })


PDF_FONT_TO_CSS = [
    ("timesnewroman",  '"Times New Roman", Times, serif',  "exact"),
    ("times",          '"Times New Roman", Times, serif',  "pattern"),
    ("palatino",       '"Palatino Linotype", Palatino, serif', "pattern"),
    ("garamond",       'Garamond, "EB Garamond", serif',  "pattern"),
    ("georgia",        'Georgia, serif',                   "exact"),
    ("bookman",        '"Bookman Old Style", Bookman, serif', "pattern"),
    ("helveticaneue",  '"Helvetica Neue", Helvetica, Arial, sans-serif', "exact"),
    ("helvetica",      'Helvetica, Arial, sans-serif',     "exact"),
    ("arial",          'Arial, Helvetica, sans-serif',     "exact"),
    ("verdana",        'Verdana, Geneva, sans-serif',      "exact"),
    ("tahoma",         'Tahoma, Geneva, sans-serif',       "exact"),
    ("trebuchet",      '"Trebuchet MS", sans-serif',       "pattern"),
    ("calibri",        'Calibri, sans-serif',              "exact"),
    ("cambria",        'Cambria, serif',                   "exact"),
    ("courier",        '"Courier New", Courier, monospace', "pattern"),
    ("consolas",       'Consolas, monospace',              "exact"),
    ("menlo",          'Menlo, monospace',                 "exact"),
    ("symbol",         'Symbol, serif',                    "exact"),
]


def _analyze_pdf_font(pdf_font_name: str) -> dict:
    """Map a PDF font name to CSS family, confidence, and detect weight/style from name."""
    lower = pdf_font_name.lower().replace(" ", "").replace("-", "")
    css_family = "serif"
    confidence = "fallback"
    for pattern, css, conf in PDF_FONT_TO_CSS:
        if pattern in lower:
            css_family = css
            confidence = conf
            break

    is_bold = any(k in lower for k in ("bold", "black", "heavy", "demi"))
    is_italic = any(k in lower for k in ("italic", "oblique", "slant"))

    return {
        "css_family": css_family,
        "confidence": confidence,
        "name_bold": is_bold,
        "name_italic": is_italic,
    }


def _parse_font_flags(flags: int) -> tuple:
    """Extract bold/italic from PyMuPDF span flags bitmask."""
    is_bold = bool(flags & 16)
    is_italic = bool(flags & 2)
    is_serif = bool(flags & 4)
    is_mono = bool(flags & 8)
    return is_bold, is_italic, is_serif, is_mono


def _group_spans_into_lines(spans, y_tolerance_px):
    """Group a list of span dicts into lines by Y-center clustering."""
    if not spans:
        return []
    spans_sorted = sorted(spans, key=lambda s: s["y_center"])
    lines = []
    current_line = [spans_sorted[0]]
    for s in spans_sorted[1:]:
        if abs(s["y_center"] - current_line[0]["y_center"]) <= y_tolerance_px:
            current_line.append(s)
        else:
            lines.append(current_line)
            current_line = [s]
    lines.append(current_line)
    for line in lines:
        line.sort(key=lambda s: s["bbox_px"][0])
    lines.sort(key=lambda line: line[0]["y_center"])
    return lines


def redaction_font_analysis(request, pk):
    """On-the-fly font/spacing analysis for text surrounding a redaction."""
    import fitz

    try:
        r = RedactionRecord.objects.select_related(
            "extracted_document", "extracted_document__extraction_run"
        ).get(pk=pk)
    except RedactionRecord.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    doc_record = r.extracted_document
    run = doc_record.extraction_run
    pdf_path = Path(doc_record.file_path)
    if not pdf_path.is_file():
        return JsonResponse({"error": "PDF not found"}, status=404)

    dpi = 150
    if isinstance(run.parameters, dict):
        dpi = run.parameters.get("dpi", 150)
    scale = dpi / 72.0

    redaction_bbox_pt = (
        r.bbox_x0_points, r.bbox_y0_points,
        r.bbox_x1_points, r.bbox_y1_points,
    )
    redaction_bbox_px = [round(v * scale) for v in redaction_bbox_pt]
    redaction_y_center_px = (redaction_bbox_px[1] + redaction_bbox_px[3]) / 2

    try:
        pdf_doc = fitz.open(str(pdf_path))
        page_index = r.page_num - 1
        if page_index < 0 or page_index >= len(pdf_doc):
            pdf_doc.close()
            return JsonResponse({"error": "Page out of range"}, status=404)
        page = pdf_doc[page_index]
        page_rect = page.rect
        page_width_px = round(page_rect.width * scale)
        page_height_px = round(page_rect.height * scale)

        raw_dict = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        pdf_doc.close()
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    all_spans = []
    font_names_seen = set()
    for block in raw_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                chars = span.get("chars")
                if chars:
                    text = "".join(c.get("c", "") for c in chars)
                else:
                    text = span.get("text", "")
                if not text.strip():
                    continue
                bbox = span.get("bbox")
                if bbox is None:
                    continue
                origin = span.get("origin")
                font_name = span.get("font", "unknown")
                font_size_pt = span.get("size", 12.0)
                flags = span.get("flags", 0)

                flag_bold, flag_italic, flag_serif, flag_mono = _parse_font_flags(flags)
                name_info = _analyze_pdf_font(font_name)
                is_bold = flag_bold or name_info["name_bold"]
                is_italic = flag_italic or name_info["name_italic"]

                bbox_px = [
                    round(bbox[0] * scale, 1),
                    round(bbox[1] * scale, 1),
                    round(bbox[2] * scale, 1),
                    round(bbox[3] * scale, 1),
                ]
                origin_px = None
                if origin:
                    origin_px = [round(origin[0] * scale, 1), round(origin[1] * scale, 1)]

                y_center = (bbox_px[1] + bbox_px[3]) / 2
                font_names_seen.add(font_name)
                all_spans.append({
                    "text": text,
                    "bbox_px": bbox_px,
                    "origin_px": origin_px,
                    "font_name": font_name,
                    "font_size_pt": round(font_size_pt, 2),
                    "font_size_px": round(font_size_pt * scale, 2),
                    "font_weight": "bold" if is_bold else "normal",
                    "font_style": "italic" if is_italic else "normal",
                    "y_center": y_center,
                })

    font_map = {}
    for name in font_names_seen:
        info = _analyze_pdf_font(name)
        font_map[name] = {
            "css_family": info["css_family"],
            "confidence": info["confidence"],
        }

    y_tolerance_px = 3 * scale
    lines = _group_spans_into_lines(all_spans, y_tolerance_px)

    redaction_line_idx = None
    min_dist = float("inf")
    for i, line in enumerate(lines):
        line_y = sum(s["y_center"] for s in line) / len(line)
        dist = abs(line_y - redaction_y_center_px)
        if dist < min_dist:
            min_dist = dist
            redaction_line_idx = i

    before_lines = []
    same_line = []
    after_lines = []
    if redaction_line_idx is not None:
        same_line = lines[redaction_line_idx]
        start = max(0, redaction_line_idx - 3)
        for line in lines[start:redaction_line_idx]:
            before_lines.extend(line)
        end = min(len(lines), redaction_line_idx + 4)
        for line in lines[redaction_line_idx + 1:end]:
            after_lines.extend(line)

    line_spacing_px = None
    if len(lines) >= 2 and redaction_line_idx is not None:
        spacings = []
        start = max(0, redaction_line_idx - 3)
        end = min(len(lines), redaction_line_idx + 4)
        for i in range(start, end - 1):
            y1 = sum(s["y_center"] for s in lines[i]) / len(lines[i])
            y2 = sum(s["y_center"] for s in lines[i + 1]) / len(lines[i + 1])
            spacings.append(y2 - y1)
        if spacings:
            line_spacing_px = round(sum(spacings) / len(spacings), 2)

    alignment = "left"
    nearby_lines = lines[max(0, (redaction_line_idx or 0) - 2):(redaction_line_idx or 0) + 3]
    if nearby_lines and page_width_px > 0:
        left_margins = []
        right_margins = []
        for line in nearby_lines:
            lx = min(s["bbox_px"][0] for s in line)
            rx = max(s["bbox_px"][2] for s in line)
            left_margins.append(lx)
            right_margins.append(page_width_px - rx)
        avg_left = sum(left_margins) / len(left_margins)
        avg_right = sum(right_margins) / len(right_margins)
        margin_threshold = page_width_px * 0.05
        left_consistent = max(left_margins) - min(left_margins) < margin_threshold
        right_consistent = max(right_margins) - min(right_margins) < margin_threshold
        if left_consistent and right_consistent:
            if abs(avg_left - avg_right) < margin_threshold:
                alignment = "center"
            else:
                alignment = "justified"
        elif right_consistent and not left_consistent:
            alignment = "right"
        else:
            alignment = "left"

    def _clean_span(s, group):
        return {
            "text": s["text"],
            "bbox_px": s["bbox_px"],
            "origin_px": s["origin_px"],
            "font_name": s["font_name"],
            "font_size_pt": s["font_size_pt"],
            "font_size_px": s["font_size_px"],
            "font_weight": s["font_weight"],
            "font_style": s["font_style"],
            "group": group,
        }

    output_spans = []
    for s in before_lines:
        output_spans.append(_clean_span(s, "before"))
    for s in same_line:
        output_spans.append(_clean_span(s, "same"))
    for s in after_lines:
        output_spans.append(_clean_span(s, "after"))

    return JsonResponse({
        "dpi": dpi,
        "page_width_px": page_width_px,
        "page_height_px": page_height_px,
        "redaction_bbox_px": redaction_bbox_px,
        "font_map": font_map,
        "line_spacing_px": line_spacing_px,
        "alignment": alignment,
        "spans": output_spans,
    })


# ---------------------------------------------------------------------------
# Per-character advance width font fingerprinting
# ---------------------------------------------------------------------------

FITZ_BUILTIN_FONTS = [
    ("Helvetica", "Helvetica, Arial, sans-serif", "helv", False, False),
    ("Helvetica Bold", "Helvetica, Arial, sans-serif", "hebo", True, False),
    ("Helvetica Italic", "Helvetica, Arial, sans-serif", "heit", False, True),
    ("Helvetica Bold-Italic", "Helvetica, Arial, sans-serif", "hebi", True, True),
    ("Times Roman", '"Times New Roman", Times, serif', "tiro", False, False),
    ("Times Bold", '"Times New Roman", Times, serif', "tibo", True, False),
    ("Times Italic", '"Times New Roman", Times, serif', "tiit", False, True),
    ("Times Bold-Italic", '"Times New Roman", Times, serif', "tibi", True, True),
    ("Courier", '"Courier New", Courier, monospace', "cour", False, False),
    ("Courier Bold", '"Courier New", Courier, monospace', "cobo", True, False),
    ("Courier Italic", '"Courier New", Courier, monospace', "coit", False, True),
    ("Courier Bold-Italic", '"Courier New", Courier, monospace', "cobi", True, True),
]

SYSTEM_FONT_FILES = [
    ("Arial", "Arial, Helvetica, sans-serif", [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ], False, False),
    ("Arial Bold", "Arial, Helvetica, sans-serif", [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Arial_Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    ], True, False),
    ("Georgia", "Georgia, serif", [
        "/System/Library/Fonts/Supplemental/Georgia.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Georgia.ttf",
    ], False, False),
    ("Verdana", "Verdana, Geneva, sans-serif", [
        "/System/Library/Fonts/Supplemental/Verdana.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Verdana.ttf",
    ], False, False),
    ("Trebuchet MS", '"Trebuchet MS", sans-serif', [
        "/System/Library/Fonts/Supplemental/Trebuchet MS.ttf",
        "/usr/share/fonts/truetype/msttcorefonts/Trebuchet_MS.ttf",
    ], False, False),
    ("Palatino", '"Palatino Linotype", Palatino, serif', [
        "/System/Library/Fonts/Supplemental/Palatino.ttc",
    ], False, False),
    ("Calibri", "Calibri, sans-serif", [
        "/System/Library/Fonts/Supplemental/Calibri.ttf",
    ], False, False),
    ("Cambria", "Cambria, serif", [
        "/System/Library/Fonts/Supplemental/Cambria.ttc",
    ], False, False),
]

_font_cache = {}


def _load_candidate_fonts():
    """Load all candidate fitz.Font objects (cached). Returns list of
    (display_name, css_family, fitz.Font, is_bold, is_italic)."""
    import fitz

    if _font_cache:
        return _font_cache["fonts"]

    fonts = []
    for name, css, fitz_name, bold, italic in FITZ_BUILTIN_FONTS:
        try:
            fonts.append((name, css, fitz.Font(fitz_name), bold, italic))
        except Exception:
            pass

    for name, css, paths, bold, italic in SYSTEM_FONT_FILES:
        for p in paths:
            if Path(p).is_file():
                try:
                    fonts.append((name, css, fitz.Font(fontfile=p), bold, italic))
                except Exception:
                    pass
                break

    _font_cache["fonts"] = fonts
    return fonts


def _build_width_profile(raw_dict, scale, redaction_y_center_px):
    """Extract per-character normalized advance widths from rawdict spans near
    the redaction. Returns (profile_dict, nearby_spans_for_overlay)."""

    all_spans_raw = []
    for block in raw_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                chars = span.get("chars")
                if not chars or len(chars) < 1:
                    continue
                text = "".join(c.get("c", "") for c in chars)
                if not text.strip():
                    continue
                bbox = span.get("bbox")
                if bbox is None:
                    continue
                font_size_pt = span.get("size", 12.0)
                if font_size_pt < 1:
                    continue
                bbox_px = [round(v * scale, 1) for v in bbox]
                y_center = (bbox_px[1] + bbox_px[3]) / 2
                all_spans_raw.append({
                    "chars": chars,
                    "text": text,
                    "font_size_pt": font_size_pt,
                    "bbox_px": bbox_px,
                    "y_center": y_center,
                })

    y_tolerance_px = 3 * scale
    lines = _group_spans_into_lines(all_spans_raw, y_tolerance_px)

    redaction_line_idx = None
    min_dist = float("inf")
    for i, ln in enumerate(lines):
        ly = sum(s["y_center"] for s in ln) / len(ln)
        d = abs(ly - redaction_y_center_px)
        if d < min_dist:
            min_dist = d
            redaction_line_idx = i

    nearby = []
    if redaction_line_idx is not None:
        start = max(0, redaction_line_idx - 3)
        end_idx = min(len(lines), redaction_line_idx + 4)
        for ln in lines[start:end_idx]:
            nearby.extend(ln)

    char_widths = {}
    for span_data in nearby:
        chars = span_data["chars"]
        fs = span_data["font_size_pt"]
        if fs < 1:
            continue
        for i in range(len(chars) - 1):
            c = chars[i].get("c", "")
            if not c:
                continue
            origin_i = chars[i].get("origin", chars[i].get("bbox", [0, 0])[:2])
            origin_next = chars[i + 1].get("origin", chars[i + 1].get("bbox", [0, 0])[:2])
            advance_pt = origin_next[0] - origin_i[0]
            if advance_pt <= 0:
                continue
            normalized = advance_pt / fs
            if c not in char_widths:
                char_widths[c] = []
            char_widths[c].append(normalized)

    profile = {}
    for c, widths in char_widths.items():
        profile[c] = sum(widths) / len(widths)

    return profile, nearby


def _char_rmse(profile, font_obj):
    """RMSE between PDF's normalized widths and a candidate font's glyph_advance at 1em."""
    total = 0.0
    n = 0
    for char, pdf_w in profile.items():
        codepoint = ord(char)
        sys_w = font_obj.glyph_advance(codepoint)
        if sys_w is not None and sys_w > 0:
            total += (pdf_w - sys_w) ** 2
            n += 1
    return (total / n) ** 0.5 if n > 0 else float("inf")


def _estimate_rendering_params(profile, font_obj):
    """Analytically compute scale_x, letter_spacing, word_spacing from the
    per-character width profile and the matched font."""
    import statistics

    ratios = []
    for char, pdf_w in profile.items():
        if char == " ":
            continue
        sys_w = font_obj.glyph_advance(ord(char))
        if sys_w is not None and sys_w > 0.001:
            ratios.append(pdf_w / sys_w)

    if not ratios:
        return 1.0, 0.0, 0.0

    scale_x = statistics.median(ratios)

    residuals = []
    for char, pdf_w in profile.items():
        if char == " ":
            continue
        sys_w = font_obj.glyph_advance(ord(char))
        if sys_w is not None and sys_w > 0.001:
            residuals.append(pdf_w - sys_w * scale_x)

    letter_spacing_norm = statistics.mean(residuals) if residuals else 0.0

    word_spacing_norm = 0.0
    space_pdf = profile.get(" ")
    if space_pdf is not None:
        space_sys = font_obj.glyph_advance(ord(" "))
        if space_sys is not None and space_sys > 0:
            word_spacing_norm = space_pdf - (space_sys * scale_x + letter_spacing_norm)

    return scale_x, letter_spacing_norm, word_spacing_norm


def redaction_font_optimize(request, pk):
    """Identify the font via per-character advance width fingerprinting.
    No numerical optimization — purely analytical."""
    import fitz

    try:
        r = RedactionRecord.objects.select_related(
            "extracted_document", "extracted_document__extraction_run"
        ).get(pk=pk)
    except RedactionRecord.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    doc_record = r.extracted_document
    run = doc_record.extraction_run
    pdf_path = Path(doc_record.file_path)
    if not pdf_path.is_file():
        return JsonResponse({"error": "PDF not found"}, status=404)

    dpi = 150
    if isinstance(run.parameters, dict):
        dpi = run.parameters.get("dpi", 150)
    scale = dpi / 72.0

    redaction_bbox_px = [round(v * scale) for v in (
        r.bbox_x0_points, r.bbox_y0_points,
        r.bbox_x1_points, r.bbox_y1_points,
    )]
    redaction_y_center_px = (redaction_bbox_px[1] + redaction_bbox_px[3]) / 2

    try:
        pdf_doc = fitz.open(str(pdf_path))
        page = pdf_doc[r.page_num - 1]
        raw_dict = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
        pdf_doc.close()
    except Exception as e:
        return JsonResponse({"error": str(e)}, status=500)

    profile, nearby_raw = _build_width_profile(raw_dict, scale, redaction_y_center_px)

    if not profile:
        return JsonResponse({"error": "No character data found near redaction"}, status=404)

    candidate_fonts = _load_candidate_fonts()
    if not candidate_fonts:
        return JsonResponse({"error": "No candidate fonts available"}, status=500)

    scored = []
    for name, css, font_obj, bold, italic in candidate_fonts:
        rmse = _char_rmse(profile, font_obj)
        scored.append((rmse, name, css, font_obj, bold, italic))
    scored.sort(key=lambda t: t[0])

    avg_font_size_pt = 0
    count = 0
    for s in nearby_raw:
        avg_font_size_pt += s["font_size_pt"]
        count += 1
    avg_font_size_pt = avg_font_size_pt / count if count else 12.0
    avg_font_size_px = round(avg_font_size_pt * scale, 2)

    results = []
    for rmse, name, css, font_obj, bold, italic in scored[:8]:
        sx, ls_norm, ws_norm = _estimate_rendering_params(profile, font_obj)
        ls_px = round(ls_norm * avg_font_size_pt, 3)
        ws_px = round(ws_norm * avg_font_size_pt, 3)

        results.append({
            "font_name": name,
            "css_family": css,
            "font_size_px": avg_font_size_px,
            "size_scale": 1.0,
            "letter_spacing_px": ls_px,
            "x_offset_px": 0,
            "y_offset_px": 0,
            "scale_x": round(float(sx), 4),
            "word_spacing_px": ws_px,
            "rmse": round(float(rmse), 6),
            "is_bold": bold,
            "is_italic": italic,
            "char_count": len(profile),
        })

    all_candidates = [
        {"font_name": name, "rmse": round(float(rmse), 6)}
        for rmse, name, css, font_obj, bold, italic in scored
    ]

    return JsonResponse({
        "best": results[0] if results else None,
        "candidates": all_candidates,
        "all_optimized": results,
        "profile_chars": len(profile),
    })


def redaction_image(request, filepath):
    """Serve a redaction crop image from REDACTION_IMAGES_DIR."""
    images_dir = Path(settings.REDACTION_IMAGES_DIR)
    full_path = (images_dir / filepath).resolve()
    if not str(full_path).startswith(str(images_dir.resolve())):
        raise Http404
    if not full_path.is_file():
        raise Http404
    return FileResponse(open(full_path, "rb"), content_type="image/png")


def _render_single_page(pdf_path: Path, page_num: int, dpi: int = 150) -> Path:
    """Render a single PDF page to a cached PNG. page_num is 1-indexed."""
    import fitz

    media_dir = Path(settings.MEDIA_ROOT)
    cache_dir = media_dir / "pdf_page_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    digest = hashlib.sha256(str(pdf_path).encode("utf-8")).hexdigest()[:16]
    cached = cache_dir / f"{digest}_p{page_num}_r{dpi}.png"
    if cached.is_file():
        return cached

    doc = fitz.open(str(pdf_path))
    page_index = page_num - 1
    if page_index < 0 or page_index >= len(doc):
        doc.close()
        raise RuntimeError(f"Page {page_num} out of range (doc has {len(doc)} pages)")

    page = doc[page_index]
    zoom = dpi / 72.0
    mat = fitz.Matrix(zoom, zoom)
    pix = page.get_pixmap(matrix=mat)
    pix.save(str(cached))
    doc.close()
    return cached


def redaction_page_image(request, pk):
    """Render and serve the PDF page containing a given redaction."""
    try:
        r = RedactionRecord.objects.select_related(
            "extracted_document", "extracted_document__extraction_run"
        ).get(pk=pk)
    except RedactionRecord.DoesNotExist:
        raise Http404

    doc = r.extracted_document
    run = doc.extraction_run
    pdf_path = Path(doc.file_path)
    if not pdf_path.is_file():
        raise Http404

    dpi = 150
    if isinstance(run.parameters, dict):
        dpi = run.parameters.get("dpi", 150)

    try:
        png_path = _render_single_page(pdf_path, r.page_num, dpi)
    except RuntimeError:
        raise Http404

    resp = FileResponse(open(png_path, "rb"), content_type="image/png")
    resp["Cache-Control"] = "public, max-age=86400"
    return resp

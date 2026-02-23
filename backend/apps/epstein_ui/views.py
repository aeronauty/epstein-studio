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
    DocumentEntity,
    CandidateList,
    RedactionCandidate,
    BatchRun,
)


def docs_page(request, slug=None):
    """Render project documentation from the docs/ markdown files."""
    import markdown

    docs_dir = Path(settings.BASE_DIR).parent / "docs"
    doc_files = sorted(docs_dir.glob("*.md"))

    toc = []
    for f in doc_files:
        s = f.stem
        toc.append({"slug": s, "title": s.replace("-", " ").replace("_", " ").title(), "active": s == slug})

    if not slug:
        slug = toc[0]["slug"] if toc else None
        toc[0]["active"] = True

    md_path = docs_dir / f"{slug}.md"
    if not md_path.exists():
        raise Http404(f"Doc '{slug}' not found")

    md_text = md_path.read_text()
    html_content = markdown.markdown(md_text, extensions=["fenced_code", "tables", "toc", "codehilite"])

    return render(request, "epstein_ui/docs.html", {
        "toc": toc,
        "content": html_content,
        "current_slug": slug,
    })


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
# Entity browser views
# ---------------------------------------------------------------------------

def entities_page(request):
    """Render the entity browser page."""
    try:
        total_entities = DocumentEntity.objects.count()
        total_people = DocumentEntity.objects.filter(entity_type="PERSON").values("entity_text").distinct().count()
        total_candidates = sum(
            len(cl.entries or []) for cl in CandidateList.objects.all()
        )
    except (OperationalError, ProgrammingError):
        total_entities = 0
        total_people = 0
        total_candidates = 0
    return render(request, "epstein_ui/entities.html", {
        "total_entities": total_entities,
        "total_people": total_people,
        "total_candidates": total_candidates,
    })


def entities_list(request):
    """Return paginated entity records as JSON with aggregation."""
    from django.db.models import Sum, Count

    try:
        page_num = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page_num = 1
    page_size = 50
    query = (request.GET.get("q") or "").strip()
    type_filter = (request.GET.get("type") or "").strip().upper()
    doc_filter = request.GET.get("doc_id", "").strip()
    sort = (request.GET.get("sort") or "frequency").lower()

    qs = DocumentEntity.objects.values("entity_text", "entity_type").annotate(
        total_count=Sum("count"),
        doc_count=Count("extracted_document", distinct=True),
    )

    if query:
        qs = qs.filter(entity_text__icontains=query)
    if type_filter:
        qs = qs.filter(entity_type=type_filter)
    if doc_filter:
        qs = qs.filter(extracted_document__doc_id=doc_filter)

    sort_map = {
        "frequency": "-total_count",
        "frequency_asc": "total_count",
        "alpha": "entity_text",
        "alpha_desc": "-entity_text",
        "docs": "-doc_count",
        "type": "entity_type",
    }
    qs = qs.order_by(sort_map.get(sort, "-total_count"))

    total = qs.count()
    start = (page_num - 1) * page_size
    end = start + page_size
    records = list(qs[start:end])

    type_counts = {}
    try:
        for row in DocumentEntity.objects.values("entity_type").annotate(n=Count("entity_text", distinct=True)):
            type_counts[row["entity_type"]] = row["n"]
    except Exception:
        pass

    return JsonResponse({
        "items": records,
        "total": total,
        "page": page_num,
        "has_more": end < total,
        "type_counts": type_counts,
    })


def entity_detail(request, entity_text):
    """Return all occurrences of a specific entity across documents."""
    records = list(
        DocumentEntity.objects.filter(entity_text=entity_text)
        .select_related("extracted_document")
        .order_by("-count")
        .values(
            "entity_text", "entity_type", "page_num", "count",
            "extracted_document__doc_id",
            "extracted_document__file_path",
        )[:200]
    )

    with_bbox = request.GET.get("bbox") == "1"
    if with_bbox:
        import fitz

        for rec in records:
            rec["bboxes"] = []
            pdf_path = rec.pop("extracted_document__file_path", "")
            page_num = rec.get("page_num")
            if not pdf_path or not page_num:
                continue
            try:
                doc = fitz.open(pdf_path)
                if page_num - 1 < len(doc):
                    page = doc[page_num - 1]
                    hits = page.search_for(entity_text, quads=False)
                    for rect in hits[:5]:
                        rec["bboxes"].append([
                            round(rect.x0, 1), round(rect.y0, 1),
                            round(rect.x1, 1), round(rect.y1, 1),
                        ])
                doc.close()
            except Exception:
                pass
    else:
        for rec in records:
            rec.pop("extracted_document__file_path", None)

    return JsonResponse({
        "entity_text": entity_text,
        "occurrences": records,
        "total": len(records),
    })


def entity_redaction_matches(request, entity_text):
    """Return redactions where entity_text appears as a candidate match."""
    from django.db.models import F

    try:
        page_num = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page_num = 1
    page_size = 30

    qs = (
        RedactionCandidate.objects
        .filter(candidate_text=entity_text)
        .select_related("redaction", "redaction__extracted_document")
        .order_by("rank")
    )

    total = qs.count()
    start = (page_num - 1) * page_size
    items = []
    for rc in qs[start : start + page_size]:
        r = rc.redaction
        doc = r.extracted_document
        items.append({
            "redaction_id": r.pk,
            "doc_id": doc.doc_id if doc else "",
            "page_num": r.page_num,
            "redaction_index": r.redaction_index,
            "rank": rc.rank,
            "total_score": round(rc.total_score, 3),
            "width_ratio": round(rc.width_ratio, 3),
            "width_fit": round(rc.width_fit, 3),
            "nlp_score": round(rc.nlp_score, 3),
            "text_before": (r.text_before or "")[-60:],
            "text_after": (r.text_after or "")[:60],
            "bbox_x0": r.bbox_x0_points,
            "bbox_y0": r.bbox_y0_points,
            "bbox_x1": r.bbox_x1_points,
            "bbox_y1": r.bbox_y1_points,
            "width_pt": round(r.width_points, 1),
            "height_pt": round(r.height_points, 1),
            "estimated_chars": r.estimated_chars,
            "image_context": r.image_context,
        })

    return JsonResponse({
        "entity_text": entity_text,
        "items": items,
        "total": total,
        "page": page_num,
        "has_more": start + page_size < total,
    })


def candidate_lists(request):
    """List all candidate lists, or create a new one (POST)."""
    import json as _json

    if request.method == "POST":
        try:
            body = _json.loads(request.body)
        except Exception:
            return JsonResponse({"error": "Invalid JSON"}, status=400)
        name = (body.get("name") or "").strip()
        entries = body.get("entries", [])
        if not name:
            return JsonResponse({"error": "Name required"}, status=400)
        entries = [e.strip() for e in entries if isinstance(e, str) and e.strip()]
        if not entries:
            return JsonResponse({"error": "At least one entry required"}, status=400)
        obj, created = CandidateList.objects.update_or_create(
            name=name, defaults={"entries": entries},
        )
        return JsonResponse({
            "id": obj.pk, "name": obj.name,
            "count": len(obj.entries), "created": created,
        })

    records = []
    for cl in CandidateList.objects.order_by("name"):
        records.append({
            "id": cl.pk,
            "name": cl.name,
            "count": len(cl.entries or []),
            "entries": cl.entries or [],
        })
    return JsonResponse({"lists": records, "total": len(records)})


def candidate_list_delete(request, pk):
    """Delete a candidate list."""
    if request.method != "DELETE":
        return JsonResponse({"error": "DELETE only"}, status=405)
    try:
        cl = CandidateList.objects.get(pk=pk)
    except CandidateList.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)
    cl.delete()
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------------
# Candidate matches browser
# ---------------------------------------------------------------------------

def matches_page(request):
    """Render the candidate matches browser page."""
    try:
        total_matches = RedactionCandidate.objects.count()
        redactions_with_matches = RedactionCandidate.objects.values(
            "redaction"
        ).distinct().count()
        latest_batch = BatchRun.objects.order_by("-pk").first()
    except (OperationalError, ProgrammingError):
        total_matches = 0
        redactions_with_matches = 0
        latest_batch = None
    return render(request, "epstein_ui/matches.html", {
        "total_matches": total_matches,
        "redactions_with_matches": redactions_with_matches,
        "latest_batch": latest_batch,
    })


def matches_list(request):
    """Return paginated candidate matches as JSON, grouped by redaction."""
    from django.db.models import Max, Count

    try:
        page_num = max(1, int(request.GET.get("page", 1)))
    except ValueError:
        page_num = 1
    page_size = 30
    query = (request.GET.get("q") or "").strip()
    doc_filter = (request.GET.get("doc") or "").strip()
    min_score = float(request.GET.get("min_score", 0))

    sort = (request.GET.get("sort") or "score").lower()

    qs = RedactionRecord.objects.filter(
        candidates__isnull=False
    ).distinct().select_related("extracted_document").annotate(
        top_score=Max("candidates__total_score"),
        match_count=Count("candidates"),
    )

    if doc_filter:
        qs = qs.filter(extracted_document__doc_id__icontains=doc_filter)
    if min_score > 0:
        qs = qs.filter(top_score__gte=min_score)
    if query:
        qs = qs.filter(candidates__candidate_text__icontains=query).distinct()

    sort_map = {
        "score": "-top_score",
        "score_asc": "top_score",
        "candidates": "-match_count",
        "width": "-width_points",
        "width_asc": "width_points",
        "doc": "extracted_document__doc_id",
        "page": "extracted_document__doc_id",
    }
    qs = qs.order_by(sort_map.get(sort, "-top_score"))

    total = qs.count()
    start = (page_num - 1) * page_size
    redactions_page = list(qs[start:start + page_size])

    items = []
    for r in redactions_page:
        top_candidates = list(
            RedactionCandidate.objects.filter(redaction=r)
            .order_by("rank")[:10]
            .values("candidate_text", "total_score", "width_fit",
                    "nlp_score", "leakage_score", "width_ratio", "rank")
        )
        items.append({
            "redaction_id": r.pk,
            "doc_id": r.extracted_document.doc_id,
            "page_num": r.page_num,
            "redaction_index": r.redaction_index,
            "text_before": (r.text_before or "")[-60:],
            "text_after": (r.text_after or "")[:60],
            "width_pt": round(r.width_points, 1),
            "estimated_chars": r.estimated_chars,
            "has_leakage": r.has_ascender_leakage or r.has_descender_leakage,
            "top_score": round(r.top_score, 3) if r.top_score else 0,
            "match_count": r.match_count,
            "candidates": top_candidates,
            "image_context": r.image_context or "",
        })

    return JsonResponse({
        "items": items,
        "total": total,
        "page": page_num,
        "has_more": (start + page_size) < total,
    })


def matches_stats(request):
    """Summary stats for the matches browser."""
    from django.db.models import Avg, Max, Count

    top_candidates = list(
        RedactionCandidate.objects.values("candidate_text")
        .annotate(
            appearances=Count("id"),
            avg_score=Avg("total_score"),
            best_score=Max("total_score"),
        )
        .order_by("-appearances")[:30]
    )
    for c in top_candidates:
        c["avg_score"] = round(c["avg_score"], 3)
        c["best_score"] = round(c["best_score"], 3)

    return JsonResponse({
        "top_candidates": top_candidates,
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


# ---------------------------------------------------------------------------
# Text candidate identification
# ---------------------------------------------------------------------------

_nlp_cache = {}


def _get_nlp():
    """Lazy-load spaCy model (cached)."""
    if "nlp" not in _nlp_cache:
        import spacy
        try:
            _nlp_cache["nlp"] = spacy.load("en_core_web_lg", disable=["lemmatizer"])
        except OSError:
            _nlp_cache["nlp"] = spacy.load("en_core_web_sm", disable=["lemmatizer"])
    return _nlp_cache["nlp"]


# -- Phase 3a: Gap type prediction from context --

GAP_PATTERNS = [
    (r"(?:Mr|Mrs|Ms|Miss|Dr|Prof|Rev|Sir|Lord|Lady|Judge|Sen|Rep)\.?\s*$",
     "PERSON", 0.95, "Title prefix → surname"),
    (r"(?:named|called|known as)\s+$",
     "PERSON", 0.85, "Naming construction → person/entity name"),
    (r"(?:told|said|asked|wrote|stated|testified|replied)\s+",
     "PERSON", 0.70, "Speech verb after gap → speaker name"),
    (r"^\s*(?:said|told|asked|wrote|stated|testified|replied|denied|confirmed)",
     "PERSON", 0.75, "Gap before speech verb → speaker name"),
    (r"(?:in|at|from|near|to)\s+$",
     "GPE", 0.50, "Preposition → place name"),
    (r"(?:on|dated?|from)\s+(?:\w+\s+)?\d",
     "DATE", 0.60, "Date pattern context"),
    (r"(?:the|a|an)\s+$",
     "ORG", 0.30, "Article → noun/org"),
    (r"\$\s*$",
     "MONEY", 0.80, "Dollar sign → monetary amount"),
]


def _predict_gap_type(text_before, text_after):
    """Predict likely entity types for the redacted gap using patterns and spaCy."""
    import re

    predictions = []
    before = (text_before or "").strip()
    after = (text_after or "").strip()

    for pattern, etype, confidence, reason in GAP_PATTERNS:
        if pattern.startswith("^"):
            if re.search(pattern, after, re.IGNORECASE):
                predictions.append({
                    "entity_type": etype,
                    "confidence": confidence,
                    "reason": reason,
                    "source": "pattern",
                })
        else:
            if re.search(pattern, before, re.IGNORECASE):
                predictions.append({
                    "entity_type": etype,
                    "confidence": confidence,
                    "reason": reason,
                    "source": "pattern",
                })

    nlp = _get_nlp()
    combined = f"{before} XXXREDACTEDXXX {after}"
    doc = nlp(combined)

    for ent in doc.ents:
        if "XXXREDACTEDXXX" in ent.text:
            predictions.append({
                "entity_type": ent.label_,
                "confidence": 0.50,
                "reason": f"spaCy recognized gap region as {ent.label_}",
                "source": "spacy_ner",
            })

    for token in doc:
        if token.text == "XXXREDACTEDXXX":
            dep = token.dep_
            head_text = token.head.text
            pos_hint = None
            if dep in ("nsubj", "nsubjpass"):
                pos_hint = ("PERSON", 0.55, f"Gap is subject of '{head_text}'")
            elif dep in ("dobj", "pobj"):
                pos_hint = ("PERSON", 0.40, f"Gap is object of '{head_text}'")
            elif dep == "attr":
                pos_hint = ("ORG", 0.35, f"Gap is attribute")
            elif dep == "appos":
                pos_hint = ("PERSON", 0.50, f"Gap in apposition")
            if pos_hint:
                predictions.append({
                    "entity_type": pos_hint[0],
                    "confidence": pos_hint[1],
                    "reason": pos_hint[2],
                    "source": "spacy_dep",
                })
            break

    type_scores = {}
    for p in predictions:
        t = p["entity_type"]
        if t not in type_scores or p["confidence"] > type_scores[t]["confidence"]:
            type_scores[t] = p

    result = sorted(type_scores.values(), key=lambda x: -x["confidence"])
    return result


# -- Phase 3b: Width constraint filtering --

def _compute_candidate_width_pt(text, font_obj, scale_x=1.0,
                                letter_spacing_norm=0.0, word_spacing_norm=0.0,
                                profile=None):
    """Compute the width of a text string in normalised units (at 1pt).

    When *profile* is provided (the measured per-character advance widths from
    the PDF), characters present in the profile use the PDF's own advance values
    rather than the font file.  This is more accurate because it captures the
    exact rendering parameters (tracking, hinting, CIDFont differences) that the
    original PDF producer used.
    """
    total = 0.0
    for ch in text:
        if profile and ch in profile:
            total += profile[ch]
        else:
            adv = font_obj.glyph_advance(ord(ch))
            if adv is not None and adv > 0:
                total += adv * scale_x + letter_spacing_norm
            else:
                total += 0.5 * scale_x
            if ch == " ":
                total += word_spacing_norm
    return total


def _measure_precise_gap(raw_dict, scale, redaction_bbox_pt):
    """Measure the exact gap on the redaction's line using character origins.

    Returns a dict with:
      gap_pt:        distance from right edge of last char before to origin of
                     first char after the redaction, in PDF points.
      char_before:   the character string immediately before the gap (e.g. "d")
      char_after:    the character string immediately after the gap (e.g. "w")
      needs_space_before: True if char_before is not whitespace (so a space
                     must be prepended to the candidate).
      needs_space_after:  True if char_after is not whitespace.
      font_size_pt:  average font size on this line.
    Returns None if the gap cannot be measured.
    """
    rx0, ry0, rx1, ry1 = redaction_bbox_pt
    ry_center = (ry0 + ry1) / 2.0

    all_chars = []
    for block in raw_dict.get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            for span in line.get("spans", []):
                chars = span.get("chars")
                if not chars:
                    continue
                fs = span.get("size", 12.0)
                for ch in chars:
                    origin = ch.get("origin")
                    bbox = ch.get("bbox")
                    if origin is None and bbox is not None:
                        origin = (bbox[0], bbox[1])
                    if origin is None:
                        continue
                    all_chars.append({
                        "c": ch.get("c", ""),
                        "x": origin[0],
                        "y": origin[1],
                        "fs": fs,
                        "bbox": bbox,
                    })

    if not all_chars:
        return None

    y_tol = (ry1 - ry0) * 0.8
    line_chars = [c for c in all_chars if abs(c["y"] - ry_center) < y_tol]
    if not line_chars:
        return None

    line_chars.sort(key=lambda c: c["x"])

    last_before = None
    first_after = None
    for c in line_chars:
        cx_right = c["bbox"][2] if c["bbox"] else c["x"] + 5
        if cx_right <= rx0 + 1:
            last_before = c
        elif c["x"] >= rx1 - 1 and first_after is None:
            first_after = c

    if last_before is None or first_after is None:
        return None

    last_before_right = last_before["bbox"][2] if last_before["bbox"] else last_before["x"]
    gap_pt = first_after["x"] - last_before_right

    char_b = last_before["c"]
    char_a = first_after["c"]
    needs_space_before = char_b.strip() != ""
    needs_space_after = char_a.strip() != ""

    avg_fs = sum(c["fs"] for c in line_chars) / len(line_chars) if line_chars else 12.0

    return {
        "gap_pt": max(0, gap_pt),
        "char_before": char_b,
        "char_after": char_a,
        "needs_space_before": needs_space_before,
        "needs_space_after": needs_space_after,
        "font_size_pt": avg_fs,
    }


def _filter_by_width(candidates, redaction_width_pt, font_obj, font_size_pt,
                     scale_x=1.0, tolerance=0.15,
                     letter_spacing_norm=0.0, word_spacing_norm=0.0,
                     profile=None, gap_info=None):
    """Score candidates by how well they fit the redaction width.

    When *gap_info* is provided (from ``_measure_precise_gap``), the candidate
    is padded with spaces to match what the PDF line requires.  For example, if
    the last visible char before the gap is "d" and the first after is "w",
    the effective string tested is " candidate " (space + text + space) because
    those inter-word spaces must also fit inside the measured gap.

    Tolerance tightens to 3% when a precise gap is available.
    """
    precise = gap_info is not None
    target_width = gap_info["gap_pt"] if precise else redaction_width_pt
    tol = 0.03 if precise else tolerance

    pad_before = ""
    pad_after = ""
    if precise:
        if gap_info["needs_space_before"]:
            pad_before = " "
        if gap_info["needs_space_after"]:
            pad_after = " "

    results = []
    for cand_text in candidates:
        full_text = pad_before + cand_text + pad_after
        width_at_1pt = _compute_candidate_width_pt(
            full_text, font_obj, scale_x,
            letter_spacing_norm, word_spacing_norm, profile,
        )
        cand_width_pt = width_at_1pt * font_size_pt
        if target_width <= 0:
            fit = 0.0
        else:
            ratio = cand_width_pt / target_width
            if abs(ratio - 1.0) <= tol:
                fit = 1.0 - abs(ratio - 1.0) / tol
            else:
                fit = 0.0
        results.append({
            "text": cand_text,
            "width_pt": round(cand_width_pt, 2),
            "width_ratio": round(cand_width_pt / max(target_width, 0.01), 3),
            "width_fit": round(fit, 3),
        })
    return results


# -- Phase 4: Enhanced leakage letterform identification --

ASCENDER_LETTERS = set("bdfhkltBDFHKLTAEGIJMNPQRSUVWXYZ0123456789")
DESCENDER_LETTERS = set("gjpqyQJ")


def _analyze_leakage_letterforms(page_pixmap_path, redaction_bbox_px, font_size_px, dpi):
    """Analyze pixel bands immediately adjacent to redaction for leaked letterform fragments.

    Only counts fragments that are connected to (touch) the redaction edge,
    distinguishing real leakage from nearby surrounding text.
    """
    import numpy as np
    from PIL import Image

    empty = {"ascender_fragments": [], "descender_fragments": [],
             "left_fragments": [], "right_fragments": []}
    try:
        img = Image.open(str(page_pixmap_path)).convert("L")
    except Exception:
        return empty

    img_array = np.array(img)
    h, w = img_array.shape
    x0, y0, x1, y1 = [int(v) for v in redaction_bbox_px]

    ascender_band_h = max(3, int(font_size_px * 0.25))
    descender_band_h = max(3, int(font_size_px * 0.20))
    edge_band_w = max(3, int(font_size_px * 0.30))

    # Skip the redaction box's own anti-aliased boundary (2-3px at 300 DPI).
    aa_inset = max(2, int(dpi / 100))

    results = {"ascender_fragments": [], "descender_fragments": [],
               "left_fragments": [], "right_fragments": []}

    # Top band: skip aa_inset rows closest to redaction (box AA), then scan upward.
    band_top_y0 = max(0, y0 - ascender_band_h - aa_inset)
    band_top_y1 = max(0, y0 - aa_inset)
    if band_top_y1 > band_top_y0 and x1 > x0:
        band = img_array[band_top_y0:band_top_y1, x0:x1]
        fragments = _find_dark_fragments(band, x0, font_size_px,
                                         require_edge="bottom")
        results["ascender_fragments"] = fragments

    # Bottom band: skip aa_inset rows closest to redaction (box AA).
    band_bot_y0 = min(h, y1 + aa_inset)
    band_bot_y1 = min(h, y1 + descender_band_h + aa_inset)
    if band_bot_y1 > band_bot_y0 and x1 > x0:
        band = img_array[band_bot_y0:band_bot_y1, x0:x1]
        fragments = _find_dark_fragments(band, x0, font_size_px,
                                         require_edge="top")
        results["descender_fragments"] = fragments

    # Left band: skip aa_inset cols closest to redaction.
    left_x0 = max(0, x0 - edge_band_w - aa_inset)
    left_x1 = max(0, x0 - aa_inset)
    if left_x1 > left_x0 and y1 > y0:
        band = img_array[y0:y1, left_x0:left_x1]
        fragments = _find_dark_fragments_vertical(band, y0, font_size_px,
                                                  require_edge="right")
        results["left_fragments"] = fragments

    # Right band: skip aa_inset cols closest to redaction.
    right_x0 = min(w, x1 + aa_inset)
    right_x1 = min(w, x1 + edge_band_w + aa_inset)
    if right_x1 > right_x0 and y1 > y0:
        band = img_array[y0:y1, right_x0:right_x1]
        fragments = _find_dark_fragments_vertical(band, y0, font_size_px,
                                                  require_edge="left")
        results["right_fragments"] = fragments

    return results


def _find_dark_fragments_vertical(band, y_offset, font_size_px, require_edge=None):
    """Find dark pixel regions in a vertical edge band.

    require_edge: "left" means fragment must have dark pixels in leftmost 3 cols,
                  "right" means fragment must have dark pixels in rightmost 3 cols.
    """
    import numpy as np

    if band.size == 0:
        return []

    threshold = 160
    dark_mask = band < threshold
    row_has_dark = np.any(dark_mask, axis=1)
    band_h, band_w = dark_mask.shape

    max_frag_h = max(4, int(font_size_px * 0.8))

    fragments = []
    in_fragment = False
    frag_start = 0

    def _emit(start, end):
        frag_h = end - start
        if frag_h < 2 or frag_h > max_frag_h:
            return
        frag_region = dark_mask[start:end, :]
        if require_edge == "left":
            edge_cols = min(3, band_w)
            if not np.any(frag_region[:, :edge_cols]):
                return
        elif require_edge == "right":
            edge_cols = min(3, band_w)
            if not np.any(frag_region[:, -edge_cols:]):
                return
        density = float(np.sum(frag_region)) / max(frag_region.size, 1)
        if density < 0.03:
            return
        frag_w = int(np.max(np.sum(dark_mask[start:end, :], axis=0)))
        fragments.append({
            "y_start": start + y_offset,
            "y_end": end + y_offset,
            "height_px": frag_h,
            "width_px": frag_w,
            "pixel_density": round(density, 3),
        })

    for row_idx in range(len(row_has_dark)):
        if row_has_dark[row_idx]:
            if not in_fragment:
                frag_start = row_idx
                in_fragment = True
        else:
            if in_fragment:
                _emit(frag_start, row_idx)
                in_fragment = False

    if in_fragment:
        _emit(frag_start, len(row_has_dark))

    return fragments


def _find_dark_fragments(band, x_offset, font_size_px, require_edge=None):
    """Find connected dark pixel regions in a horizontal band.

    require_edge: "top" means fragment must have dark pixels in topmost 3 rows
                  (i.e. touching the redaction edge for a bottom-band),
                  "bottom" means fragment must have dark pixels in bottommost 3 rows
                  (i.e. touching the redaction edge for a top-band).
    """
    import numpy as np

    if band.size == 0:
        return []

    threshold = 160
    dark_mask = band < threshold
    band_h, band_w = dark_mask.shape

    max_frag_w = max(4, int(font_size_px * 1.2))

    col_has_dark = np.any(dark_mask, axis=0)
    fragments = []
    in_fragment = False
    frag_start = 0

    def _emit(start, end):
        frag_width = end - start
        if frag_width < 2 or frag_width > max_frag_w:
            return
        frag_region = dark_mask[:, start:end]
        if require_edge == "top":
            edge_rows = min(3, band_h)
            if not np.any(frag_region[:edge_rows, :]):
                return
        elif require_edge == "bottom":
            edge_rows = min(3, band_h)
            if not np.any(frag_region[-edge_rows:, :]):
                return
        density = float(np.sum(frag_region)) / max(frag_region.size, 1)
        if density < 0.03:
            return
        avg_char_w = max(font_size_px * 0.5, 1)
        position = (start + frag_width / 2) / avg_char_w
        fragments.append({
            "x_start": start + x_offset,
            "x_end": end + x_offset,
            "width_px": frag_width,
            "pixel_density": round(density, 3),
            "position_estimate": round(position, 1),
        })

    for col_idx in range(len(col_has_dark)):
        if col_has_dark[col_idx]:
            if not in_fragment:
                frag_start = col_idx
                in_fragment = True
        else:
            if in_fragment:
                _emit(frag_start, col_idx)
                in_fragment = False

    if in_fragment:
        _emit(frag_start, len(col_has_dark))

    return fragments


def _match_leakage_to_candidates(leakage_data, candidate_text, font_size_px):
    """Score how well a candidate's character types match observed leakage.

    Uses a type-based approach: checks whether the candidate has
    ascenders/descenders consistent with detected fragment locations,
    rather than trying to match imprecise pixel positions to exact characters.
    """
    asc_frags = leakage_data.get("ascender_fragments", [])
    desc_frags = leakage_data.get("descender_fragments", [])
    left_frags = leakage_data.get("left_fragments", [])
    right_frags = leakage_data.get("right_fragments", [])

    if not asc_frags and not desc_frags and not left_frags and not right_frags:
        return 0.0

    score = 0.0
    checks = 0

    cand_has_ascender = any(ch in ASCENDER_LETTERS for ch in candidate_text)
    cand_has_descender = any(ch in DESCENDER_LETTERS for ch in candidate_text)
    cand_has_upper = any(ch.isupper() for ch in candidate_text)
    n_asc = sum(1 for ch in candidate_text if ch in ASCENDER_LETTERS)
    n_desc = sum(1 for ch in candidate_text if ch in DESCENDER_LETTERS)

    if asc_frags:
        checks += 1
        if cand_has_ascender or cand_has_upper:
            frag_count_match = min(len(asc_frags), n_asc + sum(1 for c in candidate_text if c.isupper()))
            score += min(1.0, frag_count_match / max(len(asc_frags), 1))
        else:
            score -= 0.3

    if desc_frags:
        checks += 1
        if cand_has_descender:
            frag_count_match = min(len(desc_frags), n_desc)
            score += min(1.0, frag_count_match / max(len(desc_frags), 1))
        else:
            score -= 0.3

    if left_frags:
        checks += 1
        first_ch = candidate_text[0] if candidate_text else ""
        if first_ch and (first_ch in ASCENDER_LETTERS or first_ch in DESCENDER_LETTERS
                         or first_ch.isupper()):
            score += 0.5
        else:
            score -= 0.1

    if right_frags:
        checks += 1
        last_ch = candidate_text[-1] if candidate_text else ""
        if last_ch and (last_ch in ASCENDER_LETTERS or last_ch in DESCENDER_LETTERS):
            score += 0.5

    # Negative evidence: no ascender leakage but candidate has ascenders
    # is mildly inconsistent (though the redaction may simply cover them).
    # Don't penalize, but give a small bonus to candidates without.
    if not asc_frags and not cand_has_ascender and not cand_has_upper:
        score += 0.15
        checks += 1

    if not desc_frags and not cand_has_descender:
        score += 0.15
        checks += 1

    return max(0.0, min(1.0, score / max(checks, 1)))


# -- Phase 5: Scoring --

def _score_candidates(width_results, gap_predictions, leakage_data,
                      font_size_px, doc_record, corpus_entities):
    """Combine all signals into ranked candidate scores."""
    predicted_types = {p["entity_type"]: p["confidence"] for p in gap_predictions}

    corpus_freq_map = {}
    max_freq = 1
    for ent in corpus_entities:
        freq = corpus_freq_map.get(ent["entity_text"], 0) + ent["count"]
        corpus_freq_map[ent["entity_text"]] = freq
        max_freq = max(max_freq, freq)

    doc_entity_set = set()
    for ent in corpus_entities:
        if ent.get("doc_id") == (doc_record.pk if doc_record else None):
            doc_entity_set.add(ent["entity_text"])

    scored = []
    for wr in width_results:
        text = wr["text"]
        width_fit = wr["width_fit"]

        nlp_score = 0.0
        ent_info = corpus_entities_by_text(corpus_entities, text)
        if ent_info:
            for etype in ent_info.get("types", []):
                if etype in predicted_types:
                    nlp_score = max(nlp_score, predicted_types[etype])

        leakage_score = _match_leakage_to_candidates(
            leakage_data, text, font_size_px
        )

        corpus_freq = corpus_freq_map.get(text, 0)
        freq_score = corpus_freq / max_freq if max_freq > 0 else 0.0

        doc_score = 0.3 if text in doc_entity_set else 0.0

        W_WIDTH = 0.35
        W_NLP = 0.25
        W_LEAK = 0.15
        W_CORPUS = 0.10
        W_DOC = 0.15

        total = (
            W_WIDTH * width_fit
            + W_NLP * nlp_score
            + W_LEAK * leakage_score
            + W_CORPUS * freq_score
            + W_DOC * doc_score
        )

        scored.append({
            "text": text,
            "score": round(total, 4),
            "width_fit": wr["width_fit"],
            "width_ratio": wr["width_ratio"],
            "width_pt": wr["width_pt"],
            "nlp_score": round(nlp_score, 3),
            "leakage_score": round(leakage_score, 3),
            "corpus_freq": corpus_freq,
            "in_same_doc": text in doc_entity_set,
        })

    scored.sort(key=lambda x: -x["score"])
    return scored


def corpus_entities_by_text(entities, text):
    """Look up entity info for a given text string."""
    types = set()
    total = 0
    for ent in entities:
        if ent["entity_text"] == text:
            types.add(ent["entity_type"])
            total += ent["count"]
    if not types:
        return None
    return {"types": list(types), "total_count": total}


# -- Phase 6: API endpoint --

def redaction_text_candidates(request, pk):
    """Identify likely redacted text using NLP, width constraints, and leakage analysis."""
    import fitz
    import json

    try:
        r = RedactionRecord.objects.select_related(
            "extracted_document", "extracted_document__extraction_run"
        ).get(pk=pk)
    except RedactionRecord.DoesNotExist:
        return JsonResponse({"error": "Not found"}, status=404)

    doc_record = r.extracted_document
    run = doc_record.extraction_run
    pdf_path = Path(doc_record.file_path)

    dpi = 150
    if isinstance(run.parameters, dict):
        dpi = run.parameters.get("dpi", 150)
    scale = dpi / 72.0

    # 1. Gap type prediction
    gap_predictions = _predict_gap_type(r.text_before, r.text_after)

    # 2. Gather candidates from corpus entities
    predicted_types = [p["entity_type"] for p in gap_predictions if p["confidence"] >= 0.3]
    if not predicted_types:
        predicted_types = ["PERSON", "ORG", "GPE"]

    entity_qs = DocumentEntity.objects.filter(
        entity_type__in=predicted_types
    ).values("entity_text", "entity_type", "count", "extracted_document_id")

    same_doc_entities = list(
        DocumentEntity.objects.filter(extracted_document=doc_record)
        .values("entity_text", "entity_type", "count")
    )
    same_doc_texts = {e["entity_text"] for e in same_doc_entities}

    all_entities_raw = list(entity_qs[:2000])
    for e in same_doc_entities:
        e["doc_id"] = doc_record.pk
    for e in all_entities_raw:
        e["doc_id"] = e.get("extracted_document_id")

    combined_entities = same_doc_entities + all_entities_raw

    candidate_texts = set()
    for e in combined_entities:
        candidate_texts.add(e["entity_text"])

    # Add user-provided candidates from request body
    user_candidates = []
    if request.method == "POST":
        try:
            body = json.loads(request.body)
            user_candidates = body.get("candidates", [])
        except (json.JSONDecodeError, AttributeError):
            pass
    elif request.method == "GET":
        raw = request.GET.get("candidates", "")
        if raw:
            user_candidates = [c.strip() for c in raw.split(",") if c.strip()]

    for uc in user_candidates:
        candidate_texts.add(uc)

    # Also pull from CandidateList if any exist
    for cl in CandidateList.objects.all():
        for entry in (cl.entries or []):
            if isinstance(entry, str) and entry.strip():
                candidate_texts.add(entry.strip())

    # 3. Width filtering using font identification + precise line-level gap
    font_obj = None
    font_size_pt = r.font_size_nearby or 10.0
    font_scale_x = 1.0
    font_letter_spacing = 0.0
    font_word_spacing = 0.0
    font_name = None
    profile = None
    gap_info = None

    candidate_fonts = _load_candidate_fonts()
    if pdf_path.is_file() and candidate_fonts:
        try:
            pdf_doc = fitz.open(str(pdf_path))
            page = pdf_doc[r.page_num - 1]
            raw_dict = page.get_text("rawdict", flags=fitz.TEXT_PRESERVE_WHITESPACE)

            redaction_bbox_pt = (
                r.bbox_x0_points, r.bbox_y0_points,
                r.bbox_x1_points, r.bbox_y1_points,
            )
            gap_info = _measure_precise_gap(raw_dict, scale, redaction_bbox_pt)

            pdf_doc.close()

            redaction_bbox_px = [round(v * scale) for v in redaction_bbox_pt]
            redaction_y_center_px = (redaction_bbox_px[1] + redaction_bbox_px[3]) / 2

            profile, nearby_raw = _build_width_profile(raw_dict, scale, redaction_y_center_px)

            if profile:
                best_rmse = float("inf")
                for name, css, fobj, bold, italic in candidate_fonts:
                    rmse = _char_rmse(profile, fobj)
                    if rmse < best_rmse:
                        best_rmse = rmse
                        font_obj = fobj
                        font_name = name

                if font_obj:
                    font_scale_x, font_letter_spacing, font_word_spacing = \
                        _estimate_rendering_params(profile, font_obj)

                if nearby_raw:
                    avg_fs = sum(s["font_size_pt"] for s in nearby_raw) / len(nearby_raw)
                    font_size_pt = avg_fs
        except Exception:
            pass

    redaction_width_pt = r.width_points

    if font_obj and candidate_texts:
        width_results = _filter_by_width(
            list(candidate_texts), redaction_width_pt, font_obj,
            font_size_pt, font_scale_x,
            letter_spacing_norm=font_letter_spacing,
            word_spacing_norm=font_word_spacing,
            profile=profile,
            gap_info=gap_info,
        )
    else:
        width_results = [
            {"text": t, "width_pt": 0, "width_ratio": 0, "width_fit": 0.5}
            for t in candidate_texts
        ]

    # 4. Leakage analysis — render at high DPI for sub-pixel sensitivity
    leakage_data = {"ascender_fragments": [], "descender_fragments": [],
                    "left_fragments": [], "right_fragments": []}
    try:
        leak_dpi = 300
        leak_scale = leak_dpi / 72.0
        page_png = _render_single_page(pdf_path, r.page_num, leak_dpi)
        redaction_bbox_px = [round(v * leak_scale) for v in (
            r.bbox_x0_points, r.bbox_y0_points,
            r.bbox_x1_points, r.bbox_y1_points,
        )]
        font_size_px = font_size_pt * leak_scale
        leakage_data = _analyze_leakage_letterforms(
            page_png, redaction_bbox_px, font_size_px, leak_dpi
        )
        has_asc = bool(leakage_data.get("ascender_fragments"))
        has_desc = bool(leakage_data.get("descender_fragments"))
        has_left = bool(leakage_data.get("left_fragments"))
        has_right = bool(leakage_data.get("right_fragments"))
        if (has_asc != r.has_ascender_leakage or has_desc != r.has_descender_leakage):
            RedactionRecord.objects.filter(pk=r.pk).update(
                has_ascender_leakage=has_asc or has_left,
                has_descender_leakage=has_desc or has_right,
            )
    except Exception:
        pass

    # 5. Score and rank
    font_size_px = font_size_pt * scale
    scored = _score_candidates(
        width_results, gap_predictions, leakage_data,
        font_size_px, doc_record, combined_entities,
    )

    fitting = [s for s in scored if s["width_fit"] > 0]
    non_fitting = [s for s in scored if s["width_fit"] == 0]

    char_count_min = 0
    char_count_max = 0
    if font_obj and redaction_width_pt > 0:
        avg_advance = 0.5
        advances = [font_obj.glyph_advance(ord(c)) for c in "etaoinsrhld"]
        valid = [a for a in advances if a and a > 0]
        if valid:
            avg_advance = sum(valid) / len(valid)
        char_count_at_1pt = redaction_width_pt / (avg_advance * font_scale_x * font_size_pt)
        char_count_min = max(1, int(char_count_at_1pt * 0.85))
        char_count_max = int(char_count_at_1pt * 1.15) + 1

    return JsonResponse({
        "gap_predictions": gap_predictions,
        "leakage": leakage_data,
        "candidates": fitting[:50],
        "other_candidates": non_fitting[:20],
        "total_candidates_checked": len(scored),
        "font_identified": font_name,
        "font_size_pt": round(font_size_pt, 2),
        "redaction_width_pt": round(redaction_width_pt, 2),
        "precise_gap_pt": round(gap_info["gap_pt"], 2) if gap_info else None,
        "gap_context": {
            "char_before": gap_info["char_before"],
            "char_after": gap_info["char_after"],
            "needs_space_before": gap_info["needs_space_before"],
            "needs_space_after": gap_info["needs_space_after"],
        } if gap_info else None,
        "width_tolerance": "3% (line-fitted)" if gap_info else "15% (bbox)",
        "estimated_char_range": [char_count_min, char_count_max],
        "has_ascender_leakage": r.has_ascender_leakage,
        "has_descender_leakage": r.has_descender_leakage,
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

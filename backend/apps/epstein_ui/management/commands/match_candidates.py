"""Batch candidate matching: run text identification across all redactions."""
import sys
import traceback
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.epstein_ui.models import (
    RedactionRecord,
    RedactionCandidate,
    CandidateList,
    DocumentEntity,
    BatchRun,
)


class Command(BaseCommand):
    help = "Run candidate text matching against all (or selected) redactions"

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear", action="store_true",
            help="Clear existing candidate matches before running",
        )
        parser.add_argument(
            "--doc", type=str, default="",
            help="Limit to a specific doc_id",
        )
        parser.add_argument(
            "--limit", type=int, default=0,
            help="Process at most N redactions (0 = all)",
        )
        parser.add_argument(
            "--top", type=int, default=20,
            help="Store top N candidates per redaction (default 20)",
        )
        parser.add_argument(
            "--min-width", type=float, default=10.0,
            help="Skip redactions narrower than this (points)",
        )

    def handle(self, *args, **options):
        import fitz
        from apps.epstein_ui.views import (
            _predict_gap_type,
            _load_candidate_fonts,
            _build_width_profile,
            _char_rmse,
            _estimate_rendering_params,
            _filter_by_width,
            _measure_precise_gap,
            _analyze_leakage_letterforms,
            _score_candidates,
            _render_single_page,
        )

        if options["clear"]:
            n, _ = RedactionCandidate.objects.all().delete()
            self.stdout.write(f"Cleared {n} existing candidate match(es)")

        # Gather all candidate texts
        candidate_texts = set()
        for cl in CandidateList.objects.all():
            for entry in (cl.entries or []):
                if isinstance(entry, str) and entry.strip():
                    candidate_texts.add(entry.strip())

        entity_texts = set(
            DocumentEntity.objects.values_list("entity_text", flat=True).distinct()
        )
        candidate_texts |= entity_texts
        self.stdout.write(f"Candidate pool: {len(candidate_texts)} unique texts")

        # Load fonts once
        candidate_fonts = _load_candidate_fonts()
        self.stdout.write(f"Loaded {len(candidate_fonts)} candidate fonts")

        # Build redaction queryset
        qs = RedactionRecord.objects.select_related(
            "extracted_document", "extracted_document__extraction_run"
        ).filter(width_points__gte=options["min_width"]).order_by("pk")

        if options["doc"]:
            qs = qs.filter(extracted_document__doc_id=options["doc"])
        if options["limit"]:
            qs = qs[:options["limit"]]

        redactions = list(qs)
        self.stdout.write(f"Processing {len(redactions)} redactions...")

        batch = BatchRun.objects.create(total_redactions=len(redactions))
        top_n = options["top"]
        total_matches = 0
        font_id_count = 0

        # Group redactions by PDF to avoid re-opening the same file repeatedly
        pdf_groups = {}
        for r in redactions:
            key = r.extracted_document.file_path
            pdf_groups.setdefault(key, []).append(r)

        processed = 0
        for pdf_path_str, group in pdf_groups.items():
            pdf_path = Path(pdf_path_str)
            if not pdf_path.is_file():
                self.stderr.write(f"  PDF not found: {pdf_path}")
                processed += len(group)
                continue

            run = group[0].extracted_document.extraction_run
            dpi = 150
            if isinstance(run.parameters, dict):
                dpi = run.parameters.get("dpi", 150)
            scale = dpi / 72.0

            # Open PDF once, cache per-page rawdict and font profiles
            try:
                pdf_doc = fitz.open(str(pdf_path))
            except Exception as e:
                self.stderr.write(f"  Cannot open {pdf_path}: {e}")
                processed += len(group)
                continue

            page_cache = {}

            for r in group:
                processed += 1
                try:
                    self._process_one(
                        r, pdf_doc, page_cache, scale, dpi,
                        candidate_texts, candidate_fonts,
                        _predict_gap_type, _build_width_profile,
                        _char_rmse, _estimate_rendering_params,
                        _filter_by_width, _measure_precise_gap,
                        _analyze_leakage_letterforms,
                        _score_candidates, _render_single_page,
                        top_n,
                    )
                    n_saved = r._batch_saved_count
                    total_matches += n_saved
                    if r._batch_font_name:
                        font_id_count += 1

                    if processed % 25 == 0 or processed == len(redactions):
                        batch.processed = processed
                        batch.total_matches = total_matches
                        batch.font_identified_count = font_id_count
                        batch.save(update_fields=["processed", "total_matches", "font_identified_count"])
                        self.stdout.write(
                            f"  {processed}/{len(redactions)} — "
                            f"{total_matches} matches, {font_id_count} fonts identified"
                        )
                except Exception:
                    self.stderr.write(f"  Error on redaction {r.pk}: {traceback.format_exc()}")

            pdf_doc.close()

        batch.processed = processed
        batch.total_matches = total_matches
        batch.font_identified_count = font_id_count
        batch.finished_at = timezone.now()
        batch.status = "done"
        batch.save()

        self.stdout.write(self.style.SUCCESS(
            f"Done. {processed} redactions processed, "
            f"{total_matches} candidate matches saved, "
            f"{font_id_count} fonts identified."
        ))

    def _process_one(
        self, r, pdf_doc, page_cache, scale, dpi,
        candidate_texts, candidate_fonts,
        _predict_gap_type, _build_width_profile,
        _char_rmse, _estimate_rendering_params,
        _filter_by_width, _measure_precise_gap,
        _analyze_leakage_letterforms,
        _score_candidates, _render_single_page,
        top_n,
    ):
        """Run the full candidate pipeline on one redaction and store results."""

        doc_record = r.extracted_document

        # 1. Gap type prediction
        gap_predictions = _predict_gap_type(r.text_before, r.text_after)

        # 2. Font identification (cached per page)
        page_key = r.page_num
        if page_key not in page_cache:
            page = pdf_doc[r.page_num - 1]
            raw_dict = page.get_text("rawdict", flags=1)  # TEXT_PRESERVE_WHITESPACE
            page_cache[page_key] = raw_dict
        raw_dict = page_cache[page_key]

        redaction_bbox_pt = (
            r.bbox_x0_points, r.bbox_y0_points,
            r.bbox_x1_points, r.bbox_y1_points,
        )
        redaction_bbox_px = [round(v * scale) for v in redaction_bbox_pt]
        redaction_y_center_px = (redaction_bbox_px[1] + redaction_bbox_px[3]) / 2

        font_obj = None
        font_size_pt = r.font_size_nearby or 10.0
        font_scale_x = 1.0
        font_letter_spacing = 0.0
        font_word_spacing = 0.0
        font_name = None
        profile = None

        # Measure precise gap from character origins on the line
        gap_info = _measure_precise_gap(raw_dict, scale, redaction_bbox_pt)

        if candidate_fonts:
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
                    font_size_pt = sum(s["font_size_pt"] for s in nearby_raw) / len(nearby_raw)

        r._batch_font_name = font_name

        # 3. Width filtering — "called [CANDIDATE] who" must line up
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
            pdf_path = Path(doc_record.file_path)
            leak_dpi = 300
            leak_scale = leak_dpi / 72.0
            page_png = _render_single_page(pdf_path, r.page_num, leak_dpi)
            leak_bbox_px = [round(v * leak_scale) for v in (
                r.bbox_x0_points, r.bbox_y0_points,
                r.bbox_x1_points, r.bbox_y1_points,
            )]
            font_size_px = font_size_pt * leak_scale
            leakage_data = _analyze_leakage_letterforms(
                page_png, leak_bbox_px, font_size_px, leak_dpi
            )
            has_asc = bool(leakage_data.get("ascender_fragments"))
            has_desc = bool(leakage_data.get("descender_fragments"))
            has_left = bool(leakage_data.get("left_fragments"))
            has_right = bool(leakage_data.get("right_fragments"))
            if has_asc or has_desc or has_left or has_right:
                RedactionRecord.objects.filter(pk=r.pk).update(
                    has_ascender_leakage=has_asc or has_left,
                    has_descender_leakage=has_desc or has_right,
                )
        except Exception:
            pass

        # 5. Score and rank
        font_size_px = font_size_pt * scale

        # Build a minimal combined_entities list for scoring
        same_doc_entities = list(
            DocumentEntity.objects.filter(extracted_document=doc_record)
            .values("entity_text", "entity_type", "count")
        )
        for e in same_doc_entities:
            e["doc_id"] = doc_record.pk

        scored = _score_candidates(
            width_results, gap_predictions, leakage_data,
            font_size_px, doc_record, same_doc_entities,
        )

        # Keep only those with width_fit > 0 (they actually fit), take top N
        fitting = [s for s in scored if s["width_fit"] > 0][:top_n]

        # Bulk-save
        r.candidates.all().delete()
        objs = []
        for rank, s in enumerate(fitting, 1):
            objs.append(RedactionCandidate(
                redaction=r,
                candidate_text=s["text"],
                total_score=s.get("score", 0),
                width_fit=s.get("width_fit", 0),
                nlp_score=s.get("nlp_score", 0),
                leakage_score=s.get("leakage_score", 0),
                corpus_freq=s.get("corpus_freq", 0),
                doc_freq=s.get("doc_freq", 0),
                width_ratio=s.get("width_ratio", 0),
                rank=rank,
            ))
        RedactionCandidate.objects.bulk_create(objs)
        r._batch_saved_count = len(objs)

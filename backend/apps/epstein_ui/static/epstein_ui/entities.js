(function () {
  "use strict";

  const PAGE_SIZE = 50;
  let currentPage = 1;
  let debounceTimer = null;

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const searchInput = $("#entSearch");
  const typeSelect = $("#entTypeFilter");
  const sortSelect = $("#entSort");
  const tbody = $("#entBody");
  const loading = $("#entLoading");
  const emptyMsg = $("#entEmpty");
  const prevBtn = $("#entPrev");
  const nextBtn = $("#entNext");
  const pageInfo = $("#entPageInfo");
  const detailPanel = $("#entDetail");
  const detailTitle = $("#entDetailTitle");
  const detailClose = $("#entDetailClose");

  const TYPE_LABELS = {
    PERSON: "Person", ORG: "Organization", GPE: "Geo-Political",
    LOC: "Location", DATE: "Date", FAC: "Facility",
    NORP: "Group/Nationality", EVENT: "Event", LAW: "Law",
    PRODUCT: "Product", WORK_OF_ART: "Work of Art", MONEY: "Money",
    QUANTITY: "Quantity", ORDINAL: "Ordinal", CARDINAL: "Cardinal",
    TIME: "Time", PERCENT: "Percent", LANGUAGE: "Language",
  };

  const TYPE_COLOURS = {
    PERSON: "#e74c3c", ORG: "#3498db", GPE: "#2ecc71",
    LOC: "#1abc9c", DATE: "#9b59b6", FAC: "#e67e22",
    NORP: "#f39c12", EVENT: "#e91e63", LAW: "#795548",
    MONEY: "#00bcd4", DEFAULT: "#607d8b",
  };

  function esc(s) {
    const el = document.createElement("span");
    el.textContent = s;
    return el.innerHTML;
  }

  function typeTag(t) {
    const col = TYPE_COLOURS[t] || TYPE_COLOURS.DEFAULT;
    const label = TYPE_LABELS[t] || t;
    return `<span class="ent-type-tag" style="--tag-col:${col}">${esc(label)}</span>`;
  }

  // ==========================================================================
  // Top-level tabs
  // ==========================================================================
  $$(".ent-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".ent-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const target = tab.dataset.tab;
      $$("#tabEntities, #tabCandidates").forEach((p) => (p.style.display = "none"));
      $(`#tab${target.charAt(0).toUpperCase() + target.slice(1)}`).style.display = "";
      if (target === "candidates") fetchCandidateLists();
    });
  });

  // ==========================================================================
  // Entities tab — table
  // ==========================================================================
  async function fetchEntities() {
    loading.style.display = "";
    emptyMsg.style.display = "none";
    tbody.innerHTML = "";

    const params = new URLSearchParams();
    params.set("page", currentPage);
    const q = searchInput.value.trim();
    if (q) params.set("q", q);
    const t = typeSelect.value;
    if (t) params.set("type", t);
    params.set("sort", sortSelect.value);

    try {
      const resp = await fetch("/entities/list/?" + params.toString());
      const data = await resp.json();
      renderTable(data.items);
      populateTypeFilter(data.type_counts);
      updatePager(data);
    } catch (err) {
      console.error("Entity fetch error", err);
      tbody.innerHTML = `<tr><td colspan="4" class="ent-error">Failed to load entities.</td></tr>`;
    } finally {
      loading.style.display = "none";
    }
  }

  function renderTable(items) {
    if (!items.length) { emptyMsg.style.display = ""; return; }
    tbody.innerHTML = items.map((it) => {
      const text = esc(it.entity_text);
      return `<tr class="ent-row" data-entity="${esc(it.entity_text)}">
        <td class="ent-cell-text">${text}</td>
        <td class="ent-cell-type">${typeTag(it.entity_type)}</td>
        <td class="ent-cell-count">${it.total_count}</td>
        <td class="ent-cell-docs">${it.doc_count}</td>
      </tr>`;
    }).join("");
  }

  function populateTypeFilter(counts) {
    if (!counts || typeSelect.options.length > 1) return;
    const sorted = Object.entries(counts).sort((a, b) => b[1] - a[1]);
    for (const [t, n] of sorted) {
      const label = TYPE_LABELS[t] || t;
      const opt = document.createElement("option");
      opt.value = t;
      opt.textContent = `${label} (${n})`;
      typeSelect.appendChild(opt);
    }
  }

  function updatePager(data) {
    const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
    pageInfo.textContent = `Page ${data.page} of ${totalPages} (${data.total} results)`;
    prevBtn.disabled = data.page <= 1;
    nextBtn.disabled = !data.has_more;
  }

  function resetAndFetch() { currentPage = 1; fetchEntities(); }

  searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(resetAndFetch, 300);
  });
  typeSelect.addEventListener("change", resetAndFetch);
  sortSelect.addEventListener("change", resetAndFetch);
  prevBtn.addEventListener("click", () => { if (currentPage > 1) { currentPage--; fetchEntities(); } });
  nextBtn.addEventListener("click", () => { currentPage++; fetchEntities(); });

  // ==========================================================================
  // Entity detail panel
  // ==========================================================================
  let currentEntity = null;

  tbody.addEventListener("click", (e) => {
    const row = e.target.closest(".ent-row");
    if (!row) return;
    const entity = row.dataset.entity;
    openEntityDetail(entity);
  });

  function openEntityDetail(entity) {
    currentEntity = entity;
    detailTitle.textContent = entity;
    detailPanel.style.display = "";

    $$(".ent-detail-tab").forEach((t) => t.classList.remove("active"));
    $$(".ent-detail-tab")[0].classList.add("active");
    $("#entDetailOccurrences").style.display = "";
    $("#entDetailMatches").style.display = "none";

    fetchOccurrences(entity);
    fetchRedactionMatches(entity);
  }

  // detail sub-tabs
  $$(".ent-detail-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".ent-detail-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const which = tab.dataset.dtab;
      $("#entDetailOccurrences").style.display = which === "occurrences" ? "" : "none";
      $("#entDetailMatches").style.display = which === "matches" ? "" : "none";
    });
  });

  detailClose.addEventListener("click", () => {
    detailPanel.style.display = "none";
    currentEntity = null;
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      if (!viewerOverlay.classList.contains("hidden")) { closeViewer(); return; }
      detailPanel.style.display = "none";
      currentEntity = null;
    }
  });

  // ==========================================================================
  // Occurrences sub-tab
  // ==========================================================================
  async function fetchOccurrences(entity) {
    const body = $("#entDetailOccurrences");
    body.innerHTML = "<p class='ent-loading'>Loading occurrences...</p>";
    try {
      const resp = await fetch("/entities/detail/" + encodeURIComponent(entity) + "/?bbox=1");
      const data = await resp.json();
      renderOccurrences(data, body);
    } catch (err) {
      body.innerHTML = "<p class='ent-error'>Failed to load occurrences.</p>";
    }
  }

  function renderOccurrences(data, container) {
    if (!data.occurrences || !data.occurrences.length) {
      container.innerHTML = "<p>No occurrences found.</p>";
      return;
    }
    const rows = data.occurrences.map((o) => {
      const hasBbox = o.bboxes && o.bboxes.length;
      const bboxInfo = hasBbox ? `<span class="ent-occ-bbox">${o.bboxes.length} loc(s)</span>` : "";
      return `<tr class="ent-occ-row" data-doc="${esc(o.extracted_document__doc_id)}" data-page="${o.page_num}">
        <td>${esc(o.extracted_document__doc_id)}</td>
        <td>${typeTag(o.entity_type)}</td>
        <td>p${o.page_num}</td>
        <td>${o.count}</td>
        <td>${bboxInfo}</td>
      </tr>`;
    }).join("");
    container.innerHTML = `
      <p>${data.occurrences.length} occurrence(s) across documents:</p>
      <table class="ent-detail-table">
        <thead><tr><th>Document</th><th>Type</th><th>Page</th><th>Count</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  // ==========================================================================
  // Redaction Matches sub-tab
  // ==========================================================================
  async function fetchRedactionMatches(entity) {
    const body = $("#entDetailMatches");
    body.innerHTML = "<p class='ent-loading'>Loading redaction matches...</p>";
    try {
      const resp = await fetch("/entities/redaction-matches/" + encodeURIComponent(entity) + "/");
      const data = await resp.json();
      renderRedactionMatches(data, body);
    } catch (err) {
      body.innerHTML = "<p class='ent-error'>Failed to load matches.</p>";
    }
  }

  function renderRedactionMatches(data, container) {
    if (!data.items || !data.items.length) {
      container.innerHTML = `<p class="ent-empty">No redaction matches found for "${esc(data.entity_text || "")}". Run batch matching first.</p>`;
      return;
    }

    const rows = data.items.map((m) => {
      const errPct = Math.abs(1 - m.width_ratio) * 100;
      const fitCol = errPct <= 3 ? "#2ecc71" : errPct <= 10 ? "#f1c40f" : "#e74c3c";
      const ctx = [];
      if (m.text_before) ctx.push(`...${esc(m.text_before)}`);
      ctx.push(`<span class="mat-redaction-gap">[REDACTED]</span>`);
      if (m.text_after) ctx.push(`${esc(m.text_after)}...`);

      return `<div class="ent-match-card" data-redaction-id="${m.redaction_id}">
        <div class="ent-match-header">
          <span class="mat-doc-label">${esc(m.doc_id)}</span>
          <span class="mat-page-label">p${m.page_num} r${m.redaction_index}</span>
          <span class="ent-match-rank">#${m.rank}</span>
          <span class="ent-match-score">Score: ${m.total_score}</span>
          <span class="rd-fit-indicator" style="--fit-col:${fitCol}">${m.width_ratio}x width</span>
        </div>
        <div class="mat-context">${ctx.join(" ")}</div>
        ${m.image_context ? `<img class="ent-match-thumb" src="/redactions-image/${esc(m.image_context)}" loading="lazy" />` : ""}
        <button class="btn btn-sm ent-match-view" data-rid="${m.redaction_id}" data-entity="${esc(data.entity_text)}" data-score="${m.total_score}" data-wr="${m.width_ratio}">View in context</button>
      </div>`;
    }).join("");

    container.innerHTML = `
      <p>${data.total} redaction(s) where "${esc(data.entity_text)}" is a candidate match:</p>
      ${rows}
      ${data.has_more ? `<p class="ent-match-more">Showing first ${data.items.length} of ${data.total}</p>` : ""}`;

    container.querySelectorAll(".ent-match-view").forEach((btn) => {
      btn.addEventListener("click", () => {
        openRedactionViewer(
          parseInt(btn.dataset.rid),
          btn.dataset.entity,
          parseFloat(btn.dataset.score),
          parseFloat(btn.dataset.wr)
        );
      });
    });
  }

  // ==========================================================================
  // Redaction viewer overlay (reuses rd-* CSS classes)
  // ==========================================================================
  const viewerOverlay = $("#entViewerOverlay");
  const viewerTitle = $("#entViewerTitle");
  const evViewer = $("#evViewer");
  const evViewerInner = $("#evViewerInner");
  const evPageImg = $("#evPageImg");
  const evBox = $("#evBox");

  let evScale = 1, evTx = 0, evTy = 0;
  let evBbox = null;
  let evCanvasEl = null;
  let evCurrentRedactionId = null;

  function evSetTransform(scale, tx, ty) {
    evScale = scale; evTx = tx; evTy = ty;
    evViewerInner.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    const slider = $("#evZoomSlider");
    const level = $("#evZoomLevel");
    if (slider) slider.value = Math.round(scale * 100);
    if (level) level.textContent = Math.round(scale * 100) + "%";
  }

  function evApplyZoom(mode) {
    if (!evBbox || !evPageImg.naturalWidth) return;
    evViewerInner.classList.remove("no-transition");
    const vw = evViewer.clientWidth;
    const vh = evViewer.clientHeight;
    const iw = evPageImg.naturalWidth;
    const ih = evPageImg.naturalHeight;

    const bx = evBbox.x0, by = evBbox.y0;
    const bw = evBbox.x1 - evBbox.x0, bh = evBbox.y1 - evBbox.y0;
    const bcx = bx + bw / 2, bcy = by + bh / 2;
    let scale, tx, ty;

    if (mode === "page") {
      scale = Math.min(vw / iw, vh / ih);
      tx = (vw - iw * scale) / 2;
      ty = (vh - ih * scale) / 2;
    } else {
      const pad = mode === "tight" ? 40 : 150;
      scale = Math.min(vw / (bw + pad * 2), vh / (bh + pad * 2));
      scale = Math.max(scale, Math.min(vw / iw, vh / ih));
      tx = vw / 2 - bcx * scale;
      ty = vh / 2 - bcy * scale;
      tx = Math.min(0, Math.max(vw - iw * scale, tx));
      ty = Math.min(0, Math.max(vh - ih * scale, ty));
    }

    evViewerInner.style.width = iw + "px";
    evViewerInner.style.height = ih + "px";
    evSetTransform(scale, tx, ty);

    evBox.style.left = bx + "px"; evBox.style.top = by + "px";
    evBox.style.width = bw + "px"; evBox.style.height = bh + "px";
    evBox.style.display = "block";

    [$("#evZoomTight"), $("#evZoomContext"), $("#evZoomPage")].forEach((b) => b && b.classList.remove("active"));
    const activeBtn = mode === "tight" ? "#evZoomTight" : mode === "context" ? "#evZoomContext" : "#evZoomPage";
    $(activeBtn)?.classList.add("active");
  }

  function evGetCanvas() {
    if (!evCanvasEl) {
      evCanvasEl = document.createElement("canvas");
      evCanvasEl.style.position = "absolute";
      evCanvasEl.style.left = "0";
      evCanvasEl.style.top = "0";
      evCanvasEl.style.pointerEvents = "none";
      evViewerInner.appendChild(evCanvasEl);
    }
    if (evPageImg.naturalWidth) {
      evCanvasEl.width = evPageImg.naturalWidth;
      evCanvasEl.height = evPageImg.naturalHeight;
      evCanvasEl.style.width = evPageImg.naturalWidth + "px";
      evCanvasEl.style.height = evPageImg.naturalHeight + "px";
    }
    return evCanvasEl;
  }

  function drawCandidateInRedaction(entityText, fontData) {
    if (!evBbox || !evPageImg.naturalWidth) return;
    const canvas = evGetCanvas();
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const p = fontData?.params || {};
    const scaleX = p.scale_x ?? 1.0;
    const letterSp = p.letter_spacing_px ?? 0;
    const wordSp = p.word_spacing_px ?? 0;
    const xOff = p.x_offset_px ?? 0;
    const yOff = p.y_offset_px ?? 0;
    const sizeScale = p.size_scale ?? 1;

    if (fontData && fontData.spans) {
      ctx.globalAlpha = 0.45;
      ctx.fillStyle = "#00cc44";
      ctx.textBaseline = "alphabetic";
      if (typeof ctx.letterSpacing !== "undefined") ctx.letterSpacing = letterSp + "px";
      if (typeof ctx.wordSpacing !== "undefined") ctx.wordSpacing = wordSp + "px";
      for (const span of fontData.spans) {
        const fInfo = fontData.font_map ? fontData.font_map[span.font_name] : null;
        const family = p.css_family || (fInfo ? fInfo.css_family : "serif");
        const wt = span.font_weight === "bold" ? "bold" : "normal";
        const st = span.font_style === "italic" ? "italic" : "normal";
        const fs = span.font_size_px * sizeScale;
        ctx.font = `${st} ${wt} ${fs}px ${family}`;
        let x = (span.origin_px ? span.origin_px[0] : span.bbox_px[0]) + xOff;
        let y = (span.origin_px ? span.origin_px[1] : span.bbox_px[3]) + yOff;
        if (Math.abs(scaleX - 1.0) > 0.001) {
          ctx.save(); ctx.translate(x, y); ctx.scale(scaleX, 1);
          ctx.fillText(span.text, 0, 0); ctx.restore();
        } else {
          ctx.fillText(span.text, x, y);
        }
      }
      if (typeof ctx.letterSpacing !== "undefined") ctx.letterSpacing = "0px";
      if (typeof ctx.wordSpacing !== "undefined") ctx.wordSpacing = "0px";
    }

    const bx = evBbox.x0, by = evBbox.y0;
    const bw = evBbox.x1 - evBbox.x0, bh = evBbox.y1 - evBbox.y0;
    const baseline = by + bh * 0.78;

    let cssFamily = "serif";
    let fontSize = bh * 0.7;
    let weight = "normal", style = "normal";

    if (fontData && fontData.spans && fontData.spans.length) {
      const sameLineSpans = fontData.spans.filter(
        (s) => s.origin_px && Math.abs(s.origin_px[1] - (by + bh * 0.75)) < bh
      );
      const ref = sameLineSpans[0] || fontData.spans[0];
      const fInfo = fontData.font_map ? fontData.font_map[ref.font_name] : null;
      cssFamily = p.css_family || (fInfo ? fInfo.css_family : "serif");
      fontSize = ref.font_size_px * sizeScale;
      weight = ref.font_weight === "bold" ? "bold" : "normal";
      style = ref.font_style === "italic" ? "italic" : "normal";
    }

    ctx.save();
    ctx.globalAlpha = 0.85;
    ctx.fillStyle = "#00e5ff";
    ctx.font = `${style} ${weight} ${fontSize}px ${cssFamily}`;
    ctx.textBaseline = "alphabetic";
    if (typeof ctx.letterSpacing !== "undefined") ctx.letterSpacing = letterSp + "px";
    if (typeof ctx.wordSpacing !== "undefined") ctx.wordSpacing = wordSp + "px";
    if (Math.abs(scaleX - 1.0) > 0.001) {
      ctx.translate(bx + 2, baseline); ctx.scale(scaleX, 1);
      ctx.fillText(entityText, 0, 0);
    } else {
      ctx.fillText(entityText, bx + 2, baseline);
    }
    if (typeof ctx.letterSpacing !== "undefined") ctx.letterSpacing = "0px";
    if (typeof ctx.wordSpacing !== "undefined") ctx.wordSpacing = "0px";
    ctx.restore();
  }

  async function openRedactionViewer(redactionId, entityText, score, widthRatio) {
    evCurrentRedactionId = redactionId;

    try {
      const resp = await fetch(`/redactions/${redactionId}/`);
      if (!resp.ok) return;
      const d = await resp.json();

      viewerTitle.textContent = `${d.doc_id} — Page ${d.page_num}, Redaction #${d.redaction_index}`;
      evBbox = {
        x0: d.bbox_x0_pixels, y0: d.bbox_y0_pixels,
        x1: d.bbox_x1_pixels, y1: d.bbox_y1_pixels,
      };

      evBox.style.display = "none";
      evPageImg.src = "";
      evViewerInner.style.transform = "";
      if (evCanvasEl) {
        const ctx = evCanvasEl.getContext("2d");
        ctx.clearRect(0, 0, evCanvasEl.width, evCanvasEl.height);
      }

      evPageImg.onload = async () => {
        evApplyZoom("context");

        let fontData = null;
        try {
          const faResp = await fetch(`/redactions/${redactionId}/font-analysis/`);
          if (faResp.ok) fontData = await faResp.json();
        } catch (e) { /* ignore */ }

        drawCandidateInRedaction(entityText, fontData);

        try {
          const foResp = await fetch(`/redactions/${redactionId}/font-optimize/`);
          if (foResp.ok) {
            const foData = await foResp.json();
            if (foData.best && fontData) {
              fontData.params = foData.best;
              drawCandidateInRedaction(entityText, fontData);
            }
          }
        } catch (e) { /* ignore */ }
      };
      evPageImg.src = `/redactions/${redactionId}/page-image/`;

      $("#evDetailBefore").textContent = d.text_before || "(none)";
      $("#evDetailAfter").textContent = d.text_after || "(none)";

      const fitEl = $("#evCandFit");
      if (fitEl) {
        const err = Math.abs(1 - widthRatio) * 100;
        const col = err <= 3 ? "#2ecc71" : err <= 10 ? "#f1c40f" : "#e74c3c";
        const label = err <= 3 ? "Excellent fit" : err <= 10 ? "Good fit" : "Poor fit";
        fitEl.innerHTML =
          `<strong style="color:#00e5ff">${esc(entityText)}</strong> ` +
          `<span class="rd-fit-indicator" style="--fit-col:${col}">${label}</span>` +
          ` <span class="rd-fit-ratio">${widthRatio}x width · score ${score}</span>`;
      }

      viewerOverlay.classList.remove("hidden");
    } catch (err) {
      console.error(err);
    }
  }

  function closeViewer() {
    viewerOverlay.classList.add("hidden");
    evPageImg.src = "";
    evBox.style.display = "none";
    evCurrentRedactionId = null;
  }

  // viewer event listeners
  $("#entViewerClose").addEventListener("click", closeViewer);
  viewerOverlay.addEventListener("click", (e) => { if (e.target === viewerOverlay) closeViewer(); });

  $("#evZoomTight")?.addEventListener("click", () => evApplyZoom("tight"));
  $("#evZoomContext")?.addEventListener("click", () => evApplyZoom("context"));
  $("#evZoomPage")?.addEventListener("click", () => evApplyZoom("page"));

  // zoom slider
  const evSlider = $("#evZoomSlider");
  if (evSlider) evSlider.addEventListener("input", () => {
    evViewerInner.classList.add("no-transition");
    const newScale = parseInt(evSlider.value) / 100;
    const vw = evViewer.clientWidth, vh = evViewer.clientHeight;
    const cx = vw / 2, cy = vh / 2;
    const ratio = newScale / evScale;
    evSetTransform(newScale, cx - ratio * (cx - evTx), cy - ratio * (cy - evTy));
  });

  // wheel zoom
  evViewer.addEventListener("wheel", (e) => {
    e.preventDefault();
    evViewerInner.classList.add("no-transition");
    const rect = evViewer.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const factor = e.deltaY > 0 ? 0.92 : 1.08;
    const newScale = Math.max(0.05, Math.min(10, evScale * factor));
    const ratio = newScale / evScale;
    evSetTransform(newScale, mx - ratio * (mx - evTx), my - ratio * (my - evTy));
  }, { passive: false });

  // drag to pan
  let _evDrag = false, _evDragX, _evDragY, _evDragTx, _evDragTy;
  evViewer.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    _evDrag = true; _evDragX = e.clientX; _evDragY = e.clientY;
    _evDragTx = evTx; _evDragTy = evTy;
    evViewerInner.classList.add("no-transition");
    evViewer.style.cursor = "grabbing";
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!_evDrag) return;
    evSetTransform(evScale, _evDragTx + e.clientX - _evDragX, _evDragTy + e.clientY - _evDragY);
  });
  window.addEventListener("mouseup", () => { if (_evDrag) { _evDrag = false; evViewer.style.cursor = ""; } });

  // touch: pinch zoom + pan
  let _evTouches = {}, _evPinchDist = 0, _evPinchMid = null, _evSingleTouch = null;
  evViewer.addEventListener("touchstart", (e) => {
    for (const t of e.changedTouches) _evTouches[t.identifier] = { x: t.clientX, y: t.clientY };
    const pts = Object.values(_evTouches);
    if (pts.length === 2) {
      _evPinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      _evPinchMid = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
    } else if (pts.length === 1) {
      _evSingleTouch = { x: e.touches[0].clientX, y: e.touches[0].clientY, tx: evTx, ty: evTy };
    }
  }, { passive: true });
  evViewer.addEventListener("touchmove", (e) => {
    for (const t of e.changedTouches) _evTouches[t.identifier] = { x: t.clientX, y: t.clientY };
    const pts = Object.values(_evTouches);
    evViewerInner.classList.add("no-transition");
    if (pts.length >= 2) {
      e.preventDefault();
      const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      const mid = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
      const rect = evViewer.getBoundingClientRect();
      const mx = mid.x - rect.left, my = mid.y - rect.top;
      const factor = dist / _evPinchDist;
      const newScale = Math.max(0.05, Math.min(10, evScale * factor));
      const ratio = newScale / evScale;
      evSetTransform(newScale,
        mx - ratio * (mx - evTx) + (mid.x - _evPinchMid.x),
        my - ratio * (my - evTy) + (mid.y - _evPinchMid.y));
      _evPinchDist = dist; _evPinchMid = mid;
    } else if (pts.length === 1 && _evSingleTouch) {
      e.preventDefault();
      evSetTransform(evScale,
        _evSingleTouch.tx + e.touches[0].clientX - _evSingleTouch.x,
        _evSingleTouch.ty + e.touches[0].clientY - _evSingleTouch.y);
    }
  }, { passive: false });
  evViewer.addEventListener("touchend", (e) => {
    for (const t of e.changedTouches) delete _evTouches[t.identifier];
    if (Object.keys(_evTouches).length === 0) _evSingleTouch = null;
  }, { passive: true });

  // ==========================================================================
  // Candidates tab
  // ==========================================================================
  const candContainer = $("#candLists");
  const candNameInput = $("#candNewListName");
  const candEntriesInput = $("#candNewListEntries");
  const candAddBtn = $("#candAddBtn");

  async function fetchCandidateLists() {
    candContainer.innerHTML = "<p class='ent-loading'>Loading lists...</p>";
    try {
      const resp = await fetch("/entities/candidates/");
      const data = await resp.json();
      renderCandidateLists(data.lists);
    } catch (err) {
      candContainer.innerHTML = "<p class='ent-error'>Failed to load candidate lists.</p>";
    }
  }

  function renderCandidateLists(lists) {
    if (!lists.length) {
      candContainer.innerHTML = "<p class='ent-empty'>No candidate lists loaded yet.</p>";
      return;
    }
    candContainer.innerHTML = lists.map((cl) => {
      const collapsed = cl.entries.slice(0, 12);
      const more = cl.entries.length - collapsed.length;
      const names = collapsed.map((n) =>
        `<span class="ent-cand-name">${esc(n)}</span>`
      ).join("");
      const moreTag = more > 0
        ? `<span class="ent-cand-more">+${more} more</span>`
        : "";
      return `<div class="ent-cand-card" data-id="${cl.id}">
        <div class="ent-cand-card-header">
          <h3>${esc(cl.name)}</h3>
          <span class="ent-cand-count">${cl.count} names</span>
          <button class="ent-cand-del btn btn-secondary btn-sm" data-id="${cl.id}">&times;</button>
        </div>
        <div class="ent-cand-names">${names}${moreTag}</div>
        <details class="ent-cand-full">
          <summary>Show all ${cl.count}</summary>
          <div class="ent-cand-full-list">${cl.entries.map((n) =>
            `<span class="ent-cand-name">${esc(n)}</span>`
          ).join("")}</div>
        </details>
      </div>`;
    }).join("");
  }

  candContainer.addEventListener("click", async (e) => {
    const delBtn = e.target.closest(".ent-cand-del");
    if (!delBtn) return;
    const id = delBtn.dataset.id;
    if (!confirm("Delete this candidate list?")) return;
    try {
      await fetch(`/entities/candidates/${id}/delete/`, { method: "DELETE" });
      fetchCandidateLists();
    } catch (err) {
      alert("Failed to delete list");
    }
  });

  candAddBtn.addEventListener("click", async () => {
    const name = candNameInput.value.trim();
    const raw = candEntriesInput.value.trim();
    if (!name || !raw) { alert("Enter a list name and at least one name."); return; }
    const entries = raw.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!entries.length) { alert("Enter at least one name."); return; }
    candAddBtn.disabled = true;
    candAddBtn.textContent = "Saving...";
    try {
      await fetch("/entities/candidates/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, entries }),
      });
      candNameInput.value = "";
      candEntriesInput.value = "";
      fetchCandidateLists();
    } catch (err) {
      alert("Failed to save list");
    } finally {
      candAddBtn.disabled = false;
      candAddBtn.textContent = "Save list";
    }
  });

  // ---- boot ----
  fetchEntities();
})();

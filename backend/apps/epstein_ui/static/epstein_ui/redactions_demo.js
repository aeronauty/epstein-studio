const grid = document.getElementById("rdGrid");
const moreBtn = document.getElementById("rdMore");
const sortSelect = document.getElementById("rdSort");
const methodSelect = document.getElementById("rdMethod");
const searchInput = document.getElementById("rdSearch");
const searchBtn = document.getElementById("rdSearchBtn");
const countSpan = document.getElementById("rdCount");
const overlay = document.getElementById("rdOverlay");
const closeBtn = document.getElementById("rdDetailClose");

const viewer = document.getElementById("rdViewer");
const viewerInner = document.getElementById("rdViewerInner");
const pageImg = document.getElementById("rdPageImg");
const boxEl = document.getElementById("rdBox");
const zoomTightBtn = document.getElementById("rdZoomTight");
const zoomContextBtn = document.getElementById("rdZoomContext");
const zoomPageBtn = document.getElementById("rdZoomPage");

let page = 1;
let loading = false;
let hasMore = true;

let currentBbox = null;
let currentZoom = "context";
let currentDetailId = null;
let fontOverlayActive = false;

let currentScale = 1;
let currentTx = 0;
let currentTy = 0;

const fontAnalyzeBtn = document.getElementById("rdFontAnalyze");
const fontOpacityWrap = document.getElementById("rdFontOpacityWrap");
const fontOpacityInput = document.getElementById("rdFontOpacity");
const fontSummaryEl = document.getElementById("rdFontSummary");
const zoomSlider = document.getElementById("rdZoomSlider");
const zoomLevelEl = document.getElementById("rdZoomLevel");

let _overlayCanvas = null;
let _overlayData = null;
let _overlayOpacity = 0.55;

function imgUrl(relPath) {
  if (!relPath) return "";
  return `/redactions-image/${relPath}`;
}

function setLoading(state) {
  loading = state;
  if (moreBtn) {
    moreBtn.disabled = state;
    moreBtn.textContent = state ? "Loading..." : "Load More";
  }
}

function createCard(item) {
  const card = document.createElement("div");
  card.className = "rd-card";
  card.dataset.id = item.id;

  const thumb = document.createElement("div");
  thumb.className = "rd-thumb";
  const src = item.image_context || item.image_tight;
  if (src) {
    const img = document.createElement("img");
    img.src = imgUrl(src);
    img.alt = `Redaction on page ${item.page_num}`;
    img.loading = "lazy";
    thumb.appendChild(img);
  } else {
    thumb.classList.add("rd-thumb-empty");
    thumb.textContent = "No image";
  }
  card.appendChild(thumb);

  const info = document.createElement("div");
  info.className = "rd-card-info";

  const title = document.createElement("div");
  title.className = "rd-card-title";
  title.textContent = `${item.doc_id} — p${item.page_num}`;
  info.appendChild(title);

  const meta = document.createElement("div");
  meta.className = "rd-card-meta";
  meta.innerHTML =
    `<span class="rd-tag">${item.detection_method}</span>` +
    `<span>${item.estimated_chars} chars</span>` +
    `<span>${item.width_points} × ${item.height_points} pt</span>`;
  info.appendChild(meta);

  if (item.text_before_snippet) {
    const snippet = document.createElement("div");
    snippet.className = "rd-card-snippet";
    snippet.textContent = item.text_before_snippet;
    info.appendChild(snippet);
  }

  card.appendChild(info);

  card.addEventListener("click", () => openDetail(item.id));
  return card;
}

async function loadPage() {
  if (loading || !hasMore) return;
  setLoading(true);
  try {
    const params = new URLSearchParams({
      page: page,
      sort: sortSelect ? sortSelect.value : "estimated_chars",
      q: searchInput ? searchInput.value.trim() : "",
      detection_method: methodSelect ? methodSelect.value : "",
    });
    const resp = await fetch(`/redactions-list/?${params}`);
    if (!resp.ok) throw new Error("Failed to load");
    const data = await resp.json();
    (data.items || []).forEach((item) => grid.appendChild(createCard(item)));
    hasMore = Boolean(data.has_more);
    if (countSpan && typeof data.total === "number") {
      countSpan.textContent = `(${data.total.toLocaleString()})`;
    }
    page += 1;
    if (moreBtn) moreBtn.classList.toggle("hidden", !hasMore);
  } catch (err) {
    console.error(err);
  } finally {
    setLoading(false);
  }
}

function resetAndLoad() {
  page = 1;
  hasMore = true;
  grid.innerHTML = "";
  loadPage();
}

// ---------------------------------------------------------------------------
// Zoom logic
// ---------------------------------------------------------------------------

function setTransform(scale, tx, ty) {
  currentScale = scale;
  currentTx = tx;
  currentTy = ty;
  viewerInner.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
  if (zoomSlider) zoomSlider.value = Math.round(scale * 100);
  if (zoomLevelEl) zoomLevelEl.textContent = Math.round(scale * 100) + "%";
}

function applyZoom(mode) {
  if (!currentBbox || !pageImg.naturalWidth) return;

  currentZoom = mode;
  viewerInner.classList.remove("no-transition");
  const vw = viewer.clientWidth;
  const vh = viewer.clientHeight;
  const iw = pageImg.naturalWidth;
  const ih = pageImg.naturalHeight;

  const bx = currentBbox.x0;
  const by = currentBbox.y0;
  const bw = currentBbox.x1 - currentBbox.x0;
  const bh = currentBbox.y1 - currentBbox.y0;
  const bcx = bx + bw / 2;
  const bcy = by + bh / 2;

  let scale, tx, ty;

  if (mode === "page") {
    scale = Math.min(vw / iw, vh / ih);
    tx = (vw - iw * scale) / 2;
    ty = (vh - ih * scale) / 2;
  } else {
    const pad = mode === "tight" ? 40 : 150;
    const regionW = bw + pad * 2;
    const regionH = bh + pad * 2;
    scale = Math.min(vw / regionW, vh / regionH);
    scale = Math.max(scale, Math.min(vw / iw, vh / ih));

    tx = vw / 2 - bcx * scale;
    ty = vh / 2 - bcy * scale;

    tx = Math.min(0, Math.max(vw - iw * scale, tx));
    ty = Math.min(0, Math.max(vh - ih * scale, ty));
  }

  viewerInner.style.width = iw + "px";
  viewerInner.style.height = ih + "px";
  setTransform(scale, tx, ty);

  boxEl.style.left = bx + "px";
  boxEl.style.top = by + "px";
  boxEl.style.width = bw + "px";
  boxEl.style.height = bh + "px";
  boxEl.style.display = "block";

  [zoomTightBtn, zoomContextBtn, zoomPageBtn].forEach((b) => b.classList.remove("active"));
  if (mode === "tight") zoomTightBtn.classList.add("active");
  else if (mode === "context") zoomContextBtn.classList.add("active");
  else zoomPageBtn.classList.add("active");
}

// ---------------------------------------------------------------------------
// Detail overlay
// ---------------------------------------------------------------------------

async function openDetail(id) {
  try {
    const resp = await fetch(`/redactions/${id}/`);
    if (!resp.ok) return;
    const d = await resp.json();

    document.getElementById("rdDetailTitle").textContent =
      `${d.doc_id} — Page ${d.page_num}, Redaction #${d.redaction_index}`;

    currentBbox = {
      x0: d.bbox_x0_pixels,
      y0: d.bbox_y0_pixels,
      x1: d.bbox_x1_pixels,
      y1: d.bbox_y1_pixels,
    };

    currentDetailId = id;
    clearFontOverlay();

    boxEl.style.display = "none";
    pageImg.src = "";
    viewerInner.style.transform = "";

    pageImg.onload = () => applyZoom("context");
    pageImg.src = `/redactions/${id}/page-image/`;

    document.getElementById("rdDetailBefore").textContent = d.text_before || "(none)";
    document.getElementById("rdDetailAfter").textContent = d.text_after || "(none)";

    const metaEl = document.getElementById("rdDetailMeta");
    metaEl.innerHTML = "";
    const pairs = [
      ["Detection", d.detection_method],
      ["Confidence", d.confidence],
      ["Est. chars", d.estimated_chars],
      ["Size (pt)", `${d.width_points} × ${d.height_points}`],
      ["Size (px)", `${d.width_pixels} × ${d.height_pixels}`],
      ["Font size nearby", d.font_size_nearby ?? "—"],
      ["Avg char width", d.avg_char_width ?? "—"],
      ["Ascender leak", d.has_ascender_leakage ? "Yes" : "No"],
      ["Descender leak", d.has_descender_leakage ? "Yes" : "No"],
      ["Multiline", d.is_multiline ? `Yes (group ${d.multiline_group_id}, line ${d.line_index_in_group})` : "No"],
      ["Run", `#${d.extraction_run_id} (${new Date(d.run_started_at).toLocaleDateString()})`],
    ];
    pairs.forEach(([label, value]) => {
      const row = document.createElement("div");
      row.className = "rd-meta-row";
      row.innerHTML = `<span class="rd-meta-label">${label}</span><span class="rd-meta-value">${value}</span>`;
      metaEl.appendChild(row);
    });

    overlay.classList.remove("hidden");
  } catch (err) {
    console.error(err);
  }
}

function closeDetail() {
  overlay.classList.add("hidden");
  pageImg.src = "";
  boxEl.style.display = "none";
  clearFontOverlay();
  currentDetailId = null;
}

// ---------------------------------------------------------------------------
// Font analysis overlay (canvas-based for precise baseline alignment)
// ---------------------------------------------------------------------------

function _getOverlayCanvas() {
  if (!_overlayCanvas) {
    _overlayCanvas = document.createElement("canvas");
    _overlayCanvas.style.position = "absolute";
    _overlayCanvas.style.left = "0";
    _overlayCanvas.style.top = "0";
    _overlayCanvas.style.pointerEvents = "none";
    viewerInner.appendChild(_overlayCanvas);
  }
  if (pageImg.naturalWidth) {
    _overlayCanvas.width = pageImg.naturalWidth;
    _overlayCanvas.height = pageImg.naturalHeight;
    _overlayCanvas.style.width = pageImg.naturalWidth + "px";
    _overlayCanvas.style.height = pageImg.naturalHeight + "px";
  }
  return _overlayCanvas;
}

function _drawOverlay() {
  if (!_overlayData) return;
  const canvas = _getOverlayCanvas();
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const { spans, font_map, params } = _overlayData;
  ctx.globalAlpha = _overlayOpacity;
  ctx.fillStyle = "#00cc44";
  ctx.textBaseline = "alphabetic";

  const scaleX = params?.scale_x ?? 1.0;
  const wordSp = params?.word_spacing_px ?? 0;
  const letterSp = params?.letter_spacing_px ?? 0;
  const xOff = params?.x_offset_px ?? 0;
  const yOff = params?.y_offset_px ?? 0;

  for (const span of spans) {
    const fontInfo = font_map ? font_map[span.font_name] : null;
    const cssFamily = params?.css_family || (fontInfo ? fontInfo.css_family : "serif");
    const weight = span.font_weight === "bold" ? "bold" : "normal";
    const style = span.font_style === "italic" ? "italic" : "normal";
    const fontSize = span.font_size_px * (params?.size_scale ?? 1);

    ctx.font = `${style} ${weight} ${fontSize}px ${cssFamily}`;
    if (typeof ctx.letterSpacing !== "undefined") ctx.letterSpacing = letterSp + "px";
    if (typeof ctx.wordSpacing !== "undefined") ctx.wordSpacing = wordSp + "px";

    let x, y;
    if (span.origin_px) {
      x = span.origin_px[0] + xOff;
      y = span.origin_px[1] + yOff;
    } else {
      x = span.bbox_px[0] + xOff;
      y = span.bbox_px[3] + yOff;
    }

    if (Math.abs(scaleX - 1.0) > 0.001) {
      ctx.save();
      ctx.translate(x, y);
      ctx.scale(scaleX, 1);
      ctx.fillText(span.text, 0, 0);
      ctx.restore();
    } else {
      ctx.fillText(span.text, x, y);
    }
  }

  if (typeof ctx.letterSpacing !== "undefined") ctx.letterSpacing = "0px";
  if (typeof ctx.wordSpacing !== "undefined") ctx.wordSpacing = "0px";
}

function clearFontOverlay() {
  if (_overlayCanvas) {
    const ctx = _overlayCanvas.getContext("2d");
    ctx.clearRect(0, 0, _overlayCanvas.width, _overlayCanvas.height);
  }
  _overlayData = null;
  fontOverlayActive = false;
  if (fontAnalyzeBtn) {
    fontAnalyzeBtn.textContent = "Analyze Font";
    fontAnalyzeBtn.classList.remove("active");
  }
  if (fontOpacityWrap) fontOpacityWrap.classList.add("hidden");
  if (fontSummaryEl) {
    fontSummaryEl.classList.add("hidden");
    fontSummaryEl.innerHTML = "";
  }
  const optResultsEl = document.getElementById("rdOptResults");
  if (optResultsEl) { optResultsEl.classList.add("hidden"); optResultsEl.innerHTML = ""; }
  const progressEl = document.getElementById("rdOptProgress");
  if (progressEl) progressEl.classList.add("hidden");
  const textResultsEl = document.getElementById("rdTextResults");
  if (textResultsEl) textResultsEl.classList.add("hidden");
  lastOptResults = {};
  hideCandidatePreview();
}

function renderFontOverlay(data) {
  clearFontOverlay();
  _overlayOpacity = fontOpacityInput ? parseFloat(fontOpacityInput.value) : 0.55;
  _overlayData = { spans: data.spans || [], font_map: data.font_map || {}, params: null };
  _drawOverlay();

  fontOverlayActive = true;
  if (fontAnalyzeBtn) {
    fontAnalyzeBtn.textContent = "Hide Font";
    fontAnalyzeBtn.classList.add("active");
  }
  if (fontOpacityWrap) fontOpacityWrap.classList.remove("hidden");

  if (fontSummaryEl) {
    const fonts = {};
    (data.spans || []).forEach((s) => {
      const key = s.font_name;
      if (!fonts[key]) {
        const info = data.font_map[key] || {};
        fonts[key] = {
          name: key,
          css: info.css_family || "serif",
          confidence: info.confidence || "fallback",
          size: s.font_size_pt,
          weight: s.font_weight,
          style: s.font_style,
          count: 0,
        };
      }
      fonts[key].count++;
    });
    const dominant = Object.values(fonts).sort((a, b) => b.count - a.count)[0];

    const confLabel = { exact: "High", pattern: "Medium", fallback: "Low" };
    const confClass = { exact: "rd-conf-high", pattern: "rd-conf-med", fallback: "rd-conf-low" };

    const parts = [];
    if (dominant) {
      parts.push(
        `<span class="rd-meta-label">Font</span><span class="rd-meta-value">${dominant.name}</span>`,
        `<span class="rd-meta-label">CSS Match</span><span class="rd-meta-value">${dominant.css}</span>`,
        `<span class="rd-meta-label">Certainty</span><span class="rd-meta-value"><span class="${confClass[dominant.confidence] || ""}">${confLabel[dominant.confidence] || dominant.confidence}</span></span>`,
        `<span class="rd-meta-label">Size</span><span class="rd-meta-value">${dominant.size} pt</span>`,
        `<span class="rd-meta-label">Weight</span><span class="rd-meta-value">${dominant.weight}</span>`,
        `<span class="rd-meta-label">Style</span><span class="rd-meta-value">${dominant.style}</span>`
      );
    }
    if (data.line_spacing_px != null)
      parts.push(`<span class="rd-meta-label">Line spacing</span><span class="rd-meta-value">${data.line_spacing_px} px</span>`);
    if (data.alignment)
      parts.push(`<span class="rd-meta-label">Alignment</span><span class="rd-meta-value">${data.alignment}</span>`);

    fontSummaryEl.innerHTML = parts.map((p) => `<div class="rd-meta-row">${p}</div>`).join("");
    fontSummaryEl.classList.remove("hidden");
  }
}

async function analyzeFont(id) {
  if (fontOverlayActive) {
    clearFontOverlay();
    return;
  }
  if (fontAnalyzeBtn) {
    fontAnalyzeBtn.textContent = "Analyzing…";
    fontAnalyzeBtn.disabled = true;
  }
  try {
    const resp = await fetch(`/redactions/${id}/font-analysis/`);
    if (!resp.ok) throw new Error("Font analysis failed");
    const data = await resp.json();
    lastFontAnalysisData = data;
    renderFontOverlay(data);
  } catch (err) {
    console.error(err);
    if (fontAnalyzeBtn) fontAnalyzeBtn.textContent = "Analyze Font";
  } finally {
    if (fontAnalyzeBtn) fontAnalyzeBtn.disabled = false;
  }
}

function updateFontOpacity() {
  _overlayOpacity = fontOpacityInput ? parseFloat(fontOpacityInput.value) : 0.55;
  if (_overlayData) _drawOverlay();
}

// ---------------------------------------------------------------------------
// Font identification (calls server per-char fingerprinting endpoint)
// ---------------------------------------------------------------------------

let lastFontAnalysisData = null;
let fontIdentifyRunning = false;

async function runFontIdentify() {
  if (!currentDetailId) return;
  if (fontIdentifyRunning) return;
  fontIdentifyRunning = true;

  const progressEl = document.getElementById("rdOptProgress");
  if (progressEl) { progressEl.textContent = "Identifying font..."; progressEl.classList.remove("hidden"); }

  if (!lastFontAnalysisData) {
    try {
      const resp = await fetch(`/redactions/${currentDetailId}/font-analysis/`);
      if (resp.ok) {
        lastFontAnalysisData = await resp.json();
        renderFontOverlay(lastFontAnalysisData);
      }
    } catch (e) { console.error(e); }
  }

  try {
    const resp = await fetch(`/redactions/${currentDetailId}/font-optimize/`);
    if (!resp.ok) throw new Error("Font identification failed");
    const data = await resp.json();

    if (progressEl) progressEl.classList.add("hidden");
    renderIdentifyResults(data);

    if (data.best && lastFontAnalysisData) {
      applyOptResult(data.best);
    }
  } catch (err) {
    console.error(err);
    if (progressEl) { progressEl.textContent = "Font identification failed."; }
  } finally {
    fontIdentifyRunning = false;
  }
}

// ---------------------------------------------------------------------------
// Font identification results rendering + apply
// ---------------------------------------------------------------------------

let lastOptResults = {};

function renderIdentifyResults(data) {
  const el = document.getElementById("rdOptResults");
  if (!el) return;
  el.innerHTML = "";
  el.classList.remove("hidden");

  const optimized = data.all_optimized || [];
  const allCandidates = data.candidates || [];

  if (!optimized.length) {
    el.textContent = "No font matches found.";
    return;
  }

  const section = document.createElement("div");
  section.className = "rd-opt-section";

  const heading = document.createElement("div");
  heading.className = "rd-opt-heading";
  heading.textContent = `Per-character fingerprint matching (${data.profile_chars || "?"} unique chars)`;
  section.appendChild(heading);

  optimized.forEach((r, idx) => {
    const row = document.createElement("div");
    row.className = "rd-meta-row" + (idx === 0 ? " rd-opt-winner" : "");
    const sxLabel = r.scale_x != null && Math.abs(r.scale_x - 1) > 0.001 ? ` · sX:${r.scale_x}` : "";
    const wsLabel = r.word_spacing_px != null && Math.abs(r.word_spacing_px) > 0.01 ? ` · ws:${r.word_spacing_px}px` : "";
    const boldLabel = r.is_bold ? " [B]" : "";
    const italicLabel = r.is_italic ? " [I]" : "";
    row.innerHTML =
      `<span class="rd-meta-label">${r.font_name}${boldLabel}${italicLabel}</span>` +
      `<span class="rd-meta-value">` +
        `RMSE: ${r.rmse} &middot; ` +
        `${r.font_size_px}px &middot; ` +
        `ls: ${r.letter_spacing_px}px` +
        sxLabel + wsLabel +
      `</span>`;

    const applyBtn = document.createElement("button");
    applyBtn.className = "btn btn-secondary rd-opt-apply";
    applyBtn.textContent = "Apply";
    applyBtn.addEventListener("click", () => applyOptResult(r));
    row.appendChild(applyBtn);
    section.appendChild(row);
  });

  if (allCandidates.length > optimized.length) {
    const extra = document.createElement("div");
    extra.className = "rd-opt-extra";
    const others = allCandidates.slice(optimized.length).map(
      (c) => `${c.font_name}: ${c.rmse}`
    ).join(", ");
    extra.textContent = `Other candidates: ${others}`;
    section.appendChild(extra);
  }

  el.appendChild(section);
}

function applyOptResult(result) {
  if (!lastFontAnalysisData) return;
  _overlayOpacity = fontOpacityInput ? parseFloat(fontOpacityInput.value) : 0.55;
  _overlayData = {
    spans: lastFontAnalysisData.spans || [],
    font_map: lastFontAnalysisData.font_map || {},
    params: result,
  };
  _drawOverlay();

  fontOverlayActive = true;
  if (fontAnalyzeBtn) {
    fontAnalyzeBtn.textContent = "Hide Font";
    fontAnalyzeBtn.classList.add("active");
  }
  if (fontOpacityWrap) fontOpacityWrap.classList.remove("hidden");
}

// ---------------------------------------------------------------------------
// Text identification
// ---------------------------------------------------------------------------

let textIdentifyRunning = false;

async function runTextIdentify(extraCandidates) {
  if (!currentDetailId) return;
  if (textIdentifyRunning) return;
  textIdentifyRunning = true;

  const progressEl = document.getElementById("rdOptProgress");
  if (progressEl) { progressEl.textContent = "Identifying text..."; progressEl.classList.remove("hidden"); }

  if (!lastFontAnalysisData) {
    try {
      const faResp = await fetch(`/redactions/${currentDetailId}/font-analysis/`);
      if (faResp.ok) {
        lastFontAnalysisData = await faResp.json();
        renderFontOverlay(lastFontAnalysisData);
      }
    } catch (e) { console.error(e); }
  }

  let url = `/redactions/${currentDetailId}/text-candidates/`;
  const candidatesInput = document.getElementById("rdCustomCandidates");
  const parts = [];
  if (candidatesInput && candidatesInput.value.trim()) {
    parts.push(candidatesInput.value.trim());
  }
  if (extraCandidates) parts.push(extraCandidates);
  if (parts.length) {
    url += `?candidates=${encodeURIComponent(parts.join(","))}`;
  }

  try {
    const resp = await fetch(url);
    if (!resp.ok) throw new Error("Text identification failed");
    const data = await resp.json();

    if (progressEl) progressEl.classList.add("hidden");
    renderTextResults(data);
    initCandidatePreview(data);
  } catch (err) {
    console.error(err);
    if (progressEl) { progressEl.textContent = "Text identification failed."; }
  } finally {
    textIdentifyRunning = false;
  }
}

function renderTextResults(data) {
  const container = document.getElementById("rdTextResults");
  if (!container) return;
  container.classList.remove("hidden");

  const gapEl = document.getElementById("rdTextGap");
  const leakEl = document.getElementById("rdTextLeakage");
  const candEl = document.getElementById("rdTextCandidates");

  // Gap predictions
  if (gapEl) {
    gapEl.innerHTML = "";
    const heading = document.createElement("div");
    heading.className = "rd-text-heading";
    heading.textContent = "Predicted gap type";
    gapEl.appendChild(heading);

    const preds = data.gap_predictions || [];
    if (!preds.length) {
      gapEl.innerHTML += '<div class="rd-gap-tag rd-gap-tag-low">Unknown</div>';
    } else {
      preds.forEach((p) => {
        const cls = p.confidence >= 0.5 ? "rd-gap-tag" : "rd-gap-tag rd-gap-tag-low";
        const tag = document.createElement("span");
        tag.className = cls;
        tag.textContent = `${p.entity_type} (${Math.round(p.confidence * 100)}%)`;
        gapEl.appendChild(tag);
        const reason = document.createElement("span");
        reason.className = "rd-gap-reason";
        reason.textContent = p.reason;
        gapEl.appendChild(reason);
        gapEl.appendChild(document.createElement("br"));
      });
    }

    if (data.font_identified) {
      const info = document.createElement("div");
      info.className = "rd-char-range";
      info.textContent = `Font: ${data.font_identified} at ${data.font_size_pt}pt`;
      if (data.estimated_char_range) {
        info.textContent += ` · Est. ${data.estimated_char_range[0]}–${data.estimated_char_range[1]} chars`;
      }
      info.textContent += ` · Width: ${data.redaction_width_pt}pt`;
      gapEl.appendChild(info);
    }
  }

  // Leakage
  if (leakEl) {
    leakEl.innerHTML = "";
    const leakage = data.leakage || {};
    const ascFrags = leakage.ascender_fragments || [];
    const descFrags = leakage.descender_fragments || [];

    if (ascFrags.length || descFrags.length) {
      const heading = document.createElement("div");
      heading.className = "rd-text-heading";
      heading.textContent = "Leakage detection";
      leakEl.appendChild(heading);

      const bar = document.createElement("div");
      bar.className = "rd-leakage-bar";

      if (ascFrags.length) {
        const label = document.createElement("span");
        label.className = "rd-leakage-frag";
        label.textContent = `Ascender: ${ascFrags.length} fragment${ascFrags.length > 1 ? "s" : ""}`;
        ascFrags.forEach((f) => {
          label.textContent += ` [pos ~${f.position_estimate}]`;
        });
        bar.appendChild(label);
      }
      if (descFrags.length) {
        const label = document.createElement("span");
        label.className = "rd-leakage-frag";
        label.textContent = `Descender: ${descFrags.length} fragment${descFrags.length > 1 ? "s" : ""}`;
        descFrags.forEach((f) => {
          label.textContent += ` [pos ~${f.position_estimate}]`;
        });
        bar.appendChild(label);
      }
      leakEl.appendChild(bar);
    }
  }

  // Candidates table
  if (candEl) {
    candEl.innerHTML = "";
    const allCands = [...(data.candidates || []), ...(data.other_candidates || [])];

    if (!allCands.length) {
      candEl.innerHTML = '<div class="rd-text-heading">No candidates scored</div><div style="font-size:12px;color:var(--muted)">Run batch NER or enter custom candidates above.</div>';
      return;
    }

    const heading = document.createElement("div");
    heading.className = "rd-text-heading";
    heading.textContent = `Candidates (${data.total_candidates_checked} checked, ${(data.candidates || []).length} fit width)`;
    candEl.appendChild(heading);

    const table = document.createElement("table");
    table.className = "rd-cand-table";

    const thead = document.createElement("thead");
    thead.innerHTML = "<tr><th>Candidate</th><th>Score</th><th>Width</th><th>NLP</th><th>Leak</th><th>Freq</th></tr>";
    table.appendChild(thead);

    const tbody = document.createElement("tbody");
    const maxScore = allCands.length ? Math.max(...allCands.map((c) => c.score), 0.01) : 1;

    allCands.slice(0, 30).forEach((c) => {
      const tr = document.createElement("tr");
      const barW = Math.round((c.score / maxScore) * 60);
      tr.innerHTML =
        `<td>${escapeHtml(c.text)}</td>` +
        `<td class="rd-cand-score"><span class="rd-cand-bar" style="width:${barW}px"></span>${c.score}</td>` +
        `<td>${c.width_fit > 0 ? c.width_ratio + "x" : "<span style='color:var(--muted)'>—</span>"}</td>` +
        `<td>${c.nlp_score}</td>` +
        `<td>${c.leakage_score}</td>` +
        `<td>${c.corpus_freq}${c.in_same_doc ? " *" : ""}</td>`;
      tbody.appendChild(tr);
    });

    table.appendChild(tbody);
    candEl.appendChild(table);
  }
}

function escapeHtml(str) {
  const div = document.createElement("div");
  div.textContent = str;
  return div.innerHTML;
}

// ---------------------------------------------------------------------------
// Candidate preview overlay (render candidate text in redaction bbox)
// ---------------------------------------------------------------------------

let _candPreviewData = null; // { candidates, fontInfo, bbox }
let _candPreviewIdx = 0;

function initCandidatePreview(textData) {
  const allCands = [...(textData.candidates || []), ...(textData.other_candidates || [])];
  if (!allCands.length || !currentBbox) {
    hideCandidatePreview();
    return;
  }

  _candPreviewData = {
    candidates: allCands.slice(0, 20),
    fontName: textData.font_identified,
    fontSizePt: textData.font_size_pt,
    widthPt: textData.redaction_width_pt,
    preciseGapPt: textData.precise_gap_pt,
  };
  _candPreviewIdx = 0;

  const select = document.getElementById("rdCandSelect");
  if (select) {
    select.innerHTML = "";
    _candPreviewData.candidates.forEach((c, i) => {
      const opt = document.createElement("option");
      opt.value = i;
      opt.textContent = `#${i + 1} ${c.text} (${c.score})`;
      select.appendChild(opt);
    });
  }

  const previewEl = document.getElementById("rdCandPreview");
  if (previewEl) previewEl.classList.remove("hidden");

  drawCandidatePreview();
}

function hideCandidatePreview() {
  _candPreviewData = null;
  const previewEl = document.getElementById("rdCandPreview");
  if (previewEl) previewEl.classList.add("hidden");
}

function drawCandidatePreview() {
  if (!_candPreviewData || !currentBbox || !pageImg.naturalWidth) return;

  if (_overlayData) _drawOverlay();
  else {
    const canvas = _getOverlayCanvas();
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
  }

  const canvas = _getOverlayCanvas();
  const ctx = canvas.getContext("2d");

  const cand = _candPreviewData.candidates[_candPreviewIdx];
  if (!cand) return;

  const bbox = currentBbox;
  const bx = bbox.x0;
  const by = bbox.y0;
  const bw = bbox.x1 - bbox.x0;
  const bh = bbox.y1 - bbox.y0;

  let cssFamily = "serif";
  let fontWeight = "normal";
  let fontStyle = "normal";
  let fontSize = bh * 0.7;

  if (_overlayData && _overlayData.spans && _overlayData.spans.length) {
    const sameLineSpans = _overlayData.spans.filter(
      (s) => s.origin_px && Math.abs(s.origin_px[1] - (by + bh * 0.75)) < bh
    );
    const refSpan = sameLineSpans[0] || _overlayData.spans[0];
    const fontInfo = _overlayData.font_map ? _overlayData.font_map[refSpan.font_name] : null;
    cssFamily = (_overlayData.params && _overlayData.params.css_family) ||
                (fontInfo ? fontInfo.css_family : "serif");
    fontWeight = refSpan.font_weight === "bold" ? "bold" : "normal";
    fontStyle = refSpan.font_style === "italic" ? "italic" : "normal";
    fontSize = refSpan.font_size_px * (_overlayData.params?.size_scale ?? 1);
  } else if (_candPreviewData.fontSizePt) {
    const scale = pageImg.naturalWidth / (pageImg.naturalWidth / (150 / 72));
    fontSize = _candPreviewData.fontSizePt * (150 / 72);
  }

  const baseline = by + bh * 0.78;

  ctx.save();
  ctx.globalAlpha = 0.85;
  ctx.fillStyle = "#00e5ff";
  ctx.font = `${fontStyle} ${fontWeight} ${fontSize}px ${cssFamily}`;
  ctx.textBaseline = "alphabetic";

  if (_overlayData && _overlayData.params) {
    const p = _overlayData.params;
    if (typeof ctx.letterSpacing !== "undefined")
      ctx.letterSpacing = (p.letter_spacing_px || 0) + "px";
    if (typeof ctx.wordSpacing !== "undefined")
      ctx.wordSpacing = (p.word_spacing_px || 0) + "px";
    const scaleX = p.scale_x ?? 1.0;
    if (Math.abs(scaleX - 1.0) > 0.001) {
      ctx.translate(bx + 2, baseline);
      ctx.scale(scaleX, 1);
      ctx.fillText(cand.text, 0, 0);
    } else {
      ctx.fillText(cand.text, bx + 2, baseline);
    }
  } else {
    ctx.fillText(cand.text, bx + 2, baseline);
  }

  if (typeof ctx.letterSpacing !== "undefined") ctx.letterSpacing = "0px";
  if (typeof ctx.wordSpacing !== "undefined") ctx.wordSpacing = "0px";
  ctx.restore();

  const fitEl = document.getElementById("rdCandFit");
  if (fitEl && cand.width_ratio) {
    const err = Math.abs(1 - cand.width_ratio) * 100;
    const col = err <= 3 ? "#2ecc71" : err <= 10 ? "#f1c40f" : "#e74c3c";
    const label = err <= 3 ? "Excellent fit" : err <= 10 ? "Good fit" : "Poor fit";
    fitEl.innerHTML = `<span class="rd-fit-indicator" style="--fit-col:${col}">${label}</span>` +
      ` <span class="rd-fit-ratio">${cand.width_ratio}x width · score ${cand.score}</span>`;
  }
}

// Candidate preview navigation
const _candSelectEl = document.getElementById("rdCandSelect");
const _candPrevBtn = document.getElementById("rdCandPrev");
const _candNextBtn = document.getElementById("rdCandNext");

if (_candSelectEl) _candSelectEl.addEventListener("change", () => {
  _candPreviewIdx = parseInt(_candSelectEl.value) || 0;
  drawCandidatePreview();
});
if (_candPrevBtn) _candPrevBtn.addEventListener("click", () => {
  if (_candPreviewData && _candPreviewIdx > 0) {
    _candPreviewIdx--;
    if (_candSelectEl) _candSelectEl.value = _candPreviewIdx;
    drawCandidatePreview();
  }
});
if (_candNextBtn) _candNextBtn.addEventListener("click", () => {
  if (_candPreviewData && _candPreviewIdx < _candPreviewData.candidates.length - 1) {
    _candPreviewIdx++;
    if (_candSelectEl) _candSelectEl.value = _candPreviewIdx;
    drawCandidatePreview();
  }
});

// ---------------------------------------------------------------------------
// Event listeners
// ---------------------------------------------------------------------------

if (closeBtn) closeBtn.addEventListener("click", closeDetail);
if (overlay)
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeDetail();
  });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !overlay.classList.contains("hidden")) closeDetail();
});

if (zoomTightBtn) zoomTightBtn.addEventListener("click", () => applyZoom("tight"));
if (zoomContextBtn) zoomContextBtn.addEventListener("click", () => applyZoom("context"));
if (zoomPageBtn) zoomPageBtn.addEventListener("click", () => applyZoom("page"));

if (fontAnalyzeBtn) fontAnalyzeBtn.addEventListener("click", () => {
  if (currentDetailId) analyzeFont(currentDetailId);
});
if (fontOpacityInput) fontOpacityInput.addEventListener("input", updateFontOpacity);

const identifyFontBtn = document.getElementById("rdIdentifyFont");
if (identifyFontBtn) identifyFontBtn.addEventListener("click", runFontIdentify);

const identifyTextBtn = document.getElementById("rdIdentifyText");
if (identifyTextBtn) identifyTextBtn.addEventListener("click", () => runTextIdentify());

const customCandBtn = document.getElementById("rdCustomCandidatesBtn");
if (customCandBtn) customCandBtn.addEventListener("click", () => runTextIdentify());

const customCandInput = document.getElementById("rdCustomCandidates");
if (customCandInput) customCandInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter") runTextIdentify();
});

// ---------------------------------------------------------------------------
// Zoom slider
// ---------------------------------------------------------------------------

if (zoomSlider) zoomSlider.addEventListener("input", () => {
  viewerInner.classList.add("no-transition");
  const newScale = parseInt(zoomSlider.value) / 100;
  const vw = viewer.clientWidth;
  const vh = viewer.clientHeight;
  const cx = vw / 2;
  const cy = vh / 2;
  const ratio = newScale / currentScale;
  setTransform(newScale, cx - ratio * (cx - currentTx), cy - ratio * (cy - currentTy));
});

// ---------------------------------------------------------------------------
// Wheel zoom (centered on cursor)
// ---------------------------------------------------------------------------

viewer.addEventListener("wheel", (e) => {
  e.preventDefault();
  viewerInner.classList.add("no-transition");
  const rect = viewer.getBoundingClientRect();
  const mx = e.clientX - rect.left;
  const my = e.clientY - rect.top;
  const factor = e.deltaY > 0 ? 0.92 : 1.08;
  const newScale = Math.max(0.05, Math.min(10, currentScale * factor));
  const ratio = newScale / currentScale;
  setTransform(newScale, mx - ratio * (mx - currentTx), my - ratio * (my - currentTy));
}, { passive: false });

// ---------------------------------------------------------------------------
// Drag to pan
// ---------------------------------------------------------------------------

let _isDragging = false;
let _dragStartX, _dragStartY, _dragStartTx, _dragStartTy;

viewer.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  _isDragging = true;
  _dragStartX = e.clientX;
  _dragStartY = e.clientY;
  _dragStartTx = currentTx;
  _dragStartTy = currentTy;
  viewerInner.classList.add("no-transition");
  viewer.style.cursor = "grabbing";
  e.preventDefault();
});

window.addEventListener("mousemove", (e) => {
  if (!_isDragging) return;
  setTransform(
    currentScale,
    _dragStartTx + e.clientX - _dragStartX,
    _dragStartTy + e.clientY - _dragStartY
  );
});

window.addEventListener("mouseup", () => {
  if (!_isDragging) return;
  _isDragging = false;
  viewer.style.cursor = "";
});

// ---------------------------------------------------------------------------
// Touch: pinch zoom + single-finger pan
// ---------------------------------------------------------------------------

let _activeTouches = {};
let _lastPinchDist = 0;
let _lastPinchMid = null;
let _singleTouchStart = null;

viewer.addEventListener("touchstart", (e) => {
  for (const t of e.changedTouches) _activeTouches[t.identifier] = { x: t.clientX, y: t.clientY };
  const pts = Object.values(_activeTouches);
  if (pts.length === 2) {
    _lastPinchDist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    _lastPinchMid = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
  } else if (pts.length === 1) {
    _singleTouchStart = { x: e.touches[0].clientX, y: e.touches[0].clientY, tx: currentTx, ty: currentTy };
  }
}, { passive: true });

viewer.addEventListener("touchmove", (e) => {
  for (const t of e.changedTouches) _activeTouches[t.identifier] = { x: t.clientX, y: t.clientY };
  const pts = Object.values(_activeTouches);
  viewerInner.classList.add("no-transition");

  if (pts.length >= 2) {
    e.preventDefault();
    const dist = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
    const mid = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
    const rect = viewer.getBoundingClientRect();
    const mx = mid.x - rect.left;
    const my = mid.y - rect.top;
    const factor = dist / _lastPinchDist;
    const newScale = Math.max(0.05, Math.min(10, currentScale * factor));
    const ratio = newScale / currentScale;
    setTransform(
      newScale,
      mx - ratio * (mx - currentTx) + (mid.x - _lastPinchMid.x),
      my - ratio * (my - currentTy) + (mid.y - _lastPinchMid.y)
    );
    _lastPinchDist = dist;
    _lastPinchMid = mid;
  } else if (pts.length === 1 && _singleTouchStart) {
    e.preventDefault();
    const dx = e.touches[0].clientX - _singleTouchStart.x;
    const dy = e.touches[0].clientY - _singleTouchStart.y;
    setTransform(currentScale, _singleTouchStart.tx + dx, _singleTouchStart.ty + dy);
  }
}, { passive: false });

viewer.addEventListener("touchend", (e) => {
  for (const t of e.changedTouches) delete _activeTouches[t.identifier];
  if (Object.keys(_activeTouches).length === 0) _singleTouchStart = null;
}, { passive: true });

// ---------------------------------------------------------------------------
// Grid
// ---------------------------------------------------------------------------

if (moreBtn) moreBtn.addEventListener("click", loadPage);
if (sortSelect) sortSelect.addEventListener("change", resetAndLoad);
if (methodSelect) methodSelect.addEventListener("change", resetAndLoad);
if (searchBtn) searchBtn.addEventListener("click", resetAndLoad);
if (searchInput)
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") resetAndLoad();
  });

loadPage();

(function () {
  "use strict";

  const PAGE_SIZE = 30;
  let currentPage = 1;
  let debounceTimer = null;
  let personMeta = {};

  const $ = (sel) => document.querySelector(sel);
  const $$ = (sel) => document.querySelectorAll(sel);

  const searchInput = $("#matSearch");
  const docFilter = $("#matDocFilter");
  const sortSelect = $("#matSort");
  const minScoreInput = $("#matMinScore");
  const resultsDiv = $("#matResults");
  const loadingDiv = $("#matLoading");
  const emptyDiv = $("#matEmpty");
  const prevBtn = $("#matPrev");
  const nextBtn = $("#matNext");
  const pageInfo = $("#matPageInfo");
  const topNamesDiv = $("#matTopNames");

  function esc(s) {
    const el = document.createElement("span");
    el.textContent = s;
    return el.innerHTML;
  }

  function scoreBar(val, max) {
    const pct = Math.min(100, (val / (max || 1)) * 100);
    const hue = Math.round(pct * 1.2);
    return `<div class="mat-score-bar" style="--pct:${pct}%;--hue:${hue}"></div>`;
  }

  const CAT_LABELS = {
    politician: "Politician", business: "Business", celebrity: "Celebrity",
    royalty: "Royalty", academic: "Academic", associate: "Associate",
    legal: "Legal", socialite: "Socialite", other: "Other",
    "military-intelligence": "Intel/Military",
  };
  const CAT_COLOURS = {
    politician: "#e74c3c", business: "#3498db", celebrity: "#e91e63",
    royalty: "#f1c40f", academic: "#2ecc71", associate: "#e67e22",
    legal: "#795548", socialite: "#9b59b6", other: "#607d8b",
    "military-intelligence": "#00bcd4",
  };

  function personTag(name) {
    const p = personMeta[name];
    if (!p) return "";
    const col = CAT_COLOURS[p.category] || CAT_COLOURS.other;
    const label = CAT_LABELS[p.category] || p.category || "";
    return `<span class="mat-person-tag" style="--tag-col:${col}">${esc(label)}</span>`;
  }

  function personBio(name) {
    const p = personMeta[name];
    if (!p || !p.bio) return "";
    const stats = [];
    if (p.flights) stats.push(`${p.flights} flights`);
    if (p.documents) stats.push(`${p.documents} docs`);
    if (p.connections) stats.push(`${p.connections} connections`);
    const statsStr = stats.length ? `<span class="mat-person-stats">${stats.join(" · ")}</span>` : "";
    return `<div class="mat-person-bio">${esc(p.bio)}${statsStr}</div>`;
  }

  function personLink(name) {
    const p = personMeta[name];
    if (!p || !p.slug) return esc(name);
    return `<a href="https://epsteinexposed.com/persons/${esc(p.slug)}" target="_blank" rel="noopener" class="mat-person-link">${esc(name)}</a>`;
  }

  async function loadMetadata() {
    try {
      const resp = await fetch("/static/epstein_ui/person_metadata.json");
      if (resp.ok) personMeta = await resp.json();
    } catch (e) {
      console.warn("Could not load person metadata", e);
    }
  }

  // ==========================================================================
  // Tabs
  // ==========================================================================
  $$(".mat-tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      $$(".mat-tab").forEach((t) => t.classList.remove("active"));
      tab.classList.add("active");
      const target = tab.dataset.tab;
      $$("#tabResults, #tabTopnames").forEach((p) => (p.style.display = "none"));
      if (target === "results") {
        $("#tabResults").style.display = "";
      } else {
        $("#tabTopnames").style.display = "";
        fetchTopNames();
      }
    });
  });

  // ==========================================================================
  // Results tab
  // ==========================================================================
  async function fetchResults() {
    loadingDiv.style.display = "";
    emptyDiv.style.display = "none";
    resultsDiv.innerHTML = "";

    const params = new URLSearchParams();
    params.set("page", currentPage);
    const q = searchInput.value.trim();
    if (q) params.set("q", q);
    const doc = docFilter.value.trim();
    if (doc) params.set("doc", doc);
    params.set("sort", sortSelect.value);
    const ms = parseFloat(minScoreInput.value) || 0;
    if (ms > 0) params.set("min_score", ms);

    try {
      const resp = await fetch("/matches/list/?" + params.toString());
      const data = await resp.json();
      renderResults(data.items);
      updatePager(data);
    } catch (err) {
      resultsDiv.innerHTML = `<p class="mat-error">Failed to load matches.</p>`;
    } finally {
      loadingDiv.style.display = "none";
    }
  }

  function renderResults(items) {
    if (!items.length) {
      emptyDiv.style.display = "";
      return;
    }
    resultsDiv.innerHTML = items.map((item) => {
      const ctx = [];
      if (item.text_before) ctx.push(`...${esc(item.text_before)}`);
      ctx.push(`<span class="mat-redaction-gap">[REDACTED ~${item.estimated_chars} chars, ${item.width_pt}pt]</span>`);
      if (item.text_after) ctx.push(`${esc(item.text_after)}...`);

      const candRows = (item.candidates || []).map((c, i) => {
        const score = typeof c.total_score === "number" ? c.total_score.toFixed(3) : c.total_score;
        const wr = typeof c.width_ratio === "number" ? (c.width_ratio * 100).toFixed(0) + "%" : "";
        const tag = personTag(c.candidate_text);
        const bio = (i === 0) ? personBio(c.candidate_text) : "";
        const nameHtml = personLink(c.candidate_text);
        const candJson = esc(JSON.stringify(item.candidates));
        return `<tr class="mat-cand-row ${i === 0 ? 'mat-top-pick' : ''}" data-rid="${item.redaction_id}" data-cand-idx="${i}">
          <td class="mat-cand-rank">${c.rank}</td>
          <td class="mat-cand-text">
            <div class="mat-cand-name-row">${nameHtml} ${tag}</div>
            ${bio}
          </td>
          <td class="mat-cand-score">${score}${scoreBar(c.total_score, 1)}</td>
          <td class="mat-cand-wr">${wr}</td>
          <td class="mat-cand-view"><button class="btn btn-sm mat-view-btn" data-rid="${item.redaction_id}" data-cand-idx="${i}">View</button></td>
        </tr>`;
      }).join("");

      const leakBadge = item.has_leakage
        ? `<span class="mat-badge mat-badge-leak">leakage</span>` : "";

      const imgTag = item.image_context
        ? `<img class="mat-ctx-img" src="/redactions-image/${esc(item.image_context)}" loading="lazy" />`
        : "";

      return `<div class="mat-result-card" data-rid="${item.redaction_id}" data-candidates='${JSON.stringify(item.candidates).replace(/'/g, "&#39;")}' data-text-before="${esc(item.text_before || "")}" data-text-after="${esc(item.text_after || "")}">
        <div class="mat-result-header">
          <span class="mat-doc-label">${esc(item.doc_id)}</span>
          <span class="mat-page-label">p${item.page_num} r${item.redaction_index}</span>
          ${leakBadge}
          <span class="mat-match-count">${item.match_count} candidates</span>
        </div>
        <div class="mat-context">${ctx.join(" ")}</div>
        ${imgTag}
        <table class="mat-cand-table">
          <thead><tr>
            <th>#</th><th>Candidate</th><th>Score</th><th>Width</th><th></th>
          </tr></thead>
          <tbody>${candRows}</tbody>
        </table>
      </div>`;
    }).join("");

    resultsDiv.querySelectorAll(".mat-view-btn").forEach((btn) => {
      btn.addEventListener("click", (e) => {
        e.stopPropagation();
        const card = btn.closest(".mat-result-card");
        const rid = parseInt(card.dataset.rid);
        const candidates = JSON.parse(card.dataset.candidates);
        const idx = parseInt(btn.dataset.candIdx);
        const textBefore = card.dataset.textBefore;
        const textAfter = card.dataset.textAfter;
        openMatchViewer(rid, candidates, idx, textBefore, textAfter);
      });
    });
  }

  function updatePager(data) {
    const totalPages = Math.max(1, Math.ceil(data.total / PAGE_SIZE));
    pageInfo.textContent = `Page ${data.page} of ${totalPages} (${data.total} redactions)`;
    prevBtn.disabled = data.page <= 1;
    nextBtn.disabled = !data.has_more;
  }

  function resetAndFetch() { currentPage = 1; fetchResults(); }

  searchInput.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(resetAndFetch, 400);
  });
  docFilter.addEventListener("input", () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(resetAndFetch, 400);
  });
  sortSelect.addEventListener("change", resetAndFetch);
  minScoreInput.addEventListener("change", resetAndFetch);
  prevBtn.addEventListener("click", () => { if (currentPage > 1) { currentPage--; fetchResults(); } });
  nextBtn.addEventListener("click", () => { currentPage++; fetchResults(); });

  // ==========================================================================
  // Viewer overlay for candidate preview
  // ==========================================================================
  const mvOverlay = $("#mvOverlay");
  const mvViewer = $("#mvViewer");
  const mvViewerInner = $("#mvViewerInner");
  const mvPageImg = $("#mvPageImg");
  const mvBox = $("#mvBox");
  const mvTitle = $("#mvTitle");

  let mvScale = 1, mvTx = 0, mvTy = 0;
  let mvBbox = null;
  let mvCanvas = null;
  let mvFontData = null;
  let mvCandidates = [];
  let mvCandIdx = 0;

  function mvSetTransform(scale, tx, ty) {
    mvScale = scale; mvTx = tx; mvTy = ty;
    mvViewerInner.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    const slider = $("#mvZoomSlider");
    const level = $("#mvZoomLevel");
    if (slider) slider.value = Math.round(scale * 100);
    if (level) level.textContent = Math.round(scale * 100) + "%";
  }

  function mvApplyZoom(mode) {
    if (!mvBbox || !mvPageImg.naturalWidth) return;
    mvViewerInner.classList.remove("no-transition");
    const vw = mvViewer.clientWidth, vh = mvViewer.clientHeight;
    const iw = mvPageImg.naturalWidth, ih = mvPageImg.naturalHeight;
    const bx = mvBbox.x0, by = mvBbox.y0;
    const bw = mvBbox.x1 - mvBbox.x0, bh = mvBbox.y1 - mvBbox.y0;
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
    mvViewerInner.style.width = iw + "px";
    mvViewerInner.style.height = ih + "px";
    mvSetTransform(scale, tx, ty);
    mvBox.style.left = bx + "px"; mvBox.style.top = by + "px";
    mvBox.style.width = bw + "px"; mvBox.style.height = bh + "px";
    mvBox.style.display = "block";

    [$("#mvZoomTight"), $("#mvZoomContext"), $("#mvZoomPage")].forEach((b) => b && b.classList.remove("active"));
    const ab = mode === "tight" ? "#mvZoomTight" : mode === "context" ? "#mvZoomContext" : "#mvZoomPage";
    $(ab)?.classList.add("active");
  }

  function mvGetCanvas() {
    if (!mvCanvas) {
      mvCanvas = document.createElement("canvas");
      mvCanvas.style.cssText = "position:absolute;left:0;top:0;pointer-events:none";
      mvViewerInner.appendChild(mvCanvas);
    }
    if (mvPageImg.naturalWidth) {
      mvCanvas.width = mvPageImg.naturalWidth;
      mvCanvas.height = mvPageImg.naturalHeight;
      mvCanvas.style.width = mvPageImg.naturalWidth + "px";
      mvCanvas.style.height = mvPageImg.naturalHeight + "px";
    }
    return mvCanvas;
  }

  function mvDrawCandidate() {
    if (!mvBbox || !mvPageImg.naturalWidth || !mvCandidates.length) return;
    const canvas = mvGetCanvas();
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);

    const p = mvFontData?.params || {};
    const scaleX = p.scale_x ?? 1.0;
    const letterSp = p.letter_spacing_px ?? 0;
    const wordSp = p.word_spacing_px ?? 0;
    const xOff = p.x_offset_px ?? 0;
    const yOff = p.y_offset_px ?? 0;
    const sizeScale = p.size_scale ?? 1;

    if (mvFontData && mvFontData.spans) {
      ctx.globalAlpha = 0.45;
      ctx.fillStyle = "#00cc44";
      ctx.textBaseline = "alphabetic";
      if (typeof ctx.letterSpacing !== "undefined") ctx.letterSpacing = letterSp + "px";
      if (typeof ctx.wordSpacing !== "undefined") ctx.wordSpacing = wordSp + "px";
      for (const span of mvFontData.spans) {
        const fInfo = mvFontData.font_map ? mvFontData.font_map[span.font_name] : null;
        const family = p.css_family || (fInfo ? fInfo.css_family : "serif");
        const weight = span.font_weight === "bold" ? "bold" : "normal";
        const style = span.font_style === "italic" ? "italic" : "normal";
        const fontSize = span.font_size_px * sizeScale;
        ctx.font = `${style} ${weight} ${fontSize}px ${family}`;
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

    const cand = mvCandidates[mvCandIdx];
    if (!cand) return;

    const bx = mvBbox.x0, by = mvBbox.y0;
    const bw = mvBbox.x1 - mvBbox.x0, bh = mvBbox.y1 - mvBbox.y0;
    const baseline = by + bh * 0.78;

    let cssFamily = "serif", fontSize = bh * 0.7;
    let weight = "normal", style = "normal";

    if (mvFontData && mvFontData.spans && mvFontData.spans.length) {
      const nearSpans = mvFontData.spans.filter(
        (s) => s.origin_px && Math.abs(s.origin_px[1] - (by + bh * 0.75)) < bh
      );
      const ref = nearSpans[0] || mvFontData.spans[0];
      const fInfo = mvFontData.font_map ? mvFontData.font_map[ref.font_name] : null;
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
      ctx.fillText(cand.candidate_text, 0, 0);
    } else {
      ctx.fillText(cand.candidate_text, bx + 2, baseline);
    }
    if (typeof ctx.letterSpacing !== "undefined") ctx.letterSpacing = "0px";
    if (typeof ctx.wordSpacing !== "undefined") ctx.wordSpacing = "0px";
    ctx.restore();

    const fitEl = $("#mvCandFit");
    if (fitEl) {
      const wr = cand.width_ratio || 0;
      const err = Math.abs(1 - wr) * 100;
      const col = err <= 3 ? "#2ecc71" : err <= 10 ? "#f1c40f" : "#e74c3c";
      const label = err <= 3 ? "Excellent fit" : err <= 10 ? "Good fit" : "Poor fit";
      const tag = personTag(cand.candidate_text);
      const score = typeof cand.total_score === "number" ? cand.total_score.toFixed(3) : cand.total_score;
      fitEl.innerHTML =
        `<strong style="color:#00e5ff">${esc(cand.candidate_text)}</strong> ${tag} ` +
        `<span class="rd-fit-indicator" style="--fit-col:${col}">${label}</span>` +
        ` <span class="rd-fit-ratio">${(wr * 100).toFixed(0)}% width · score ${score}</span>`;
    }
  }

  async function openMatchViewer(redactionId, candidates, candIdx, textBefore, textAfter) {
    mvCandidates = candidates;
    mvCandIdx = candIdx || 0;
    mvFontData = null;

    try {
      const resp = await fetch(`/redactions/${redactionId}/`);
      if (!resp.ok) return;
      const d = await resp.json();

      mvTitle.textContent = `${d.doc_id} — Page ${d.page_num}, Redaction #${d.redaction_index}`;
      mvBbox = {
        x0: d.bbox_x0_pixels, y0: d.bbox_y0_pixels,
        x1: d.bbox_x1_pixels, y1: d.bbox_y1_pixels,
      };

      mvBox.style.display = "none";
      mvPageImg.src = "";
      mvViewerInner.style.transform = "";
      if (mvCanvas) {
        mvCanvas.getContext("2d").clearRect(0, 0, mvCanvas.width, mvCanvas.height);
      }

      // Populate candidate selector
      const select = $("#mvCandSelect");
      if (select) {
        select.innerHTML = "";
        candidates.forEach((c, i) => {
          const opt = document.createElement("option");
          opt.value = i;
          const score = typeof c.total_score === "number" ? c.total_score.toFixed(3) : c.total_score;
          opt.textContent = `#${c.rank} ${c.candidate_text} (${score})`;
          select.appendChild(opt);
        });
        select.value = mvCandIdx;
      }

      mvPageImg.onload = async () => {
        mvApplyZoom("context");

        try {
          const faResp = await fetch(`/redactions/${redactionId}/font-analysis/`);
          if (faResp.ok) mvFontData = await faResp.json();
        } catch (e) { /* ignore */ }

        mvDrawCandidate();

        try {
          const foResp = await fetch(`/redactions/${redactionId}/font-optimize/`);
          if (foResp.ok) {
            const foData = await foResp.json();
            if (foData.best && mvFontData) {
              mvFontData.params = foData.best;
              mvDrawCandidate();
            }
          }
        } catch (e) { /* ignore */ }
      };
      mvPageImg.src = `/redactions/${redactionId}/page-image/`;

      $("#mvBefore").textContent = textBefore || d.text_before || "(none)";
      $("#mvAfter").textContent = textAfter || d.text_after || "(none)";

      mvOverlay.classList.remove("hidden");
    } catch (err) {
      console.error(err);
    }
  }

  function closeMatchViewer() {
    mvOverlay.classList.add("hidden");
    mvPageImg.src = "";
    mvBox.style.display = "none";
  }

  // viewer events
  $("#mvClose").addEventListener("click", closeMatchViewer);
  mvOverlay.addEventListener("click", (e) => { if (e.target === mvOverlay) closeMatchViewer(); });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !mvOverlay.classList.contains("hidden")) closeMatchViewer();
  });

  $("#mvZoomTight")?.addEventListener("click", () => mvApplyZoom("tight"));
  $("#mvZoomContext")?.addEventListener("click", () => mvApplyZoom("context"));
  $("#mvZoomPage")?.addEventListener("click", () => mvApplyZoom("page"));

  // zoom slider
  const mvSlider = $("#mvZoomSlider");
  if (mvSlider) mvSlider.addEventListener("input", () => {
    mvViewerInner.classList.add("no-transition");
    const ns = parseInt(mvSlider.value) / 100;
    const vw = mvViewer.clientWidth, vh = mvViewer.clientHeight;
    const cx = vw / 2, cy = vh / 2;
    const r = ns / mvScale;
    mvSetTransform(ns, cx - r * (cx - mvTx), cy - r * (cy - mvTy));
  });

  // wheel zoom
  mvViewer.addEventListener("wheel", (e) => {
    e.preventDefault();
    mvViewerInner.classList.add("no-transition");
    const rect = mvViewer.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const f = e.deltaY > 0 ? 0.92 : 1.08;
    const ns = Math.max(0.05, Math.min(10, mvScale * f));
    const r = ns / mvScale;
    mvSetTransform(ns, mx - r * (mx - mvTx), my - r * (my - mvTy));
  }, { passive: false });

  // drag to pan
  let _mvDrag = false, _mvDx, _mvDy, _mvDtx, _mvDty;
  mvViewer.addEventListener("mousedown", (e) => {
    if (e.button !== 0) return;
    _mvDrag = true; _mvDx = e.clientX; _mvDy = e.clientY;
    _mvDtx = mvTx; _mvDty = mvTy;
    mvViewerInner.classList.add("no-transition");
    mvViewer.style.cursor = "grabbing";
    e.preventDefault();
  });
  window.addEventListener("mousemove", (e) => {
    if (!_mvDrag) return;
    mvSetTransform(mvScale, _mvDtx + e.clientX - _mvDx, _mvDty + e.clientY - _mvDy);
  });
  window.addEventListener("mouseup", () => { if (_mvDrag) { _mvDrag = false; mvViewer.style.cursor = ""; } });

  // touch
  let _mvT = {}, _mvPD = 0, _mvPM = null, _mvST = null;
  mvViewer.addEventListener("touchstart", (e) => {
    for (const t of e.changedTouches) _mvT[t.identifier] = { x: t.clientX, y: t.clientY };
    const pts = Object.values(_mvT);
    if (pts.length === 2) {
      _mvPD = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      _mvPM = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
    } else if (pts.length === 1) {
      _mvST = { x: e.touches[0].clientX, y: e.touches[0].clientY, tx: mvTx, ty: mvTy };
    }
  }, { passive: true });
  mvViewer.addEventListener("touchmove", (e) => {
    for (const t of e.changedTouches) _mvT[t.identifier] = { x: t.clientX, y: t.clientY };
    const pts = Object.values(_mvT);
    mvViewerInner.classList.add("no-transition");
    if (pts.length >= 2) {
      e.preventDefault();
      const d = Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
      const m = { x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2 };
      const rect = mvViewer.getBoundingClientRect();
      const mx = m.x - rect.left, my = m.y - rect.top;
      const f = d / _mvPD;
      const ns = Math.max(0.05, Math.min(10, mvScale * f));
      const r = ns / mvScale;
      mvSetTransform(ns, mx - r * (mx - mvTx) + (m.x - _mvPM.x), my - r * (my - mvTy) + (m.y - _mvPM.y));
      _mvPD = d; _mvPM = m;
    } else if (pts.length === 1 && _mvST) {
      e.preventDefault();
      mvSetTransform(mvScale, _mvST.tx + e.touches[0].clientX - _mvST.x, _mvST.ty + e.touches[0].clientY - _mvST.y);
    }
  }, { passive: false });
  mvViewer.addEventListener("touchend", (e) => {
    for (const t of e.changedTouches) delete _mvT[t.identifier];
    if (!Object.keys(_mvT).length) _mvST = null;
  }, { passive: true });

  // candidate navigation
  const mvSelect = $("#mvCandSelect");
  const mvPrevBtn = $("#mvCandPrev");
  const mvNextBtn = $("#mvCandNext");
  if (mvSelect) mvSelect.addEventListener("change", () => {
    mvCandIdx = parseInt(mvSelect.value) || 0;
    mvDrawCandidate();
  });
  if (mvPrevBtn) mvPrevBtn.addEventListener("click", () => {
    if (mvCandIdx > 0) { mvCandIdx--; if (mvSelect) mvSelect.value = mvCandIdx; mvDrawCandidate(); }
  });
  if (mvNextBtn) mvNextBtn.addEventListener("click", () => {
    if (mvCandIdx < mvCandidates.length - 1) { mvCandIdx++; if (mvSelect) mvSelect.value = mvCandIdx; mvDrawCandidate(); }
  });

  // ==========================================================================
  // Top Names tab
  // ==========================================================================
  let topNamesFetched = false;

  async function fetchTopNames() {
    if (topNamesFetched) return;
    topNamesDiv.innerHTML = "<p class='mat-loading'>Loading top names...</p>";
    try {
      const resp = await fetch("/matches/stats/");
      const data = await resp.json();
      renderTopNames(data.top_candidates);
      topNamesFetched = true;
    } catch (err) {
      topNamesDiv.innerHTML = "<p class='mat-error'>Failed to load stats.</p>";
    }
  }

  function renderTopNames(candidates) {
    if (!candidates || !candidates.length) {
      topNamesDiv.innerHTML = "<p class='mat-empty'>No candidate data yet. Run the batch matching first.</p>";
      return;
    }
    const rows = candidates.map((c, i) => {
      const tag = personTag(c.candidate_text);
      const p = personMeta[c.candidate_text];
      const bio = p && p.bio ? `<div class="mat-person-bio mat-person-bio-sm">${esc(p.bio)}</div>` : "";
      const nameHtml = personLink(c.candidate_text);
      return `<tr>
        <td class="mat-tn-rank">${i + 1}</td>
        <td class="mat-tn-name">${nameHtml} ${tag}${bio}</td>
        <td class="mat-tn-count">${c.appearances}</td>
        <td class="mat-tn-score">${c.avg_score}${scoreBar(c.avg_score, 1)}</td>
        <td class="mat-tn-best">${c.best_score}</td>
      </tr>`;
    }).join("");
    topNamesDiv.innerHTML = `
      <p class="mat-tn-intro">Names appearing most frequently as width-matching candidates across all redactions:</p>
      <table class="mat-tn-table">
        <thead><tr>
          <th>#</th><th>Name</th><th>Appearances</th><th>Avg Score</th><th>Best Score</th>
        </tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  // ---- boot ----
  loadMetadata().then(() => fetchResults());
})();

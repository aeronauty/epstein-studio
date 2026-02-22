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

  // ==========================================================================
  // Load person metadata
  // ==========================================================================
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
        return `<tr class="mat-cand-row ${i === 0 ? 'mat-top-pick' : ''}">
          <td class="mat-cand-rank">${c.rank}</td>
          <td class="mat-cand-text">
            <div class="mat-cand-name-row">${nameHtml} ${tag}</div>
            ${bio}
          </td>
          <td class="mat-cand-score">${score}${scoreBar(c.total_score, 1)}</td>
          <td class="mat-cand-wr">${wr}</td>
        </tr>`;
      }).join("");

      const leakBadge = item.has_leakage
        ? `<span class="mat-badge mat-badge-leak">leakage</span>` : "";

      const imgTag = item.image_context
        ? `<img class="mat-ctx-img" src="/redactions-image/${esc(item.image_context)}" loading="lazy" />`
        : "";

      return `<div class="mat-result-card">
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
            <th>#</th><th>Candidate</th><th>Score</th><th>Width</th>
          </tr></thead>
          <tbody>${candRows}</tbody>
        </table>
      </div>`;
    }).join("");
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

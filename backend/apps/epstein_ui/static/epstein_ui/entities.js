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
  const detailBody = $("#entDetailBody");
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
  // Tabs
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
  // Entities tab
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

  // ---- entity detail panel ----
  tbody.addEventListener("click", async (e) => {
    const row = e.target.closest(".ent-row");
    if (!row) return;
    const entity = row.dataset.entity;
    detailTitle.textContent = entity;
    detailBody.innerHTML = "<p>Loading...</p>";
    detailPanel.style.display = "";
    try {
      const resp = await fetch("/entities/detail/" + encodeURIComponent(entity) + "/");
      const data = await resp.json();
      renderDetail(data);
    } catch (err) {
      detailBody.innerHTML = "<p class='ent-error'>Failed to load detail.</p>";
    }
  });

  function renderDetail(data) {
    if (!data.occurrences || !data.occurrences.length) {
      detailBody.innerHTML = "<p>No occurrences found.</p>";
      return;
    }
    const rows = data.occurrences.map((o) =>
      `<tr>
        <td>${esc(o.extracted_document__doc_id)}</td>
        <td>${typeTag(o.entity_type)}</td>
        <td>${o.page_num ?? "\u2014"}</td>
        <td>${o.count}</td>
      </tr>`
    ).join("");
    detailBody.innerHTML = `
      <p>${data.occurrences.length} occurrence(s) across documents:</p>
      <table class="ent-detail-table">
        <thead><tr><th>Document</th><th>Type</th><th>Page</th><th>Count</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>`;
  }

  detailClose.addEventListener("click", () => { detailPanel.style.display = "none"; });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") detailPanel.style.display = "none";
  });

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

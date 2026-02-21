const grid = document.getElementById("rdGrid");
const moreBtn = document.getElementById("rdMore");
const sortSelect = document.getElementById("rdSort");
const methodSelect = document.getElementById("rdMethod");
const searchInput = document.getElementById("rdSearch");
const searchBtn = document.getElementById("rdSearchBtn");
const countSpan = document.getElementById("rdCount");
const overlay = document.getElementById("rdOverlay");
const closeBtn = document.getElementById("rdDetailClose");

let page = 1;
let loading = false;
let hasMore = true;

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

async function openDetail(id) {
  try {
    const resp = await fetch(`/redactions/${id}/`);
    if (!resp.ok) return;
    const d = await resp.json();

    document.getElementById("rdDetailTitle").textContent =
      `${d.doc_id} — Page ${d.page_num}, Redaction #${d.redaction_index}`;

    const ctxImg = document.getElementById("rdDetailCtx");
    const tightImg = document.getElementById("rdDetailTight");
    ctxImg.src = d.image_context ? imgUrl(d.image_context) : "";
    ctxImg.parentElement.classList.toggle("hidden", !d.image_context);
    tightImg.src = d.image_tight ? imgUrl(d.image_tight) : "";
    tightImg.parentElement.classList.toggle("hidden", !d.image_tight);

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
}

if (closeBtn) closeBtn.addEventListener("click", closeDetail);
if (overlay)
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeDetail();
  });
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !overlay.classList.contains("hidden")) closeDetail();
});

if (sortSelect) sortSelect.addEventListener("change", resetAndLoad);
if (methodSelect) methodSelect.addEventListener("change", resetAndLoad);
if (searchBtn) searchBtn.addEventListener("click", resetAndLoad);
if (searchInput)
  searchInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter") resetAndLoad();
  });

loadPage();

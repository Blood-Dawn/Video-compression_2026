/*
 * src/gui/static/js/library.js
 *
 * Library / gallery tab (FIX 6 + R2.3 overhaul).
 *
 * Browse a folder of videos as a thumbnail grid or list, search and filter and
 * sort them, open a detail view with an inline player and metadata, and send a
 * clip into the compress flow. A "Browse..." button opens a native folder
 * dialog (or type a path). The chosen folder is remembered. Thumbnails come from
 * /api/library/thumb (generated lazily, cached) and fall back to a placeholder
 * when one cannot be made. Loads lazily the first time the tab is opened.
 *
 * Author: Bloodawn (KheivenD), 2026-06-03 (FIX 6), 2026-06-05 (R2.3).
 */
"use strict";

window._svcsLibrary = { view: "grid", folder: "", loaded: false, selected: null, all: [], kind: "all" };

function _libStatus(msg) {
  const el = document.getElementById("library-status");
  if (el) el.textContent = msg || "";
}

function _enc(p) { return encodeURIComponent(p); }

function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

function _fmtSize(bytes) {
  if (bytes == null) return "";
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? (mb / 1024).toFixed(2) + " GB" : mb.toFixed(1) + " MB";
}

// Remembered per browser: sort order and grid or list layout.
function _lsGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function _lsSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }

function setLibraryView(mode) {
  window._svcsLibrary.view = mode === "list" ? "list" : "grid";
  _lsSet("svcs.lib.view", window._svcsLibrary.view);
  const grid = document.getElementById("library-grid");
  if (grid) grid.classList.toggle("is-list", window._svcsLibrary.view === "list");
  ["grid", "list"].forEach((k) => {
    const b = document.getElementById("library-view-" + k);
    if (b) b.setAttribute("aria-pressed", String(k === window._svcsLibrary.view));
  });
  filterLibrary();
}
window.setLibraryView = setLibraryView;

// R3.1d: switch the All | Originals | Compressed segmented control.
function setLibraryKind(kind) {
  window._svcsLibrary.kind = (["all", "original", "compressed"].includes(kind)) ? kind : "all";
  ["all", "original", "compressed"].forEach((k) => {
    const btn = document.getElementById("library-kind-" + k);
    if (btn) btn.setAttribute("aria-pressed", String(k === window._svcsLibrary.kind));
  });
  filterLibrary();
}
window.setLibraryKind = setLibraryKind;

function _placeholderThumb(img, ext) {
  // Replace a broken or failed thumbnail with a labelled placeholder box.
  img.onerror = null;
  const box = document.createElement("div");
  box.className = "x-noprev";
  box.textContent = (ext || "video").toUpperCase() + " (no preview)";
  if (img.parentNode) img.parentNode.replaceChild(box, img);
}

// Long names keep their start and their ending (the extension and the time
// stamp are the useful parts); the full name stays in the title tooltip.
function _midTrunc(name, max) {
  max = max || 30;
  if (name.length <= max) return name;
  const tail = 11;
  return name.slice(0, max - tail - 1) + "…" + name.slice(-tail);
}

// ── Selection ──────────────────────────────────────────────────────────────
window._svcsLibrary.sel = new Set();

function _libUpdateSelection() {
  const sel = window._svcsLibrary.sel;
  const bar = document.getElementById("library-selbar");
  const filt = document.getElementById("library-filterrow");
  const chips = document.getElementById("library-chips");
  const n = sel.size;
  if (bar) bar.hidden = n === 0;
  if (filt) filt.hidden = n > 0;
  if (chips && n > 0) chips.hidden = true;
  const cnt = document.getElementById("library-sel-count");
  if (cnt) cnt.textContent = n + " selected";
  const hint = document.getElementById("library-sel-hint");
  if (hint) hint.textContent = n > 1 ? "Compress and Encrypt work on one video at a time." : "";
  ["compress", "encrypt"].forEach((k) => {
    const b = document.getElementById("library-sel-" + k);
    if (b) b.disabled = n !== 1;
  });
  document.querySelectorAll("#library-grid .x-vcard").forEach((c) => {
    c.classList.toggle("is-sel", sel.has(c.dataset.path));
  });
}

function libClearSelection() {
  window._svcsLibrary.sel.clear();
  document.querySelectorAll("#library-grid .x-check input").forEach((i) => { i.checked = false; });
  _libUpdateSelection();
  _libRenderChips();
}
window.libClearSelection = libClearSelection;

function libSelAction(kind) {
  const sel = Array.from(window._svcsLibrary.sel);
  if (sel.length !== 1) return;
  window._svcsLibrary.selected = sel[0];
  if (kind === "compress") compressLibrarySelection();
  else if (kind === "encrypt" && typeof promptEncryptSegment === "function") promptEncryptSegment(sel[0]);
}
window.libSelAction = libSelAction;

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape" || !window._svcsLibrary.sel.size) return;
  const tab = document.getElementById("tab-library");
  if (tab && tab.classList.contains("active")) libClearSelection();
});

// ── Filter chips ───────────────────────────────────────────────────────────
const _LIB_AGE_LABEL = { "1": "Last 24 hours", "7": "Last 7 days", "30": "Last 30 days" };

function _libActiveFilters() {
  const out = [];
  const kind = window._svcsLibrary.kind;
  if (kind === "original") out.push({ id: "kind", label: "Originals" });
  if (kind === "compressed") out.push({ id: "kind", label: "Compressed" });
  const ext = ((document.getElementById("library-ext") || {}).value || "");
  if (ext) out.push({ id: "ext", label: ext.toUpperCase() });
  const age = ((document.getElementById("library-age") || {}).value || "");
  if (age) out.push({ id: "age", label: _LIB_AGE_LABEL[age] || ("Last " + age + " days") });
  const q = ((document.getElementById("library-search") || {}).value || "").trim();
  if (q) out.push({ id: "q", label: "Name has “" + q + "”" });
  return out;
}

function _libRemoveFilter(id) {
  if (id === "kind") { window._svcsLibrary.kind = "all"; setLibraryKind("all"); return; }
  const map = { ext: "library-ext", age: "library-age", q: "library-search" };
  const el = document.getElementById(map[id]);
  if (el) el.value = "";
  filterLibrary();
}

function libClearFilters() {
  ["library-ext", "library-age", "library-search"].forEach((i) => {
    const el = document.getElementById(i);
    if (el) el.value = "";
  });
  window._svcsLibrary.kind = "all";
  setLibraryKind("all");
}
window.libClearFilters = libClearFilters;

function _libRenderChips() {
  const box = document.getElementById("library-chips");
  if (!box) return;
  const f = _libActiveFilters();
  if (!f.length || window._svcsLibrary.sel.size) { box.hidden = true; box.innerHTML = ""; return; }
  box.hidden = false;
  box.innerHTML = '<span class="x-chips-lbl">Active filters</span>';
  f.forEach((x) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "x-chip";
    b.setAttribute("aria-label", "Remove filter " + x.label);
    b.innerHTML = _esc(x.label) + ' <span class="x-x" aria-hidden="true">×</span>';
    b.onclick = () => _libRemoveFilter(x.id);
    box.appendChild(b);
  });
  const clr = document.createElement("button");
  clr.type = "button";
  clr.className = "x-link";
  clr.textContent = "Clear filters";
  clr.onclick = libClearFilters;
  box.appendChild(clr);
}

function _libShowEmpty(kind) {
  // kind: "none" (nothing in the folder), "filtered" (filters match nothing)
  const empty = document.getElementById("library-empty");
  if (!empty) return;
  const t = document.getElementById("library-empty-title");
  const x = document.getElementById("library-empty-text");
  const clr = document.getElementById("library-empty-clear");
  const br = document.getElementById("library-empty-browse");
  const rt = document.getElementById("library-empty-retry");
  if (rt) rt.hidden = true;
  if (kind === "filtered") {
    if (t) t.textContent = "No videos match these filters";
    if (x) x.textContent = "Try a different search, or clear the filters to see everything in the folder.";
    if (clr) clr.hidden = false;
    if (br) br.hidden = true;
  } else {
    if (t) t.textContent = "No videos in this folder yet";
    if (x) x.textContent = "Pick a folder that contains your clips (subfolders are searched too).";
    if (clr) clr.hidden = true;
    if (br) br.hidden = false;
  }
  empty.style.display = "block";
}

function _renderLibrary(list) {
  const grid = document.getElementById("library-grid");
  const empty = document.getElementById("library-empty");
  const count = document.getElementById("library-count");
  if (!grid) return;
  grid.innerHTML = "";
  const total = window._svcsLibrary.all.length;
  if (count) {
    count.textContent = list.length === total
      ? total + (total === 1 ? " video" : " videos") : list.length + " of " + total + " videos";
  }
  if (!list.length) {
    if (!total) { _libStatus(""); _libShowEmpty("none"); }
    else { _libStatus(""); _libShowEmpty("filtered"); }
    _libUpdateSelection();
    return;
  }
  if (empty) empty.style.display = "none";
  _libStatus("");
  // Source sizes for "Saved n%": only claimed when the original is in the
  // same listing, so the number is measured and never guessed.
  const sizeByPath = {};
  window._svcsLibrary.all.forEach((v) => { sizeByPath[v.path] = v.size; });
  const sel = window._svcsLibrary.sel;
  list.forEach((v) => {
    const ext = (v.name.split(".").pop() || "").toLowerCase();
    const cell = document.createElement("div");
    cell.className = "x-vcard" + (sel.has(v.path) ? " is-sel" : "");
    cell.dataset.path = v.path;

    const thumb = document.createElement("div");
    thumb.className = "x-thumb";
    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = "/api/library/thumb?path=" + _enc(v.path);
    img.alt = "";
    img.onerror = () => _placeholderThumb(img, ext);
    thumb.appendChild(img);
    thumb.onclick = () => openLibraryDetail(v.path, v.name);

    const chk = document.createElement("label");
    chk.className = "x-check";
    chk.innerHTML = '<input type="checkbox" aria-label="Select ' + _esc(v.name) + '"/><span aria-hidden="true"></span>';
    const cb = chk.querySelector("input");
    cb.checked = sel.has(v.path);
    cb.addEventListener("click", (e) => e.stopPropagation());
    cb.addEventListener("change", () => {
      if (cb.checked) sel.add(v.path); else sel.delete(v.path);
      _libUpdateSelection();
      _libRenderChips();
    });
    thumb.appendChild(chk);

    const body = document.createElement("div");
    body.className = "x-vbody";
    const nm = document.createElement("button");
    nm.type = "button";
    nm.className = "x-vname";
    nm.title = v.name;
    nm.textContent = _midTrunc(v.name);
    nm.onclick = () => openLibraryDetail(v.path, v.name);
    body.appendChild(nm);

    const meta = document.createElement("div");
    meta.className = "x-vmeta";
    const isComp = v.kind === "compressed";
    meta.innerHTML = '<span class="x-badge ' + (isComp ? "is-comp" : "is-orig") + '">' +
      (isComp ? "Compressed" : "Original") + '</span><span class="x-size">' + _esc(_fmtSize(v.size)) + '</span>';
    body.appendChild(meta);

    const note = document.createElement("div");
    note.className = "x-saved";
    if (isComp) {
      const src = v.source && sizeByPath[v.source];
      if (src && v.size && src > v.size) {
        const pct = Math.round((1 - v.size / src) * 100);
        note.textContent = pct >= 2 ? "Saved " + pct + "%" : "Almost no savings";
        if (pct >= 2) note.classList.add("is-good");
      } else {
        note.textContent = "Compressed copy";
      }
    } else {
      note.textContent = v.compressed ? "Has a compressed copy" : "Not compressed yet";
    }
    body.appendChild(note);

    cell.appendChild(thumb);
    cell.appendChild(body);
    grid.appendChild(cell);
  });
  _libUpdateSelection();
}

// Aggregate stats for the filtered set: real counts and sizes only, with
// deliberately no invented compression ratio (see status.js's
// pollMeasuredSavings comment for why a synthetic ratio is avoided).
function _fmtBytes(bytes) {
  if (!bytes) return '0 MB';
  const mb = bytes / (1024 * 1024);
  return mb >= 1024 ? (mb / 1024).toFixed(2) + ' GB' : mb.toFixed(1) + ' MB';
}

function _renderLibraryStats(list) {
  const strip = document.getElementById('library-stats-strip');
  if (!strip) return;
  if (!list.length) { strip.style.display = 'none'; return; }
  let totalBytes = 0, origCount = 0, origBytes = 0, compCount = 0, compBytes = 0;
  list.forEach((v) => {
    const sz = v.size || 0;
    totalBytes += sz;
    if (v.kind === 'compressed') { compCount++; compBytes += sz; }
    else { origCount++; origBytes += sz; }
  });
  strip.style.display = 'flex';
  strip.innerHTML =
    '<span>' + list.length + ' clip' + (list.length === 1 ? '' : 's') +
    ' &middot; ' + _fmtBytes(totalBytes) + ' total</span>' +
    '<span>Originals: ' + origCount + ' (' + _fmtBytes(origBytes) + ')</span>' +
    '<span>Compressed: ' + compCount + ' (' + _fmtBytes(compBytes) + ')</span>';
}

function _libKindCounts() {
  const c = { all: 0, original: 0, compressed: 0 };
  (window._svcsLibrary.all || []).forEach((v) => {
    c.all++;
    if (v.kind === "compressed") c.compressed++; else c.original++;
  });
  ["all", "original", "compressed"].forEach((k) => {
    const el = document.getElementById("library-n-" + k);
    if (el) el.textContent = c[k];
  });
}

// Client-side search + type filter + sort over the loaded page.
function filterLibrary() {
  const all = window._svcsLibrary.all || [];
  const q = ((document.getElementById("library-search") || {}).value || "").trim().toLowerCase();
  const ext = ((document.getElementById("library-ext") || {}).value || "").toLowerCase();
  const sortVal = (document.getElementById("library-sort") || {}).value || "date-desc";
  const ageDays = parseInt((document.getElementById("library-age") || {}).value || "0", 10) || 0;
  const cutoff = ageDays ? (Date.now() / 1000) - ageDays * 86400 : 0;
  const kind = window._svcsLibrary.kind || "all";
  _lsSet("svcs.lib.sort", sortVal);
  let list = all.filter((v) => {
    if (q && !v.name.toLowerCase().includes(q)) return false;
    if (ext && !v.name.toLowerCase().endsWith("." + ext)) return false;
    if (cutoff && !(v.mtime >= cutoff)) return false;
    if (kind === "compressed" && v.kind !== "compressed") return false;
    if (kind === "original" && v.kind === "compressed") return false;
    return true;
  });
  const [field, dir] = sortVal.split("-");
  if (field === "name") {
    // Lowercase each name once instead of twice per comparison; this runs on
    // every keystroke in the search box.
    list = list.map((v) => [v.name.toLowerCase(), v])
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map((pair) => pair[1]);
  } else {
    list.sort(field === "size" ? (a, b) => a.size - b.size : (a, b) => a.mtime - b.mtime);
  }
  if (dir === "desc") list.reverse();
  _libKindCounts();
  _libRenderChips();
  _renderLibraryStats(list);
  _renderLibrary(list);
}
window.filterLibrary = filterLibrary;

function _populateExtFilter(exts) {
  const sel = document.getElementById("library-ext");
  if (!sel) return;
  const cur = sel.value;
  sel.innerHTML = '<option value="">All types</option>';
  (exts || []).forEach((e) => {
    const o = document.createElement("option");
    o.value = e; o.textContent = e.toUpperCase();
    sel.appendChild(o);
  });
  if (cur && exts && exts.includes(cur)) sel.value = cur;
}

async function loadLibrary() {
  const folderEl = document.getElementById("library-folder");
  const folder = folderEl ? folderEl.value.trim() : "";
  _libStatus("Loading...");
  closeLibraryDetail();
  try {
    // refresh=1 bypasses the server-side listing cache (M2.1a), which exists
    // for the phone client's pagination. loadLibrary only runs on a user
    // action, and a user who just compressed something and clicks Load
    // expects to see it.
    const base = "/api/library/videos?refresh=1";
    const url = base + (folder ? "&folder=" + _enc(folder) : "");
    const data = await (await fetch(url)).json();
    if (folderEl && !folderEl.value && data.folder) folderEl.value = data.folder;
    window._svcsLibrary.loaded = true;
    window._svcsLibrary.folder = data.folder || folder;
    window._svcsLibrary.all = data.videos || [];
    _populateExtFilter(data.extensions);
    if (data.exists === false) {
      _libShowEmpty("none");
      const tt = document.getElementById("library-empty-title");
      if (tt) tt.textContent = "That folder was not found";
      _libStatus("Folder not found. Click Browse to pick one.");
      const grid = document.getElementById("library-grid");
      if (grid) grid.innerHTML = "";
      return;
    }
    filterLibrary();
  } catch (e) {
    _libStatus("Could not load the library.");
    _libShowEmpty("none");
    const tt = document.getElementById("library-empty-title");
    const tx = document.getElementById("library-empty-text");
    const rt = document.getElementById("library-empty-retry");
    if (tt) tt.textContent = "Could not load the library";
    if (tx) tx.textContent = "The app could not read this folder just now. Check the path, then try again.";
    if (rt) rt.hidden = false;
  }
}
window.loadLibrary = loadLibrary;

// ── Folder browser modal (R2.3 follow-up) ───────────────────────────────────
// A server-side navigator (works in the frozen app + remotely, unlike a native
// OS dialog). Walks directories via /api/library/list_dirs.
window._lbPath = "";
window._lbTargetInputId = "library-folder";
window._lbOnUse = null;

function _showBrowseModal(show) {
  const m = document.getElementById("library-browse-modal");
  if (m) m.style.display = show ? "flex" : "none";
}

async function _lbNavigate(path) {
  const listEl = document.getElementById("lb-dir-list");
  const pathEl = document.getElementById("lb-current-path");
  const hintEl = document.getElementById("lb-hint");
  const useBtn = document.getElementById("lb-use-btn");
  if (listEl) listEl.innerHTML = "Loading...";
  let data;
  try {
    data = await (await fetch("/api/library/list_dirs" + (path ? "?path=" + _enc(path) : ""))).json();
  } catch (e) {
    if (listEl) listEl.textContent = "Could not read that folder.";
    return;
  }
  if (data.error) { if (hintEl) hintEl.textContent = data.error; return; }
  window._lbPath = data.path || "";
  if (pathEl) pathEl.textContent = data.is_root ? "This PC" : (data.path || "/");
  if (useBtn) useBtn.disabled = !!data.is_root;
  if (hintEl) {
    hintEl.textContent = data.is_root ? "Pick a drive, then a folder."
      : ((data.video_count || 0) + " video(s) directly in this folder; subfolders are included too.");
  }
  if (listEl) {
    listEl.innerHTML = "";
    (data.dirs || []).forEach((d) => {
      const row = document.createElement("div");
      row.style.cssText = "padding:4px 6px;cursor:pointer;border-radius:3px;";
      row.textContent = (data.is_root ? "" : "[dir] ") + d.name;
      row.onmouseover = () => row.style.background = "var(--surface3)";
      row.onmouseout = () => row.style.background = "transparent";
      row.onclick = () => _lbNavigate(d.path);
      listEl.appendChild(row);
    });
    if (!(data.dirs || []).length) {
      listEl.innerHTML = '<div style="padding:6px;color:var(--text-dim);">No subfolders here. Use this folder, or go Up.</div>';
    }
  }
}

async function browseFolderInto(inputId, onUse) {
  // Lands the chosen path in whatever <input> the caller names and,
  // optionally, runs a callback afterward (Setup's folder fields use it
  // without triggering a Library reload). Tries the host's NATIVE folder
  // picker first and falls back to the in-app server-side browser when that
  // is unreachable (e.g. a remote/headless server).
  try {
    const data = await (await fetch("/api/library/browse_folder")).json();
    if (data && data.path) {
      const el = document.getElementById(inputId);
      if (el) {
        el.value = data.path;
        // Fields like setup-output-dir keep another field in sync via an
        // 'input' listener; a value set from JS doesn't fire that on its
        // own, so dispatch one explicitly.
        el.dispatchEvent(new Event("input", { bubbles: true }));
      }
      if (typeof onUse === "function") onUse(data.path);
    }
    // An empty path means the user cancelled the dialog: do nothing.
    return;
  } catch (e) {
    // Native picker unavailable: fall back to the in-app folder browser so a
    // remote user is never stuck.
    window._lbTargetInputId = inputId;
    window._lbOnUse = onUse || null;
    _showBrowseModal(true);
    const el = document.getElementById(inputId);
    const start = (el && el.value.trim()) || "";
    await _lbNavigate(start);
  }
}
window.browseFolderInto = browseFolderInto;

async function browseLibraryFolder() {
  await browseFolderInto("library-folder", () => loadLibrary());
}
window.browseLibraryFolder = browseLibraryFolder;

async function lbUp() {
  let data;
  try {
    data = await (await fetch("/api/library/list_dirs" + (window._lbPath ? "?path=" + _enc(window._lbPath) : ""))).json();
  } catch (e) { return; }
  // parent is "" -> drive list; null -> already at top.
  if (data.parent === null || data.parent === undefined) { await _lbNavigate(""); return; }
  await _lbNavigate(data.parent);
}
window.lbUp = lbUp;

function lbUseFolder() {
  if (!window._lbPath) return;
  const inputId = window._lbTargetInputId || "library-folder";
  const folderEl = document.getElementById(inputId);
  if (folderEl) {
    folderEl.value = window._lbPath;
    folderEl.dispatchEvent(new Event("input", { bubbles: true }));
  }
  const onUse = window._lbOnUse;
  const path = window._lbPath;
  window._lbTargetInputId = "library-folder";
  window._lbOnUse = null;
  closeBrowseModal();
  if (typeof onUse === "function") onUse(path);
}
window.lbUseFolder = lbUseFolder;

function closeBrowseModal() { _showBrowseModal(false); }
window.closeBrowseModal = closeBrowseModal;

async function openLibraryDetail(path, name) {
  window._svcsLibrary.selected = path;
  const grid = document.getElementById("library-grid");
  const detail = document.getElementById("library-detail");
  if (grid) grid.style.display = "none";
  const empty = document.getElementById("library-empty");
  if (empty) empty.style.display = "none";
  if (detail) detail.style.display = "block";
  const player = document.getElementById("library-player");
  if (player) player.src = "/api/library/file?path=" + _enc(path);
  const nameEl = document.getElementById("library-detail-name");
  if (nameEl) nameEl.textContent = name || path;
  const metaEl = document.getElementById("library-detail-meta");
  if (metaEl) metaEl.textContent = "Loading metadata...";
  try {
    const m = await (await fetch("/api/library/meta?path=" + _enc(path))).json();
    if (metaEl) {
      const dur = m.duration ? parseFloat(m.duration).toFixed(1) + " s" : "n/a";
      metaEl.innerHTML = '<dl class="x-facts">'
        + "<dt>Size</dt><dd>" + _esc(_fmtSize(m.size)) + "</dd>"
        + "<dt>Resolution</dt><dd>" + _esc((m.width || "?") + " x " + (m.height || "?")) + "</dd>"
        + "<dt>Codec</dt><dd>" + _esc(m.codec_name || "n/a") + "</dd>"
        + "<dt>Frame rate</dt><dd>" + _esc(m.r_frame_rate || "n/a") + "</dd>"
        + "<dt>Duration</dt><dd>" + _esc(dur) + "</dd></dl>";
    }
  } catch (e) {
    if (metaEl) metaEl.textContent = "Metadata unavailable.";
  }
}
window.openLibraryDetail = openLibraryDetail;

function closeLibraryDetail() {
  const grid = document.getElementById("library-grid");
  const detail = document.getElementById("library-detail");
  const player = document.getElementById("library-player");
  if (player) { if (player.pause) player.pause(); player.removeAttribute("src"); if (player.load) player.load(); }
  if (detail) detail.style.display = "none";
  if (grid) grid.style.display = "grid";
}
window.closeLibraryDetail = closeLibraryDetail;

async function compressLibrarySelection() {
  const path = window._svcsLibrary.selected;
  if (!path) return;
  try {
    const res = await fetch("/api/library/compress", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ path: path }),
    });
    const data = await res.json();
    if (!data.ok) { _libStatus(data.error || "Could not select this video."); return; }
    const src = document.getElementById("input-source");
    if (src) {
      src.value = data.path;
      if (typeof _onInputSourceChange === "function") _onInputSourceChange(data.path);
    }
    if (typeof switchTab === "function") switchTab("home");
    if (typeof pushNotif === "function") {
      pushNotif("Loaded into source", data.name + " is ready. Pick a preset and press Start.", "info", null, 4000);
    }
  } catch (e) {
    _libStatus("Could not load this video into the compressor.");
  }
}
window.compressLibrarySelection = compressLibrarySelection;

// Prefill the last-used folder, then lazy-load on first LIBRARY tab open.
window.addEventListener("DOMContentLoaded", async () => {
  const savedSort = _lsGet("svcs.lib.sort");
  const sortEl = document.getElementById("library-sort");
  if (sortEl && savedSort && Array.from(sortEl.options).some((o) => o.value === savedSort)) sortEl.value = savedSort;
  if (_lsGet("svcs.lib.view") === "list") setLibraryView("list");
  try {
    const st = await (await fetch("/api/setup/state")).json();
    const folderEl = document.getElementById("library-folder");
    if (folderEl && st.library_folder) folderEl.value = st.library_folder;
  } catch (e) { /* optional */ }
  const btn = document.querySelector('.tab-btn[data-tab="library"]');
  if (btn) {
    btn.addEventListener("click", () => {
      if (!window._svcsLibrary.loaded) loadLibrary();
    });
  }
});

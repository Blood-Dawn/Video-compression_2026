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

function setLibraryView(mode) {
  window._svcsLibrary.view = mode === "list" ? "list" : "grid";
  const grid = document.getElementById("library-grid");
  if (grid) {
    grid.style.gridTemplateColumns = window._svcsLibrary.view === "list"
      ? "1fr" : "repeat(auto-fill,minmax(180px,1fr))";
  }
  filterLibrary();
}
window.setLibraryView = setLibraryView;

// R3.1d: switch the All | Originals | Compressed segmented control.
function setLibraryKind(kind) {
  window._svcsLibrary.kind = (["all", "original", "compressed"].includes(kind)) ? kind : "all";
  ["all", "original", "compressed"].forEach((k) => {
    const btn = document.getElementById("library-kind-" + k);
    if (!btn) return;
    const on = k === window._svcsLibrary.kind;
    btn.style.color = on ? "#ff9e5e" : "";
    btn.style.borderColor = on ? "#ff9e5e" : "";
  });
  filterLibrary();
}
window.setLibraryKind = setLibraryKind;

function _placeholderThumb(img, ext) {
  // Replace a broken/failed thumbnail with a labelled placeholder box.
  img.onerror = null;
  img.removeAttribute("src");
  img.style.display = "flex";
  img.style.alignItems = "center";
  img.style.justifyContent = "center";
  img.style.color = "var(--text-dim)";
  img.style.fontFamily = "var(--mono)";
  img.style.fontSize = "0.6rem";
  img.style.background = "#11151c";
  // <img> cannot hold text, so swap to a div in place.
  const box = document.createElement("div");
  box.style.cssText = img.style.cssText;
  box.style.width = img.style.width || "100%";
  box.style.height = img.style.height;
  box.textContent = (ext || "video").toUpperCase() + " (no preview)";
  if (img.parentNode) img.parentNode.replaceChild(box, img);
}

function _renderLibrary(list) {
  const grid = document.getElementById("library-grid");
  const empty = document.getElementById("library-empty");
  const count = document.getElementById("library-count");
  if (!grid) return;
  grid.innerHTML = "";
  if (count) {
    const total = window._svcsLibrary.all.length;
    count.textContent = list.length === total
      ? total + " video(s)" : list.length + " of " + total;
  }
  if (!list.length) {
    if (empty) empty.style.display = window._svcsLibrary.all.length ? "none" : "block";
    if (!window._svcsLibrary.all.length) _libStatus("");
    else _libStatus("No videos match the current search/filter.");
    return;
  }
  if (empty) empty.style.display = "none";
  _libStatus("");
  const isList = window._svcsLibrary.view === "list";
  list.forEach((v) => {
    const ext = (v.name.split(".").pop() || "").toLowerCase();
    const cell = document.createElement("div");
    cell.style.cssText = isList
      ? "display:flex;gap:0.6rem;align-items:center;padding:0.3rem;border:1px solid var(--border);border-radius:4px;cursor:pointer;"
      : "border:1px solid var(--border);border-radius:6px;overflow:hidden;cursor:pointer;background:var(--surface2);";
    const img = document.createElement("img");
    img.loading = "lazy";
    img.src = "/api/library/thumb?path=" + _enc(v.path);
    img.alt = v.name;
    img.style.cssText = isList
      ? "width:96px;height:54px;object-fit:cover;background:#000;border-radius:3px;flex-shrink:0;"
      : "width:100%;height:108px;object-fit:cover;background:#000;display:block;";
    img.onerror = () => _placeholderThumb(img, ext);
    const label = document.createElement("div");
    label.style.cssText = "font-family:var(--mono);font-size:0.6rem;padding:0.3rem;color:var(--text);word-break:break-all;";
    // R3.1d: tag compressed outputs, and mark originals that already have one.
    let tag = "";
    if (v.kind === "compressed") {
      tag = '<span style="display:inline-block;font-size:0.5rem;font-weight:700;color:#ff5fa2;border:1px solid #ff5fa2;border-radius:3px;padding:0 0.25rem;margin-right:0.3rem;">COMPRESSED</span>';
    } else if (v.compressed) {
      tag = '<span title="A compressed version exists" style="color:var(--green,#39d353);margin-right:0.3rem;">&#10003;</span>';
    }
    label.innerHTML = tag + _esc(v.name) + (isList ? "   " + _fmtSize(v.size) : "");
    cell.appendChild(img);
    cell.appendChild(label);
    cell.onclick = () => openLibraryDetail(v.path, v.name);
    grid.appendChild(cell);
  });
}

// Client-side search + type filter + sort over the loaded page.
function filterLibrary() {
  const all = window._svcsLibrary.all || [];
  const q = ((document.getElementById("library-search") || {}).value || "").trim().toLowerCase();
  const ext = ((document.getElementById("library-ext") || {}).value || "").toLowerCase();
  const sortVal = (document.getElementById("library-sort") || {}).value || "date-desc";
  const kind = window._svcsLibrary.kind || "all";
  let list = all.filter((v) => {
    if (q && !v.name.toLowerCase().includes(q)) return false;
    if (ext && !v.name.toLowerCase().endsWith("." + ext)) return false;
    if (kind === "compressed" && v.kind !== "compressed") return false;
    if (kind === "original" && v.kind === "compressed") return false;
    return true;
  });
  const [field, dir] = sortVal.split("-");
  const cmp = {
    name: (a, b) => a.name.toLowerCase().localeCompare(b.name.toLowerCase()),
    size: (a, b) => a.size - b.size,
    date: (a, b) => a.mtime - b.mtime,
  }[field] || ((a, b) => a.mtime - b.mtime);
  list.sort(cmp);
  if (dir === "desc") list.reverse();
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
    const url = "/api/library/videos" + (folder ? "?folder=" + _enc(folder) : "");
    const data = await (await fetch(url)).json();
    if (folderEl && !folderEl.value && data.folder) folderEl.value = data.folder;
    window._svcsLibrary.loaded = true;
    window._svcsLibrary.folder = data.folder || folder;
    window._svcsLibrary.all = data.videos || [];
    _populateExtFilter(data.extensions);
    if (data.exists === false) {
      const empty = document.getElementById("library-empty");
      if (empty) empty.style.display = "block";
      _libStatus("Folder not found. Click Browse to pick one.");
      const grid = document.getElementById("library-grid");
      if (grid) grid.innerHTML = "";
      return;
    }
    filterLibrary();
  } catch (e) {
    _libStatus("Could not load the library.");
  }
}
window.loadLibrary = loadLibrary;

// ── Folder browser modal (R2.3 follow-up) ───────────────────────────────────
// A server-side navigator (works in the frozen app + remotely, unlike a native
// OS dialog). Walks directories via /api/library/list_dirs.
window._lbPath = "";

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

async function browseLibraryFolder() {
  _showBrowseModal(true);
  const folderEl = document.getElementById("library-folder");
  const start = (folderEl && folderEl.value.trim()) || "";
  await _lbNavigate(start);
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
  const folderEl = document.getElementById("library-folder");
  if (folderEl) folderEl.value = window._lbPath;
  closeBrowseModal();
  loadLibrary();
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
      metaEl.innerHTML =
        "Size: " + _fmtSize(m.size) + "<br>"
        + "Resolution: " + (m.width || "?") + " x " + (m.height || "?") + "<br>"
        + "Codec: " + (m.codec_name || "n/a") + "<br>"
        + "Frame rate: " + (m.r_frame_rate || "n/a") + "<br>"
        + "Duration: " + dur;
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

/*
 * src/gui/static/js/library.js
 *
 * Library / gallery tab (FIX 6).
 *
 * Browse videos in a folder (defaults to the chosen output folder) as a
 * thumbnail grid or list, open a detail view with an inline player and
 * metadata, and send a clip into the existing compress flow. Thumbnails come
 * from /api/library/thumb (generated lazily and cached server-side). Loads
 * lazily the first time the LIBRARY tab is opened. Degrades to no-ops if the
 * DOM hooks are absent. Author: Bloodawn (KheivenD), 2026-06-03 (FIX 6).
 */
"use strict";

window._svcsLibrary = { view: "grid", folder: "", loaded: false, selected: null };

function _libStatus(msg) {
  const el = document.getElementById("library-status");
  if (el) el.textContent = msg || "";
}

function _enc(p) { return encodeURIComponent(p); }

function _fmtSize(bytes) {
  if (!bytes && bytes !== 0) return "";
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
  if (window._svcsLibrary._last) _renderLibrary(window._svcsLibrary._last);
}
window.setLibraryView = setLibraryView;

function _renderLibrary(data) {
  window._svcsLibrary._last = data;
  const grid = document.getElementById("library-grid");
  const count = document.getElementById("library-count");
  if (!grid) return;
  grid.innerHTML = "";
  const vids = data.videos || [];
  if (count) count.textContent = data.total != null ? data.total + " video(s)" : "";
  if (!vids.length) {
    _libStatus(data.exists === false
      ? "Folder not found. Enter a different path and press Load."
      : "No videos in this folder.");
    return;
  }
  _libStatus("");
  const isList = window._svcsLibrary.view === "list";
  vids.forEach((v) => {
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
    img.onerror = () => { img.style.background = "#111"; img.removeAttribute("src"); };
    const label = document.createElement("div");
    label.style.cssText = "font-family:var(--mono);font-size:0.6rem;padding:0.3rem;color:var(--text);word-break:break-all;";
    label.textContent = v.name + (isList ? "   " + _fmtSize(v.size) : "");
    cell.appendChild(img);
    cell.appendChild(label);
    cell.onclick = () => openLibraryDetail(v.path, v.name);
    grid.appendChild(cell);
  });
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
    _renderLibrary(data);
  } catch (e) {
    _libStatus("Could not load the library.");
  }
}
window.loadLibrary = loadLibrary;

async function openLibraryDetail(path, name) {
  window._svcsLibrary.selected = path;
  const grid = document.getElementById("library-grid");
  const detail = document.getElementById("library-detail");
  if (grid) grid.style.display = "none";
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
  if (player) { player.pause && player.pause(); player.removeAttribute("src"); player.load && player.load(); }
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

// Lazy-load the first time the LIBRARY tab is opened.
window.addEventListener("DOMContentLoaded", () => {
  const btn = document.querySelector('.tab-btn[data-tab="library"]');
  if (btn) {
    btn.addEventListener("click", () => {
      if (!window._svcsLibrary.loaded) loadLibrary();
    });
  }
});

/*
 * src/gui/static/js/tabs.js
 *
 * Small behaviors for the redesigned dashboard tabs (section 8 of
 * docs/REDESIGN.md): Show/Hide on secret fields, the Tools section list, the
 * Metrics tiles, charts and column menu, and the Search filter chips. Loaded
 * after the per tab scripts. Only touches the DOM; it never changes compression
 * code, view models or navigation.
 *
 * Author: Bloodawn (KheivenD), 2026-11-08.
 */
"use strict";

function _xEsc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function _xGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
function _xSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* private mode */ } }

// Show or hide a password style field. The button label and aria-pressed
// always say what a press will do, never just an icon.
function xTogglePw(inputId, btn) {
  const el = document.getElementById(inputId);
  if (!el) return;
  const show = el.type === "password";
  el.type = show ? "text" : "password";
  if (btn) {
    btn.textContent = show ? "Hide" : "Show";
    btn.setAttribute("aria-pressed", String(show));
  }
}
window.xTogglePw = xTogglePw;

// ── Search: example chips, removable filter chips, result view control ─────
function xSearchExample(btn) {
  const q = document.getElementById("nl-search-q");
  if (!q) return;
  q.value = btn.textContent.trim();
  if (typeof runNlSearch === "function") runNlSearch();
}
window.xSearchExample = xSearchExample;

const _ARC_FIELDS = [
  { id: "arc-object-type", label: "Type" }, { id: "arc-color", label: "Color" },
  { id: "arc-scene", label: "Scene" }, { id: "arc-tod", label: "Time of day" },
  { id: "arc-camera-id", label: "Camera" }, { id: "arc-min-rois", label: "Motion at least" },
  { id: "arc-date-from", label: "From" }, { id: "arc-date-to", label: "To" },
  { id: "arc-enc-only", label: "Encrypted only", bool: true },
  { id: "arc-pose-only", label: "Pose verified people only", bool: true },
];

function _arcActive() {
  const out = [];
  _ARC_FIELDS.forEach((f) => {
    const el = document.getElementById(f.id);
    if (!el) return;
    if (f.bool) { if (el.checked) out.push({ id: f.id, text: f.label }); return; }
    const v = (el.value || "").trim();
    if (!v || v === "0") return;
    let shown = v;
    if (el.tagName === "SELECT") {
      const o = el.options[el.selectedIndex];
      shown = (o ? o.textContent : v).replace(/[^\w +\/-]/g, "").trim() || v;
    }
    out.push({ id: f.id, text: f.label + ": " + shown });
  });
  return out;
}

function xArcRenderChips() {
  const act = _arcActive();
  const cnt = document.getElementById("arc-filter-count");
  if (cnt) cnt.textContent = act.length ? (act.length + " active") : "none active";
  const box = document.getElementById("arc-chips");
  if (!box) return;
  if (!act.length) { box.hidden = true; box.innerHTML = ""; return; }
  box.hidden = false;
  box.innerHTML = '<span class="x-chips-lbl">Active filters</span>';
  act.forEach((a) => {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "x-chip";
    b.setAttribute("aria-label", "Remove filter " + a.text);
    const t = document.createElement("span");
    t.textContent = a.text;
    const x = document.createElement("span");
    x.className = "x-x"; x.setAttribute("aria-hidden", "true"); x.textContent = "\u00d7";
    b.appendChild(t); b.appendChild(x);
    b.onclick = () => {
      const el = document.getElementById(a.id);
      if (!el) return;
      if (el.type === "checkbox") el.checked = false; else el.value = "";
      xArcRenderChips();
      if (typeof runArchiveSearch === "function") runArchiveSearch();
    };
    box.appendChild(b);
  });
}
window.xArcRenderChips = xArcRenderChips;

function xArcView(which) {
  ["results", "busiest", "daily"].forEach((k) => {
    const b = document.getElementById("arc-view-" + k);
    if (b) b.setAttribute("aria-pressed", String(k === which));
  });
  if (which === "busiest" && typeof loadArchiveBusiest === "function") loadArchiveBusiest();
  else if (which === "daily" && typeof loadArchiveDaily === "function") loadArchiveDaily();
  else if (typeof runArchiveSearch === "function") runArchiveSearch();
}
window.xArcView = xArcView;

document.addEventListener("DOMContentLoaded", () => {
  const panel = document.getElementById("arc-filters-panel");
  if (panel) {
    panel.addEventListener("change", xArcRenderChips);
    panel.addEventListener("input", xArcRenderChips);
  }
  // A smart search fills the filters; show them as chips afterwards.
  const nl = document.getElementById("nl-search-q");
  if (nl) nl.addEventListener("keyup", () => setTimeout(xArcRenderChips, 400));
  xArcRenderChips();
});

// ── Metrics: slide-over, columns menu, charts, measured savings ────────────
function xMetricsOpen() {
  const r = document.getElementById("metrics-right");
  if (r) r.classList.add("is-open");
}
function xMetricsClose() {
  const r = document.getElementById("metrics-right");
  if (r) r.classList.remove("is-open");
  const v = document.getElementById("metrics-video");
  if (v && v.pause) v.pause();
  document.querySelectorAll("#segments-tbody tr.row-selected").forEach((t) => t.classList.remove("row-selected"));
}
window.xMetricsOpen = xMetricsOpen;
window.xMetricsClose = xMetricsClose;

document.addEventListener("keydown", (e) => {
  if (e.key !== "Escape") return;
  const r = document.getElementById("metrics-right");
  if (r && r.classList.contains("is-open")) xMetricsClose();
});

function _xFmtMb(mb) {
  if (mb >= 1024) return (mb / 1024).toFixed(2) + " GB";
  if (mb >= 10) return mb.toFixed(0) + " MB";
  return mb.toFixed(1) + " MB";
}

function _xDayKey(ts) {
  // "20260407T143022Z" -> "2026-04-07"
  if (!ts || ts.length < 8) return null;
  return ts.slice(0, 4) + "-" + ts.slice(4, 6) + "-" + ts.slice(6, 8);
}

// One series per chart, direct value labels on every bar, a text summary for
// screen readers, and a table version behind the "View as table" link.
function _xBars(el, items, color, summary) {
  if (!el) return;
  if (!items.length) {
    el.innerHTML = '<p class="x-hint">Nothing to chart yet. Record or compress a clip and it shows up here.</p>';
    return;
  }
  const W = 560, H = 190, padT = 22, padB = 30, padX = 10;
  const max = Math.max.apply(null, items.map((i) => i.value)) || 1;
  const slot = (W - padX * 2) / items.length;
  const bw = Math.min(46, slot * 0.62);
  let g = "";
  items.forEach((it, i) => {
    const h = Math.max(2, (it.value / max) * (H - padT - padB));
    const x = padX + slot * i + (slot - bw) / 2;
    const y = H - padB - h;
    g += '<rect x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + bw.toFixed(1) + '" height="' + h.toFixed(1) + '" rx="3" fill="' + color + '"/>';
    g += '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (y - 5).toFixed(1) + '" text-anchor="middle" class="x-ct">' + _xEsc(it.text) + '</text>';
    g += '<text x="' + (x + bw / 2).toFixed(1) + '" y="' + (H - 10) + '" text-anchor="middle" class="x-ct x-ct-dim">' + _xEsc(it.label) + '</text>';
  });
  el.innerHTML = '<svg viewBox="0 0 ' + W + ' ' + H + '" role="img" aria-label="' + _xEsc(summary) + '" preserveAspectRatio="xMidYMid meet">' + g + '</svg>';
}

function _xTable(el, head, rows) {
  if (!el) return;
  el.innerHTML = '<table><thead><tr><th>' + _xEsc(head[0]) + '</th><th>' + _xEsc(head[1]) + '</th></tr></thead><tbody>' +
    rows.map((r) => '<tr><td>' + _xEsc(r[0]) + '</td><td>' + _xEsc(r[1]) + '</td></tr>').join("") + '</tbody></table>';
}

function xChartTable(which, btn) {
  const chart = document.getElementById("mchart-" + which);
  const tbl = document.getElementById("mchart-" + which + "-table");
  if (!chart || !tbl) return;
  const showTable = tbl.hidden;
  tbl.hidden = !showTable;
  chart.hidden = showTable;
  if (btn) {
    btn.textContent = showTable ? "View as chart" : "View as table";
    btn.setAttribute("aria-expanded", String(showTable));
  }
}
window.xChartTable = xChartTable;

function xMetricsCharts(segments) {
  segments = segments || [];
  // Per day: total compressed size recorded, last 14 days that have footage.
  const byDay = {};
  segments.forEach((s) => {
    const k = _xDayKey(s.timestamp);
    if (!k) return;
    byDay[k] = (byDay[k] || 0) + (s.file_size_kb || 0) / 1024;
  });
  const days = Object.keys(byDay).sort().slice(-14);
  const dayItems = days.map((d) => ({ label: d.slice(5), value: byDay[d], text: _xFmtMb(byDay[d]) }));
  _xBars(document.getElementById("mchart-day"), dayItems, "var(--amber)",
    dayItems.length ? "Footage recorded per day. " + dayItems.map((i) => i.label + ": " + i.text).join(", ") + "." : "No footage yet.");
  _xTable(document.getElementById("mchart-day-table"), ["Day", "Recorded"], dayItems.map((i) => [i.label, i.text]));

  // Per mode: average clip size.
  const byMode = {};
  segments.forEach((s) => {
    const m = (typeof _segMode === "function") ? _segMode(s) : "?";
    (byMode[m] = byMode[m] || []).push((s.file_size_kb || 0) / 1024);
  });
  const modeItems = Object.keys(byMode).sort().map((m) => {
    const arr = byMode[m];
    const avg = arr.reduce((a, b) => a + b, 0) / arr.length;
    return { label: m, value: avg, text: _xFmtMb(avg) };
  });
  _xBars(document.getElementById("mchart-mode"), modeItems, "var(--teal)",
    modeItems.length ? "Average clip size by mode. " + modeItems.map((i) => i.label + ": " + i.text).join(", ") + "." : "No clips yet.");
  _xTable(document.getElementById("mchart-mode-table"), ["Mode", "Average clip size"], modeItems.map((i) => [i.label, i.text]));
}
window.xMetricsCharts = xMetricsCharts;

// "Space saved": measured numbers when SVCS compressed real files, otherwise
// the old estimate with its caveat spelled out.
let _xSavingsBusy = false;
async function xMetricsMeasured() {
  if (_xSavingsBusy) return;
  _xSavingsBusy = true;
  try {
    const d = await (await fetch("/api/savings")).json();
    const m = d && (d.measured || d);
    const v = document.getElementById("mlib-saved");
    const note = document.getElementById("mlib-saved-note");
    if (m && m.files > 0 && m.saved_pct != null && v && note) {
      v.textContent = m.saved_pct + "%";
      note.textContent = "Smaller. Measured on " + m.files + (m.files === 1 ? " file" : " files") + ", " + _xFmtMb(m.saved_bytes / 1048576) + " saved";
    } else if (note) {
      note.textContent = "Estimate against raw video. Compress files from the Library to measure it.";
    }
  } catch (e) { /* keep the estimate */ }
  finally { _xSavingsBusy = false; }
}
window.xMetricsMeasured = xMetricsMeasured;

(function _xWrapMetrics() {
  document.addEventListener("DOMContentLoaded", () => {
    if (typeof _updateLibrarySummary === "function") {
      const orig = _updateLibrarySummary;
      window._updateLibrarySummary = function (segs) { orig(segs); xMetricsCharts(segs); xMetricsMeasured(); };
    }
    if (typeof showMetricsDetail === "function") {
      const origShow = showMetricsDetail;
      window.showMetricsDetail = function (s) { origShow(s); xMetricsOpen(); };
    }
    // Columns menu
    const menu = document.getElementById("metrics-colmenu");
    const table = document.getElementById("metrics-table");
    if (menu && table) {
      let saved = {};
      try { saved = JSON.parse(_xGet("svcs.metrics.cols") || "{}"); } catch (e) { saved = {}; }
      menu.querySelectorAll("input[data-col]").forEach((cb) => {
        const col = cb.dataset.col;
        cb.checked = !!saved[col];
        table.classList.toggle("hide-c-" + col, !cb.checked);
        cb.addEventListener("change", () => {
          table.classList.toggle("hide-c-" + col, !cb.checked);
          saved[col] = cb.checked;
          _xSet("svcs.metrics.cols", JSON.stringify(saved));
        });
      });
    }
    xMetricsCharts([]);
  });
})();

// ── Tools: section list ────────────────────────────────────────────────────
// Built from the cards that exist, so a card the page does not have never
// leaves a dead link. A link opens its card (they are <details>) and scrolls.
function xBuildToolsNav() {
  const nav = document.getElementById("tools-secnav");
  const body = document.getElementById("tab-tools-body");
  if (!nav || !body) return;
  const items = [];
  const names = {
    "update-panel": "App updates", "push-panel": "Phone alerts", "webhook-panel": "Webhook",
    "events-panel": "Recent events", "zone-editor-panel": "Zone editor", "devices-panel": "Paired devices",
    "danger-zone": "Danger zone",
  };
  const streaming = body.querySelector('[data-sec="streaming"]');
  Array.prototype.forEach.call(body.children, (el) => {
    if (names[el.id]) items.push({ id: el.id, label: names[el.id] });
  });
  if (streaming) {
    if (!streaming.id) streaming.id = "tools-streaming";
    // Streaming sits just before the Danger zone in page order.
    const di = items.findIndex((i) => i.id === "danger-zone");
    const entry = { id: streaming.id, label: "Streaming" };
    if (di >= 0) items.splice(di, 0, entry); else items.push(entry);
  }
  nav.innerHTML = "";
  items.forEach((it) => {
    const a = document.createElement("a");
    a.href = "#" + it.id;
    a.textContent = it.label;
    a.addEventListener("click", (e) => {
      e.preventDefault();
      const t = document.getElementById(it.id);
      if (!t) return;
      if (t.tagName === "DETAILS") t.open = true;
      t.scrollIntoView({ behavior: "smooth", block: "start" });
      nav.querySelectorAll("a").forEach((x) => x.removeAttribute("aria-current"));
      a.setAttribute("aria-current", "true");
    });
    nav.appendChild(a);
  });
}
window.xBuildToolsNav = xBuildToolsNav;
window.addEventListener("DOMContentLoaded", xBuildToolsNav);

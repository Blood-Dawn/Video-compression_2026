/*
 * src/gui/static/js/events.js
 *
 * Recent behavior events panel (Week 3 TASKS 3.5/3.6).
 *
 * Read-only: this panel just shows what fired. It's backed by the existing
 * GET /api/events/recent (R5 TASK 5.7), which tails the configured output
 * folder's events.jsonl newest-first. Nothing here writes anything.
 *
 * Auto-refresh is tied to the <details> panel's own open/closed state
 * (wired from index.html's ontoggle) rather than running from page load,
 * so a dashboard sitting on another tab never polls in the background.
 *
 * Author: Bloodawn (KheivenD), Week 3 (3.5/3.6).
 */
"use strict";

let _eventsTimer = null;
let _eventsInFlight = false;

function _eventsDetail(ev) {
  if (ev.kind === "line_crossing") {
    const dir = ev.direction ? `heading ${ev.direction}` : "";
    const at = ev.geometry_id ? `at ${ev.geometry_id}` : "";
    return escHtml([at, dir].filter(Boolean).join(" "));
  }
  if (ev.kind === "loitering") {
    const dwell = ev.dwell_s != null ? `${Math.round(Number(ev.dwell_s))}s` : "";
    const at = ev.geometry_id ? `in ${ev.geometry_id}` : "";
    return escHtml([at, dwell].filter(Boolean).join(" "));
  }
  return escHtml(ev.geometry_id || "");
}

function _eventsRow(ev) {
  const when = ev.wall_time
    ? (() => { try { return new Date(ev.wall_time).toLocaleString(); }
               catch { return ev.wall_time; } })()
    : " - ";
  const kind = String(ev.kind || "event").replace(/_/g, " ");
  return `<tr style="border-bottom:1px solid var(--border);">
    <td style="padding:0.25rem 0.4rem;white-space:nowrap;">${escHtml(when)}</td>
    <td style="padding:0.25rem 0.4rem;">${escHtml(ev.camera_id || "-")}</td>
    <td style="padding:0.25rem 0.4rem;">${escHtml(kind)}</td>
    <td style="padding:0.25rem 0.4rem;">${escHtml(ev.label || "-")}</td>
    <td style="padding:0.25rem 0.4rem;color:var(--text-dim);">${_eventsDetail(ev)}</td>
  </tr>`;
}

async function eventsRefresh() {
  if (_eventsInFlight) return;
  _eventsInFlight = true;
  const rows = document.getElementById("events-rows");
  const empty = document.getElementById("events-empty");
  const updated = document.getElementById("events-updated");
  try {
    const data = await (await fetch("/api/events/recent?limit=100")).json();
    const events = Array.isArray(data && data.events) ? data.events : [];
    if (rows) rows.innerHTML = events.map(_eventsRow).join("");
    if (empty) empty.style.display = events.length ? "none" : "block";
    if (updated) updated.textContent = "updated " + new Date().toLocaleTimeString();
  } catch (e) {
    if (updated) updated.textContent = "could not refresh";
  } finally {
    _eventsInFlight = false;
  }
}
window.eventsRefresh = eventsRefresh;

function eventsAutoStart() {
  eventsAutoStop();
  _eventsTimer = window.setInterval(eventsRefresh, 10000);
}
window.eventsAutoStart = eventsAutoStart;

function eventsAutoStop() {
  if (_eventsTimer) { window.clearInterval(_eventsTimer); _eventsTimer = null; }
}
window.eventsAutoStop = eventsAutoStop;

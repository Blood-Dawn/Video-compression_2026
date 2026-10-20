/*
 * src/gui/static/js/global_status.js
 *
 * Persistent server-activity drawer.
 *
 * A second, always-mounted render target for the live status (/api/status,
 * polled by status.js) and live log (/api/logs SSE, pipeline.js) that the
 * HOME tab shows, so "what is SVCS doing right now" is visible from every tab.
 * status.js and pipeline.js feed it directly (_updateGlobalStatus() and
 * _appendLogTo()); this file only opens, closes and clears the drawer.
 *
 * Author: Bloodawn (KheivenD), 2026-09-30.
 */
"use strict";

function toggleGlobalStatus() {
  const drawer = document.getElementById("global-drawer");
  const btn = document.getElementById("global-activity-toggle");
  if (!drawer) return;
  const open = !drawer.classList.contains("open");
  drawer.classList.toggle("open", open);
  document.body.classList.toggle("global-drawer-open", open);
  if (btn) btn.classList.toggle("lit", open);
  if (open) {
    const term = document.getElementById("global-log-terminal");
    if (term) term.scrollTop = term.scrollHeight;
  }
}
window.toggleGlobalStatus = toggleGlobalStatus;

function clearGlobalLog() {
  const el = document.getElementById("global-log-terminal");
  if (el) el.innerHTML = "";
}
window.clearGlobalLog = clearGlobalLog;

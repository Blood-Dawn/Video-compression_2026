/*
 * src/gui/static/js/global_status.js
 *
 * Persistent server-activity drawer (2026-09-30 follow-up).
 *
 * The dashboard already streams live status (/api/status, polled every
 * 1.2s by status.js) and a live log (/api/logs, SSE, rendered by
 * pipeline.js's appendLog()) continuously from page load - but both only
 * ever rendered into elements that live inside the HOME tab's markup, so
 * none of it was visible from any other tab, and the console window was
 * the only place that ever showed things like an update check or an
 * auto-compress daemon event. This file just opens a second, always-
 * mounted render target for that SAME data (status.js and pipeline.js
 * feed it directly, see _updateGlobalStatus() / _appendLogTo()) so "what
 * is SVCS doing right now" no longer requires either switching to Home
 * or watching the console window.
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

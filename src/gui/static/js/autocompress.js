/*
 * src/gui/static/js/autocompress.js
 *
 * AUTO-COMPRESS tab (R3.1c).
 *
 * Drives the opt-in auto-compress daemon (gui.routes.autocompress_bp): turn ON
 * to watch a folder and compress any video saved into it; "Compress existing
 * now" runs one batch pass over the folder. Nothing starts on its own - the
 * daemon starts only when the operator turns it ON here.
 *
 * Reuses the Library folder-browse endpoint for the picker and the SSE /api/logs
 * stream for the live activity log. Status is polled while the tab is visible.
 *
 * Author: Bloodawn (KheivenD), 2026-06-06 (R3.1c - auto-compress tab).
 */

let _acRunning = false;
let _acPoll = null;
let _acLogSource = null;
let _acFormRestored = false;

function _acEnc(s) { return encodeURIComponent(s); }

function _acSelectedCompression() {
  // The compression <select> encodes "mode:<x>" or "preset:<key>".
  const raw = (document.getElementById("ac-mode")?.value || "mode:mode0");
  const [kind, val] = raw.split(":");
  return kind === "preset" ? { preset: val } : { mode: val || "mode0" };
}

function _acRequestBody() {
  const body = {
    folder: (document.getElementById("ac-folder")?.value || "").trim(),
    profile: (document.getElementById("ac-profile")?.value || "") || null,
    delete_original: !!document.getElementById("ac-delete-original")?.checked,
  };
  Object.assign(body, _acSelectedCompression());
  return body;
}

// ── Folder picker (reuses the Library native-dialog endpoint) ─────────────────
async function acBrowseFolder() {
  try {
    const data = await (await fetch("/api/library/browse_folder")).json();
    if (data && data.path) document.getElementById("ac-folder").value = data.path;
  } catch (e) {
    // Native dialog unavailable (e.g. headless) - the operator can type a path.
  }
}
window.acBrowseFolder = acBrowseFolder;

// ── Delete-original opt-in: one-time warning on enable ────────────────────────
function acOnDeleteToggle() {
  const cb = document.getElementById("ac-delete-original");
  const warn = document.getElementById("ac-delete-warn");
  if (cb && cb.checked) {
    const ok = window.confirm(
      "Delete originals after compress?\n\n" +
      "Originals will be permanently deleted after a verified compress. The " +
      "source video is removed only AFTER a valid compressed copy has been " +
      "written and verified. This cannot be undone.\n\nContinue?"
    );
    if (!ok) { cb.checked = false; if (warn) warn.textContent = ""; return; }
    if (warn) warn.textContent = "Originals will be deleted after a verified compress.";
  } else if (warn) {
    warn.textContent = "";
  }
}
window.acOnDeleteToggle = acOnDeleteToggle;

// ── ON/OFF ────────────────────────────────────────────────────────────────────
async function acToggle() {
  if (_acRunning) { await _acStop(); return; }
  await _acStart();
}
window.acToggle = acToggle;

async function _acStart() {
  const body = _acRequestBody();
  if (!body.folder) {
    _acStatusLine("Pick a folder to watch first.");
    return;
  }
  try {
    const resp = await fetch("/api/autocompress/start", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      _acStatusLine("Could not start: " + (data.error || resp.status));
      return;
    }
    _acRenderStatus(data.status);
    if (typeof pushNotif === "function") {
      pushNotif("Auto-compress on", "Watching " + body.folder, "info", null, 4000);
    }
  } catch (e) {
    _acStatusLine("Could not start: " + e);
  }
}

async function _acStop() {
  try {
    const data = await (await fetch("/api/autocompress/stop", { method: "POST" })).json();
    _acRenderStatus(data.status);
  } catch (e) {
    _acStatusLine("Could not stop: " + e);
  }
}

// ── Batch pass over existing clips ────────────────────────────────────────────
async function acScanNow() {
  const body = _acRequestBody();
  if (!body.folder) { _acStatusLine("Pick a folder first."); return; }
  const btn = document.getElementById("ac-scan-btn");
  if (btn) { btn.disabled = true; btn.textContent = "Compressing..."; }
  try {
    const resp = await fetch("/api/autocompress/scan_now", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (resp.ok && data.ok) {
      _acStatusLine("Batch pass done: compressed " + data.compressed + " clip(s).");
      _acRenderStatus(data.status);
      // R4 Phase 1 (NN/g): a batch pass is a long wait - end it with an
      // explicit, user-dismissed summary, and refresh the HOME job record.
      // No compressed>0 gate: an all-failed pass needs the summary MOST
      // (it is recorded status="error"); an idle pass records no history
      // entry, so the kind+freshness check inside makes this a no-op then.
      if (typeof maybeShowLatestJobSummary === "function") {
        maybeShowLatestJobSummary("autocompress");
      }
      if (typeof loadRecentJobs === "function") loadRecentJobs();
    } else {
      _acStatusLine("Batch pass failed: " + (data.error || resp.status));
    }
  } catch (e) {
    _acStatusLine("Batch pass failed: " + e);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Compress existing now"; }
  }
}
window.acScanNow = acScanNow;

// ── Status rendering ──────────────────────────────────────────────────────────
function _acStatusLine(text) {
  const el = document.getElementById("ac-status-line");
  if (el) el.textContent = text;
}

function _basename(p) {
  if (!p) return "";
  return String(p).split(/[\\/]/).pop();
}

function _acRenderStatus(st) {
  if (!st) return;
  _acRunning = !!st.running;

  // Restore the form from the saved config once (so it reopens where it was).
  if (!_acFormRestored && st.saved) {
    const s = st.saved;
    const fEl = document.getElementById("ac-folder");
    if (fEl && !fEl.value && s.folder) fEl.value = s.folder;
    if (s.delete_original) {
      const dc = document.getElementById("ac-delete-original");
      if (dc) dc.checked = true;
      const w = document.getElementById("ac-delete-warn");
      if (w) w.textContent = "Originals will be deleted after a verified compress.";
    }
    const pEl = document.getElementById("ac-profile");
    if (pEl && s.profile) pEl.value = s.profile;
    const mEl = document.getElementById("ac-mode");
    if (mEl && s.mode) mEl.value = "mode:" + s.mode;
    _acFormRestored = true;
  }

  const badge = document.getElementById("ac-state-badge");
  if (badge) {
    badge.textContent = _acRunning ? "ON" : "OFF";
    badge.style.color = _acRunning ? "#ff5fa2" : "var(--text-dim)";
  }
  const btn = document.getElementById("ac-toggle-btn");
  if (btn) btn.textContent = _acRunning ? "Turn OFF" : "Turn ON";

  if (st.batch_total > 0) {
    // R4 Phase 1 (NN/g): batch waits >= 10s need determinate "file N of M"
    // progress, not a spinner. Applies to daemon passes AND "Compress
    // existing now" (which also updates these fields while it runs).
    const cur = Math.min((st.batch_done || 0) + 1, st.batch_total);
    _acStatusLine("Compressing file " + cur + " of " + st.batch_total +
                  (st.current_file ? ": " + st.current_file : ""));
  } else if (_acRunning) {
    const folder = st.folder || (st.saved && st.saved.folder) || "";
    _acStatusLine("Watching " + folder + "   queue: " + (st.queue || 0) +
                  "   compressed this session: " + (st.compressed_total || 0));
  } else if (st.compressed_total) {
    _acStatusLine("Stopped. Compressed " + st.compressed_total + " clip(s) this session.");
  } else {
    _acStatusLine("Idle. Not watching.");
  }

  const recEl = document.getElementById("ac-recent");
  if (recEl) {
    const recent = st.recent || [];
    if (!recent.length) {
      // Empty state (R4 Phase 1, NN/g): say what appears here and why it is
      // empty, and point at the actions that populate it.
      recEl.textContent = _acRunning
        ? "Nothing compressed yet. Clips saved into the watched folder will be compressed and listed here."
        : "Nothing compressed yet. Turn ON watching, or use \"Compress existing now\" to process the clips already in the folder.";
    } else {
      recEl.innerHTML = recent.slice(0, 8).map(r =>
        _esc(_basename(r.source)) + "  &rarr;  compressed/" + _esc(_basename(r.output))
      ).join("<br>");
    }
  }
  if (st.last_error) _acStatusLine((document.getElementById("ac-status-line")?.textContent || "") + "  (last error: " + st.last_error + ")");
}

function _esc(s) {
  return String(s == null ? "" : s)
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

async function acRefreshStatus() {
  try {
    const st = await (await fetch("/api/autocompress/status")).json();
    _acRenderStatus(st);
  } catch (e) { /* transient - keep last render */ }
}
window.acRefreshStatus = acRefreshStatus;

// ── Live log (reuse SSE /api/logs) ────────────────────────────────────────────
function _acStartLog() {
  if (_acLogSource) return;
  try {
    _acLogSource = new EventSource("/api/logs");
    _acLogSource.onmessage = (ev) => {
      let line;
      try { line = JSON.parse(ev.data); } catch (e) { line = ev.data; }
      const el = document.getElementById("ac-log");
      if (!el) return;
      const span = document.createElement("span");
      span.textContent = line + "\n";
      el.appendChild(span);
      while (el.children.length > 400) el.removeChild(el.firstChild);
      el.scrollTop = el.scrollHeight;
    };
    _acLogSource.onerror = () => { /* the browser auto-reconnects */ };
  } catch (e) { /* SSE unsupported - log panel stays empty */ }
}

function _acStopLog() {
  if (_acLogSource) { _acLogSource.close(); _acLogSource = null; }
}

// ── Retention / disk budget (R4 Phase 3) ──────────────────────────────────────
let _retLoaded = false;

function _retFmtDays(d) {
  if (d == null) return "unknown";
  if (d >= 365) return (d / 365).toFixed(1) + " years";
  if (d >= 60) return (d / 30).toFixed(1) + " months";
  return d + " days";
}

function _retRenderEstimate(est) {
  const el = document.getElementById("ret-estimate");
  if (!el || !est) return;
  if (!est.available) { el.textContent = ""; return; }
  const lines = [];
  if (est.used_gb != null) lines.push("Compressed on disk: " + est.used_gb + " GB");
  if (est.free_gb != null) lines.push("Free disk: " + est.free_gb + " GB");
  if (est.bytes_per_day != null) {
    const gbday = (est.bytes_per_day / 1e9).toFixed(2);
    lines.push("Recent rate: ~" + gbday + " GB/day");
  }
  if (est.est_days_headroom != null) {
    lines.push("Estimated headroom: ~" + _retFmtDays(est.est_days_headroom));
  } else {
    lines.push("Headroom: record more footage to estimate");
  }
  el.innerHTML = lines.map(_esc).join("<br>");
}

async function retentionRefresh() {
  try {
    const data = await (await fetch("/api/retention")).json();
    if (!data || !data.policy) return;
    const p = data.policy;
    const en = document.getElementById("ret-enabled");
    const age = document.getElementById("ret-max-age");
    const gb = document.getElementById("ret-max-gb");
    if (en) en.checked = !!p.enabled;
    if (age && !_retLoaded) age.value = p.max_age_days || "";
    if (gb && !_retLoaded) gb.value = p.max_total_gb || "";
    _retLoaded = true;
    _retRenderEstimate(data.estimate);
  } catch (e) { /* keep last render */ }
}
window.retentionRefresh = retentionRefresh;

async function retentionSave() {
  const body = {
    enabled: !!document.getElementById("ret-enabled")?.checked,
    max_age_days: (document.getElementById("ret-max-age")?.value || "0").trim() || "0",
    max_total_gb: (document.getElementById("ret-max-gb")?.value || "0").trim() || "0",
  };
  try {
    const data = await (await fetch("/api/retention", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })).json();
    if (data && data.estimate) _retRenderEstimate(data.estimate);
  } catch (e) { /* transient */ }
}
window.retentionSave = retentionSave;

async function retentionPurgeNow() {
  const btn = document.getElementById("ret-purge-btn");
  if (!document.getElementById("ret-enabled")?.checked) {
    if (typeof pushNotif === "function")
      pushNotif("Retention off", "Enable retention and set a limit before purging.", "info", null, 5000);
    return;
  }
  if (!window.confirm("Delete old compressed clips now that exceed the retention limits? This cannot be undone.")) return;
  if (btn) { btn.disabled = true; btn.textContent = "Purging..."; }
  try {
    const data = await (await fetch("/api/retention/purge_now", { method: "POST" })).json();
    const s = data.summary || {};
    if (typeof pushNotif === "function") {
      pushNotif("Retention purge",
        s.ran ? ("Deleted " + (s.deleted || 0) + " clip(s), freed " +
                 ((s.freed_bytes || 0) / 1e6).toFixed(1) + " MB")
              : "Nothing to purge (no clips over the limit).",
        "success", null, 5000);
    }
    if (data.estimate) _retRenderEstimate(data.estimate);
    if (typeof loadRecentJobs === "function") loadRecentJobs();
  } catch (e) {
    if (typeof pushNotif === "function") pushNotif("Retention purge failed", String(e), "error", null, 5000);
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Purge now"; }
  }
}
window.retentionPurgeNow = retentionPurgeNow;

// ── Tab show/hide lifecycle (called from switchTab) ───────────────────────────
function acOnTabShow() {
  acRefreshStatus();
  retentionRefresh();
  _acStartLog();
  if (_acPoll) clearInterval(_acPoll);
  _acPoll = setInterval(acRefreshStatus, 2500);
}
window.acOnTabShow = acOnTabShow;

function acOnTabHide() {
  if (_acPoll) { clearInterval(_acPoll); _acPoll = null; }
  _acStopLog();
}
window.acOnTabHide = acOnTabHide;

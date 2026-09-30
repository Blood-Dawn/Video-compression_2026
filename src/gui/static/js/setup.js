/*
 * src/gui/static/js/setup.js
 *
 * First-run Setup + destination chooser (FIX 1).
 *
 * On first run (no persisted choice) this shows a Setup overlay where the user
 * explicitly picks where compressed output and encrypted output go. Nothing is
 * auto-selected and no cloud folder is ever chosen implicitly. Until a choice is
 * made, the START button is disabled. The choice persists server-side
 * (/api/setup/choose) so the overlay does not reappear. The same overlay is
 * reachable later via window.openSetup() from settings.
 *
 * Author: Bloodawn (KheivenD), 2026-06-03 (FIX 1).
 */
"use strict";

window._svcsSetup = { complete: false, output_dir: "", encrypted_dir: "" };

function _setStartEnabled(enabled) {
  const btn = document.getElementById("btn-start");
  if (!btn) return;
  btn.disabled = !enabled;
  btn.style.opacity = enabled ? "" : "0.5";
  btn.style.pointerEvents = enabled ? "" : "none";
  btn.title = enabled ? "" : "Choose an output destination in Setup first";
}

function _setOutputFields(path) {
  if (!path) return;
  const out = document.getElementById("output-dir");
  if (out) out.value = path;
  const demo = document.getElementById("demo-output-dir");
  if (demo && !demo.value) demo.value = path;
}

function _showSetupOverlay(show) {
  const ov = document.getElementById("setup-overlay");
  if (ov) ov.style.display = show ? "flex" : "none";
}

function _setupError(msg) {
  const el = document.getElementById("setup-error");
  if (el) el.textContent = msg || "";
}

function _defaultEncryptedFor(outPath) {
  if (!outPath) return "";
  const sep = outPath.includes("\\") ? "\\" : "/";
  return outPath.replace(/[\\/]+$/, "") + sep + "Encrypted";
}

async function _populateDestinations() {
  const sel = document.getElementById("setup-dest-select");
  if (!sel) return;
  let data;
  try {
    data = await (await fetch("/api/setup/destinations")).json();
  } catch (e) {
    _setupError("Could not load destinations. Type a folder path below.");
    return;
  }
  sel.innerHTML = "";
  (data.destinations || []).forEach((d) => {
    const opt = document.createElement("option");
    opt.value = JSON.stringify({ kind: d.kind, path: d.path });
    opt.textContent = d.label + (d.path ? "  (" + d.path + ")" : "");
    sel.appendChild(opt);
  });
  // Apply the first option's path to the inputs as a starting point.
  sel.onchange = () => {
    let v = {};
    try { v = JSON.parse(sel.value); } catch (e) { v = {}; }
    const outEl = document.getElementById("setup-output-dir");
    const encEl = document.getElementById("setup-encrypted-dir");
    if (v.kind === "custom") {
      if (outEl) { outEl.value = ""; outEl.focus(); }
    } else if (outEl) {
      outEl.value = v.path || "";
    }
    if (encEl) encEl.value = _defaultEncryptedFor(outEl ? outEl.value : "");
  };
  sel.onchange();
  // Keep the encrypted default in sync when the user edits the output path.
  const outEl = document.getElementById("setup-output-dir");
  if (outEl) {
    outEl.addEventListener("input", () => {
      const encEl = document.getElementById("setup-encrypted-dir");
      if (encEl && (!encEl.dataset.touched)) encEl.value = _defaultEncryptedFor(outEl.value);
    });
  }
  const encEl = document.getElementById("setup-encrypted-dir");
  if (encEl) encEl.addEventListener("input", () => { encEl.dataset.touched = "1"; });
}

async function _saveSetup(skip) {
  _setupError("");
  let outVal = (document.getElementById("setup-output-dir") || {}).value || "";
  let encVal = (document.getElementById("setup-encrypted-dir") || {}).value || "";
  if (skip) {
    // Skip = use the neutral LOCAL default the server offers (never cloud).
    try {
      const st = await (await fetch("/api/setup/destinations")).json();
      outVal = st.neutral_default || outVal;
      encVal = "";
    } catch (e) { /* fall through with whatever is in the field */ }
  }
  outVal = outVal.trim();
  if (!outVal) { _setupError("Please choose or enter an output folder."); return; }
  try {
    const res = await fetch("/api/setup/choose", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ output_dir: outVal, encrypted_dir: encVal.trim() }),
    });
    const data = await res.json();
    if (!data.ok) { _setupError(data.error || "Could not save."); return; }
    window._svcsSetup = {
      complete: true, output_dir: data.output_dir, encrypted_dir: data.encrypted_dir,
    };
    _setOutputFields(data.output_dir);
    _showSetupOverlay(false);
    _setStartEnabled(true);
    if (typeof pushNotif === "function") {
      pushNotif("Setup complete", "Output: " + data.output_dir, "info", null, 3500);
    }
  } catch (e) {
    _setupError("Could not save the choice. Check the path and try again.");
  }
}
window.saveSetup = _saveSetup;

// Folder-browse buttons (Week 3 TASK 3.13): reuses the Library tab's own
// folder picker (native OS dialog first, in-app server-side browser as the
// remote/headless fallback) rather than standing up a second one just for
// Setup. See library.js's browseFolderInto() for the shared implementation.
function setupBrowseOutputDir() {
  browseFolderInto("setup-output-dir");
}
window.setupBrowseOutputDir = setupBrowseOutputDir;

function setupBrowseEncryptedDir() {
  browseFolderInto("setup-encrypted-dir", () => {
    // A path chosen explicitly here is a deliberate override, same as
    // typing one: stop re-deriving it from the output folder.
    const encEl = document.getElementById("setup-encrypted-dir");
    if (encEl) encEl.dataset.touched = "1";
  });
}
window.setupBrowseEncryptedDir = setupBrowseEncryptedDir;

async function openSetup() {
  await _populateDestinations();
  _showSetupOverlay(true);
}
window.openSetup = openSetup;

// Factory reset (FIX 2): clear per-install state and return to first-run.
async function resetAppData() {
  const ok = window.confirm(
    "Reset app data?\n\nThis clears saved settings, the destination choice, and "
    + "the CPU benchmarks, and returns SVCS to first-run setup. Your compressed "
    + "videos are NOT deleted.");
  if (!ok) return;
  try {
    const res = await fetch("/api/setup/reset", { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      // Reload so the first-run Setup overlay shows again with clean state.
      window.location.reload();
    }
  } catch (e) {
    if (typeof pushNotif === "function") {
      pushNotif("Reset failed", "Could not reset app data.", "error", null, 4000);
    }
  }
}
window.resetAppData = resetAppData;

// Dependency status (FIX 5/8): show whether ffmpeg/mediamtx/onnx are found.
async function checkDependencies() {
  const out = document.getElementById("help-deps-result");
  if (out) out.textContent = "Checking...";
  try {
    const data = await (await fetch("/api/setup/dependencies")).json();
    const deps = data.dependencies || {};
    const lines = Object.keys(deps).map((k) => {
      const d = deps[k];
      const mark = d.present ? "[ok]" : "[missing]";
      return mark + " " + k + (d.present && d.path ? " - " + d.path : "");
    });
    if (out) out.innerHTML = lines.join("<br>");
  } catch (e) {
    if (out) out.textContent = "Could not check dependencies.";
  }
}
window.checkDependencies = checkDependencies;

// In-app update check (Fall 3.17): check + notify only - never downloads or
// installs anything itself. Runs once automatically on dashboard load (silent
// unless something is actually newer, so it never nags on every reload when
// you're already current); the Help > "Check for updates" and Tools >
// "Check for updates" buttons re-run it on demand and always report their
// result, including "up to date".
//
// Fall 3.18 adds the actual pipeline behind /api/update/{status,download,
// install} (gui.services.update_manager) - downloadUpdate()/installUpdate()
// below drive it. The check above still only ever reports; nothing here
// downloads or installs without the user starting it from a button or the
// update notification.
//
// Fall 3.18 UX follow-up (2026-09-30): progress used to live only in a
// hidden help-update-progress span inside the Help glossary panel, so if you
// were not looking at that one tab you would never see it move, and
// installing needed a second manual click plus a confirm() dialog after the
// download had already finished verifying. Now: (1) an update notification
// tracks its own download/verify/install progress in place, visible from any
// tab, and (2) once the download is verified, install starts on its own -
// clicking the notification (or "Check for updates" in Help or Tools) is the
// one click the whole update needs.
async function _checkForUpdate(showResult) {
  const out = document.getElementById("help-update-result");
  const toolsOut = document.getElementById("tools-update-result");
  const actions = document.getElementById("help-update-actions");
  if (showResult) {
    if (out) out.textContent = "Checking...";
    if (toolsOut) toolsOut.textContent = "Checking...";
  }
  let data;
  try {
    data = await (await fetch("/api/setup/update_check")).json();
  } catch (e) {
    if (showResult) {
      if (out) out.textContent = "Could not check for updates.";
      if (toolsOut) toolsOut.textContent = "Could not check for updates.";
    }
    return;
  }
  if (showResult) {
    const msg = !data.checked
      ? "Could not reach GitHub to check."
      : data.update_available
        ? "Update available: " + data.latest_version + " (you have " + data.current_version + ")"
        : "Up to date (" + data.current_version + ").";
    if (out) out.textContent = msg;
    if (toolsOut) toolsOut.textContent = msg;
  }
  if (actions) actions.style.display = data.update_available ? "block" : "none";
  if (data.update_available) {
    _showUpdateNotif(data);
  }
}
window.checkForUpdate = () => _checkForUpdate(true);
window.addEventListener("DOMContentLoaded", () => _checkForUpdate(false));

// -- Fall 3.18: download + verify + install, tracked in a toast notification
// (the Help panel's Download/Install buttons still work directly, but the
// notification is the primary progress display since it stays visible no
// matter which tab is open) -------------------------------------------------

let _updatePollTimer = null;
let _updateNotifCard = null;

function _stopUpdatePolling() {
  if (_updatePollTimer) {
    clearInterval(_updatePollTimer);
    _updatePollTimer = null;
  }
}

function _formatBytes(n) {
  if (!n || n <= 0) return "";
  const mb = n / (1024 * 1024);
  return mb >= 1 ? mb.toFixed(1) + " MB" : Math.round(n / 1024) + " KB";
}

// Puts up the toast that starts the flow. Its button kicks off
// downloadUpdate(); once the checksum verifies, installUpdate() runs on its
// own (see _renderUpdateStatus's "ready" case below), so this is the only
// click the whole update ever needs.
function _showUpdateNotif(info) {
  if (_updateNotifCard && _updateNotifCard.parentNode) return;
  if (typeof pushNotif !== "function") return;
  const actionButtons = info.download_url
    ? [{ label: "Update now", fn: () => downloadUpdate() }]
    : (info.release_url
      ? [{ label: "View release", fn: () => window.open(info.release_url, "_blank") }]
      : null);
  _updateNotifCard = pushNotif(
    "Update available",
    "SVCS " + info.latest_version + " is out - you have " + info.current_version + ".",
    "info",
    actionButtons,
    0,
  );
}

// Writes progress into whichever surfaces are visible: the toast (if the
// flow started from one) and the Help panel's own progress line (for anyone
// who started it from that button instead, or who wants to keep watching
// after the toast is gone).
function _setUpdateMessage(text, opts) {
  opts = opts || {};
  const prog = document.getElementById("help-update-progress");
  if (prog) prog.textContent = text;
  if (_updateNotifCard && _updateNotifCard.parentNode) {
    const msg = _updateNotifCard.querySelector(".notif-msg");
    if (msg) msg.textContent = text;
    if (opts.clearActions) {
      const actionsEl = _updateNotifCard.querySelector(".notif-actions");
      if (actionsEl) actionsEl.remove();
    }
  }
}

function _renderUpdateStatus(status) {
  const dlBtn = document.getElementById("help-update-download-btn");
  const instBtn = document.getElementById("help-update-install-btn");
  switch (status.phase) {
    case "downloading": {
      const pct = status.bytes_total
        ? Math.min(100, Math.round((100 * status.bytes_downloaded) / status.bytes_total))
        : null;
      _setUpdateMessage(
        "Downloading" + (pct !== null ? " " + pct + "%" : "")
        + " (" + _formatBytes(status.bytes_downloaded)
        + (status.bytes_total ? " / " + _formatBytes(status.bytes_total) : "") + ")",
      );
      if (dlBtn) dlBtn.disabled = true;
      break;
    }
    case "verifying":
      _setUpdateMessage("Verifying download...");
      break;
    case "ready":
      _stopUpdatePolling();
      _setUpdateMessage(
        "Verified. Installing " + (status.latest_version || "") + " and restarting...",
        { clearActions: true },
      );
      if (dlBtn) dlBtn.style.display = "none";
      if (instBtn) instBtn.style.display = "none";
      // A verified download is safe by construction (its checksum matched
      // the release's own SHA256SUMS.txt), so chain straight into the
      // restart the user already asked for - no second click.
      installUpdate();
      break;
    case "installing":
      _setUpdateMessage("Installing - SVCS will close and restart shortly...");
      _stopUpdatePolling();
      break;
    case "error":
      _setUpdateMessage("Update failed: " + (status.error || "unknown error"));
      if (dlBtn) { dlBtn.disabled = false; dlBtn.style.display = "inline-block"; }
      if (instBtn) instBtn.style.display = "none";
      _stopUpdatePolling();
      break;
    default:
      _setUpdateMessage("");
  }
}

async function _pollUpdateStatus() {
  let status;
  try {
    status = await (await fetch("/api/update/status")).json();
  } catch (e) {
    // The server may be mid-restart after an install; stop quietly rather
    // than showing a scary error for something that is expected.
    return;
  }
  _renderUpdateStatus(status);
}

// Re-checks GitHub itself and starts a background download + checksum
// verify of whatever it finds - see update_manager's module docstring for
// why this never accepts a URL from the page itself.
async function downloadUpdate() {
  const actions = document.getElementById("help-update-actions");
  if (actions) actions.style.display = "block";
  _setUpdateMessage("Starting download...");
  let status;
  try {
    status = await (await fetch("/api/update/download", { method: "POST" })).json();
  } catch (e) {
    _setUpdateMessage("Could not start the download.");
    return;
  }
  _renderUpdateStatus(status);
  _stopUpdatePolling();
  _updatePollTimer = setInterval(_pollUpdateStatus, 700);
}
window.downloadUpdate = downloadUpdate;

// Called automatically once the download verifies (see _renderUpdateStatus's
// "ready" case) - installing a checksum-verified build is exactly what the
// user already asked for by starting the update, so this no longer stops to
// confirm() a second time.
async function installUpdate() {
  _setUpdateMessage("Installing - SVCS will close and restart shortly...", { clearActions: true });
  try {
    const r = await fetch("/api/update/install", { method: "POST" });
    const body = await r.json();
    if (!r.ok || !body.ok) {
      _setUpdateMessage("Install failed: " + (body.error || "unknown error"));
    }
  } catch (e) {
    // Expected once the app actually exits mid-response for the restart;
    // the "installing" message above already covers this for the user.
  }
}
window.installUpdate = installUpdate;

// Send feedback (fresh-install walkthrough / general bug reports): opens the
// user's own default mail client, pre-addressed and pre-filled. No network
// call, no credentials in the app - the person still has to hit Send
// themselves, this just removes the "what do I even write" friction.
function sendFeedback() {
  const to = "kdhaiti2024@fau.edu";
  const subject = "SVCS feedback";
  const body =
    "What were you doing:\n\n\n" +
    "What happened:\n\n\n" +
    "What did you expect instead:\n\n\n" +
    "---\n" +
    "App: SVCS desktop\n" +
    "Browser/OS info: " + navigator.userAgent;
  const href = "mailto:" + to
    + "?subject=" + encodeURIComponent(subject)
    + "&body=" + encodeURIComponent(body);
  window.location.href = href;
}
window.sendFeedback = sendFeedback;

async function initSetup() {
  let st;
  try {
    st = await (await fetch("/api/setup/state")).json();
  } catch (e) {
    return;  // optional; the field still works without it
  }
  window._svcsSetup.complete = !!st.setup_complete;
  if (st.output_dir) {
    window._svcsSetup.output_dir = st.output_dir;
    window._svcsSetup.encrypted_dir = st.encrypted_dir || "";
    _setOutputFields(st.output_dir);
  }
  if (!st.setup_complete) {
    _setStartEnabled(false);
    await openSetup();
  } else {
    _setStartEnabled(true);
  }
}
window.addEventListener("DOMContentLoaded", initSetup);

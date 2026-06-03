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

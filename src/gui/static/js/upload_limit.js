/*
 * src/gui/static/js/upload_limit.js
 *
 * Settings panel for the per-file upload size cap (GET/POST /api/upload/limit).
 * Default 8 GB. Nothing auto-saves; the operator types a number and presses
 * Save. The server enforces the cap on both upload routes.
 */
"use strict";

function _uploadLimitSay(text, kind) {
  const el = document.getElementById("upload-limit-status");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = kind === "error" ? "var(--red)"
                 : kind === "ok" ? "var(--green)" : "var(--text-dim)";
}

function _uploadLimitApply(cfg) {
  if (!cfg) return;
  const input = document.getElementById("upload-limit-gb");
  if (input) {
    input.value = cfg.max_upload_gb;
    input.min = cfg.min_gb;
    input.max = cfg.max_gb;
  }
  _uploadLimitSay("Default is " + cfg.default_gb + " GB per file.");
}

async function uploadLimitRefresh() {
  try {
    const data = await (await fetch("/api/upload/limit")).json();
    _uploadLimitApply(data && data.config);
  } catch (e) { /* keep whatever is on screen */ }
}
window.uploadLimitRefresh = uploadLimitRefresh;

async function uploadLimitSave() {
  const btn = document.getElementById("upload-limit-save-btn");
  const raw = (document.getElementById("upload-limit-gb")?.value || "").trim();
  const gb = Number(raw);
  if (!raw || !Number.isFinite(gb)) {
    _uploadLimitSay("Enter a number of gigabytes.", "error");
    return;
  }
  if (btn) btn.disabled = true;
  _uploadLimitSay("Saving...");
  try {
    const res = await fetch("/api/upload/limit", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ max_upload_gb: gb }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      _uploadLimitSay(data.error || "Could not save.", "error");
      return;
    }
    _uploadLimitApply(data.config);
    _uploadLimitSay("Saved. Uploads over " + data.config.max_upload_gb + " GB are refused.", "ok");
  } catch (e) {
    _uploadLimitSay(String(e), "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}
window.uploadLimitSave = uploadLimitSave;

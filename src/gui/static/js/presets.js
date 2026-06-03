/*
 * src/gui/static/js/presets.js
 *
 * SVCS dashboard — named surveillance presets (M3 TASK 3.1).
 *
 * Fetches /api/presets and exposes the catalog by NAME so operators pick
 * "Continuous CCTV (max savings)" instead of reasoning about "Mode 2". Applying
 * a preset writes its resolved encode config (mode, CRF, background CRF, codec,
 * object filter, segment length) into the existing sidebar form fields and
 * records the active preset on window._svcsPreset so pipeline.js sends it (and
 * the background CRF) to /api/start. The raw Mode picker stays available behind
 * the existing "Advanced" toggle.
 *
 * Loaded as a classic script; all functions are global. Author: Bloodawn
 * (KheivenD), 2026-06-03 (TASK 3.1).
 */
"use strict";

window._svcsPreset = null;          // {key, background_crf} of the active preset
window._svcsPresetConfigs = {};     // key -> resolved encode config

function _setField(id, value) {
  const el = document.getElementById(id);
  if (!el || value === undefined || value === null) return;
  if (el.type === "checkbox") {
    el.checked = !!value;
  } else {
    el.value = String(value);
  }
  // Fire change/input so any listeners (chips, labels) update.
  el.dispatchEvent(new Event("change", { bubbles: true }));
  el.dispatchEvent(new Event("input", { bubbles: true }));
}

function applyPreset(key) {
  const cfg = window._svcsPresetConfigs[key];
  if (!cfg) return;
  // Mode: set the select and highlight the matching preset card if present.
  _setField("mode-select", cfg.mode);
  document.querySelectorAll(".preset-card").forEach((c) => {
    c.classList.toggle("selected", c.dataset.mode === cfg.mode);
  });
  // Encode params.
  _setField("codec-select", cfg.codec || "auto");
  _setField("crf-input", cfg.crf != null ? cfg.crf : "");
  _setField("bg-method", cfg.bg_method || "MOG2");
  _setField("segment-seconds", cfg.segment_seconds || 60);
  _setField("object-filter-toggle", !!cfg.object_filter);
  // Record the active preset for pipeline.js (it sends preset + background_crf).
  window._svcsPreset = { key: key, background_crf: cfg.background_crf };
  const sel = document.getElementById("preset-select");
  if (sel && sel.value !== key) sel.value = key;
  if (typeof pushNotif === "function") {
    const meta = (window._svcsPresetMeta || {})[key];
    pushNotif("Preset applied", (meta && meta.label) || key, "info", null, 2500);
  }
}
window.applyPreset = applyPreset;

async function loadPresets() {
  let data;
  try {
    const res = await fetch("/api/presets");
    data = await res.json();
  } catch (e) {
    return;  // presets are optional; the form still works without them
  }
  window._svcsPresetConfigs = data.configs || {};
  window._svcsPresetMeta = {};
  (data.presets || []).forEach((p) => { window._svcsPresetMeta[p.key] = p; });

  const sel = document.getElementById("preset-select");
  if (sel) {
    sel.innerHTML = "";
    (data.presets || []).forEach((p) => {
      const opt = document.createElement("option");
      opt.value = p.key;
      opt.textContent = p.label + (p.surveillance ? "" : "  (general)");
      opt.title = p.description || "";
      sel.appendChild(opt);
    });
    sel.value = data.default || (data.presets[0] && data.presets[0].key);
    sel.addEventListener("change", () => applyPreset(sel.value));
    // Apply the default preset on first load so the form starts sensible.
    if (sel.value) applyPreset(sel.value);
  }
}

window.addEventListener("DOMContentLoaded", loadPresets);

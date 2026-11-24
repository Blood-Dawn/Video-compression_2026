/*
 * src/gui/static/js/profile.js
 *
 * Home tab "Profile": save the current settings to a small file, or load one
 * someone else made. Loading sets the same form fields that Start reads, so
 * the values really are the ones the next run uses. After a load the panel
 * lists what the form now holds, read back from the form itself.
 *
 * Credentials (password, key file path) and the video source are never saved.
 */
"use strict";

(function () {
  function el(id) { return document.getElementById(id); }
  function val(id) { var e = el(id); return e ? e.value : ""; }
  function chk(id) { var e = el(id); return !!(e && e.checked); }
  function num(id) { var n = parseFloat(val(id)); return isFinite(n) ? n : null; }

  function collect() {
    var seg = (window.SegPlan && SegPlan.get) ? SegPlan.get() : { kind: "default", seconds: null };
    var panel = el("advanced-panel");
    return {
      svcs_config_version: "1.1",
      saved_at: new Date().toISOString(),
      mode: val("mode-select"),
      preset: (window._svcsPreset && window._svcsPreset.key) || null,
      segment_default: seg.kind !== "fixed",
      segment_seconds: seg.kind === "fixed" ? seg.seconds : null,
      advanced_open: !!(panel && panel.classList.contains("open")),
      bg_method: val("bg-method"),
      warmup_frames: num("warmup-frames"),
      object_filter: chk("object-filter-toggle"),
      filter_confidence: num("filter-confidence"),
      enhance: chk("enhance-toggle"),
      enhance_model: val("enhance-model"),
      enhance_scale: num("enhance-scale"),
      enhance_every_n: num("enhance-every-n"),
      enhance_max_roi_px: num("enhance-max-roi"),
      enhance_device: val("enhance-device"),
      upscale_output: chk("upscale-output-toggle"),
      encrypt: chk("encrypt-toggle"),
      codec: val("codec-select") || "auto",
      crf: num("crf-input"),
      background_crf: (window._svcsPreset && window._svcsPreset.background_crf != null)
        ? window._svcsPreset.background_crf : null,
      verbose: chk("verbose-toggle"),
      target_vmaf: chk("targetvmaf-toggle") ? num("targetvmaf-input") : null,
      max_bitrate_kbps: num("maxbitrate-input"),
      gop_seconds: num("gop-input"),
      denoise: val("denoise-select"),
      roi_qp: chk("roiqp-toggle")
    };
  }

  function save() {
    var p = collect();
    var blob = new Blob([JSON.stringify(p, null, 2)], { type: "application/json" });
    var a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "svcs_profile_" + (p.mode || "settings") + ".json";
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 500);
    note("Saved " + a.download + ".", false);
  }

  function set(id, v) {
    var e = el(id);
    if (!e || v === undefined || v === null) return;
    if (e.type === "checkbox") e.checked = !!v; else e.value = String(v);
    e.dispatchEvent(new Event("input", { bubbles: true }));
    e.dispatchEvent(new Event("change", { bubbles: true }));
  }
  // Apply a normalised profile to the form, in an order that lets explicit
  // values win over what a preset sets.
  function apply(cfg) {
    if (cfg.preset && window._svcsPresetConfigs && window._svcsPresetConfigs[cfg.preset]) {
      applyPreset(cfg.preset);
    } else if (cfg.mode) {
      var card = document.querySelector('.preset-card[data-mode="' + cfg.mode + '"]');
      if (card && typeof selectPreset === "function") selectPreset(card); else set("mode-select", cfg.mode);
    }
    if (cfg.mode) set("mode-select", cfg.mode);
    set("bg-method", cfg.bg_method);
    set("warmup-frames", cfg.warmup_frames);
    set("object-filter-toggle", cfg.object_filter);
    if (typeof _onObjectFilterChange === "function") _onObjectFilterChange(chk("object-filter-toggle"));
    set("filter-confidence", cfg.filter_confidence);
    set("enhance-toggle", cfg.enhance);
    if (typeof updateEnhanceFields === "function") updateEnhanceFields();
    set("enhance-model", cfg.enhance_model);
    set("enhance-scale", cfg.enhance_scale);
    set("enhance-every-n", cfg.enhance_every_n);
    set("enhance-max-roi", cfg.enhance_max_roi_px);
    set("enhance-device", cfg.enhance_device);
    set("upscale-output-toggle", cfg.upscale_output);
    set("encrypt-toggle", cfg.encrypt);
    if (typeof updateEncryptFields === "function") updateEncryptFields();
    set("codec-select", cfg.codec);
    set("crf-input", cfg.crf === null || cfg.crf === undefined ? "" : cfg.crf);
    if (cfg.background_crf !== null && cfg.background_crf !== undefined) {
      window._svcsPreset = { key: cfg.preset || (window._svcsPreset && window._svcsPreset.key) || "",
                             background_crf: cfg.background_crf };
    }
    set("verbose-toggle", cfg.verbose);
    var useV = cfg.target_vmaf !== null && cfg.target_vmaf !== undefined;
    set("targetvmaf-toggle", useV);
    if (typeof onTargetVmafToggle === "function") onTargetVmafToggle();
    if (useV) set("targetvmaf-input", cfg.target_vmaf);
    set("maxbitrate-input", cfg.max_bitrate_kbps === null || cfg.max_bitrate_kbps === undefined ? "" : cfg.max_bitrate_kbps);
    set("gop-input", cfg.gop_seconds === null || cfg.gop_seconds === undefined ? "" : cfg.gop_seconds);
    set("denoise-select", cfg.denoise);
    set("roiqp-toggle", cfg.roi_qp);
    if (window.SegPlan) {
      if (cfg.segment_default === false && cfg.segment_seconds) SegPlan.setFixed(cfg.segment_seconds);
      else if (SegPlan.setDefault) SegPlan.setDefault();
    }
    var panel = el("advanced-panel");
    if (panel && typeof toggleAdvanced === "function" &&
        panel.classList.contains("open") !== !!cfg.advanced_open) toggleAdvanced();
    if (typeof syncModeChips === "function") syncModeChips();
  }

  function summary() {
    var c = collect();
    var seg = c.segment_default ? "whole video" : (c.segment_seconds + " s per file");
    return [
      ["Mode", c.mode],
      ["Segment length", seg],
      ["Advanced settings", c.advanced_open ? "open" : "closed"],
      ["Codec", c.codec + (c.crf !== null ? ", CRF " + c.crf : "")],
      ["Detection", c.bg_method + ", warmup " + c.warmup_frames + (c.object_filter ? ", smart filter on" : ", smart filter off")],
      ["AI sharpen", c.enhance ? c.enhance_model + " x" + c.enhance_scale + ", every " + c.enhance_every_n + " frames" : "off"],
      ["Encrypt output", c.encrypt ? "on (enter the password or key file below)" : "off"]
    ];
  }

  function note(text, isError) {
    var box = el("profile-note");
    if (!box) return;
    box.textContent = text;
    box.style.color = isError ? "var(--red)" : "var(--green)";
  }

  function showSummary(fileName) {
    var box = el("profile-summary");
    if (!box) return;
    box.innerHTML = "";
    var h = document.createElement("div");
    h.textContent = "Loaded " + fileName + ". The form now holds:";
    h.style.marginBottom = "0.25rem";
    box.appendChild(h);
    summary().forEach(function (r) {
      var d = document.createElement("div");
      d.textContent = r[0] + ": " + r[1];
      box.appendChild(d);
    });
    box.hidden = false;
  }

  async function onFile(evt) {
    var f = evt.target.files && evt.target.files[0];
    if (!f) return;
    var parsed;
    try { parsed = JSON.parse(await f.text()); }
    catch (e) { note("That file is not valid JSON.", true); return; }
    try {
      var resp = await fetch("/api/config/import", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(parsed)
      });
      var data = await resp.json();
      if (!resp.ok || data.error) { note("Could not load: " + (data.error || resp.statusText), true); return; }
      apply(data.config);
      note("Profile loaded.", false);
      showSummary(f.name);
    } catch (e) { note("Could not load: " + e.message, true); }
  }

  function load() {
    var inp = el("profile-file");
    if (!inp) return;
    inp.value = "";
    inp.click();
  }

  window.SvcsProfile = { collect: collect, apply: apply, summary: summary, save: save, load: load };
  window.addEventListener("DOMContentLoaded", function () {
    var inp = el("profile-file");
    if (inp) inp.addEventListener("change", onFile);
  });
})();
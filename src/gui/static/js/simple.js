/*
 * src/gui/static/js/simple.js
 *
 * Simple Home (default) and the Advanced switch in the header.
 *
 * Simple view shows four things: choose a video, pick a mode, tick what
 * matters ("goals"), Start; with progress and Recent Jobs (Play / Encrypt)
 * beside it. The real controls are MOVED between the simple slots and their
 * places in the full layout, so there is never a second copy of an id or a
 * handler. Each goal sets the same fields an expert would set by hand in
 * Advanced (CRF, segment length, AI model, detection, overlays, encryption).
 *
 * Author: Bloodawn (KheivenD), 2026-11-25 (simple Home).
 */
(function () {
  "use strict";

  var KEY = "svcs.advanced";
  var moved = [];   // {node, home: placeholder comment}

  function $(id) { return document.getElementById(id); }
  function readAdv() { try { return localStorage.getItem(KEY) === "1"; } catch (e) { return false; } }
  function saveAdv(v) { try { localStorage.setItem(KEY, v ? "1" : "0"); } catch (e) { /* private mode */ } }

  // What goes where in the simple view.
  function pieces() {
    var start = $("btn-start");
    var progressRow = $("progress-fill") && $("progress-fill").closest(".progress-row");
    return [
      ["upload", $("upload-zone")],
      ["upload", $("upload-status")],
      ["modes", document.querySelector("#tab-home .preset-grid")],
      ["start", $("start-hint")],
      ["start", start && start.closest(".btn-row")],
      ["result", $("last-result")],
      ["progress", $("status-message")],
      ["progress", progressRow],
      ["jobs", $("jobs-panel")],
      ["jobs", $("home-preview-wrap")],
    ];
  }

  function toSimple() {
    if (moved.length) return;
    pieces().forEach(function (pair) {
      var node = pair[1];
      var slot = document.querySelector('#simple-home [data-slot="' + pair[0] + '"]');
      if (!node || !slot) return;
      var mark = document.createComment("simple-home:" + (node.id || pair[0]));
      node.parentNode.insertBefore(mark, node);
      slot.appendChild(node);
      moved.push({ node: node, home: mark });
    });
  }

  function toAdvanced() {
    moved.forEach(function (m) {
      if (m.home.parentNode) {
        m.home.parentNode.insertBefore(m.node, m.home);
        m.home.parentNode.removeChild(m.home);
      }
    });
    moved = [];
  }

  function apply(adv) {
    document.body.classList.toggle("svcs-advanced", adv);
    document.body.classList.toggle("svcs-simple", !adv);
    if (adv) toAdvanced(); else toSimple();
    var b = $("adv-toggle");
    if (b) {
      b.setAttribute("aria-pressed", adv ? "true" : "false");
      b.textContent = adv ? "Simple" : "Advanced";
      b.title = adv ? "Back to the simple view" : "Show every setting";
    }
  }

  function toggle() {
    var adv = !document.body.classList.contains("svcs-advanced");
    saveAdv(adv);
    apply(adv);
  }

  // ── goals -> real settings ──────────────────────────────────────────────
  var CRF_SMALL = { mode0: 30, mode1: 28, mode2: 32, mode3: 42 };
  var CRF_BEST = { mode0: 18, mode1: 18, mode2: 20, mode3: 30 };

  function mode() { return ($("mode-select") && $("mode-select").value) || "mode0"; }

  function setChecked(id, on) {
    var el = $(id);
    if (!el || el.checked === on) return;
    el.checked = on;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  }

  function applyGoals() {
    var small = $("goal-small"), best = $("goal-quality");
    var crf = $("crf-input");
    if (crf) {
      crf.value = small && small.checked ? CRF_SMALL[mode()]
                : best && best.checked ? CRF_BEST[mode()] : "";
    }
    var ai = $("goal-ai") && $("goal-ai").checked;
    setChecked("enhance-toggle", ai);
    if (ai && $("enhance-model") && $("enhance-model").value === "bicubic") {
      $("enhance-model").value = "fsrcnn";   // fast real AI model, bundled
    }
    setChecked("object-filter-toggle", !!($("goal-search") && $("goal-search").checked));
    setChecked("overlay-toggle", !!($("goal-overlay") && $("goal-overlay").checked));

    var split = $("goal-split") && $("goal-split").checked;
    if (typeof _onSegLenUserChange === "function") _onSegLenUserChange(split ? 600 : 86400);

    var lock = $("goal-lock") && $("goal-lock").checked;
    if ($("sh-lock")) $("sh-lock").hidden = !lock;
    setChecked("encrypt-toggle", lock);
    if ($("encrypt-password") && $("sh-lock-pw")) {
      $("encrypt-password").value = lock ? $("sh-lock-pw").value : "";
    }
  }

  function wireGoals() {
    ["goal-small", "goal-quality"].forEach(function (id, i, all) {
      var el = $(id);
      if (el) el.addEventListener("change", function () {
        if (el.checked) { var other = $(all[1 - i]); if (other) other.checked = false; }
        applyGoals();
      });
    });
    ["goal-ai", "goal-search", "goal-overlay", "goal-split", "goal-lock"].forEach(function (id) {
      var el = $(id);
      if (el) el.addEventListener("change", applyGoals);
    });
    var pw = $("sh-lock-pw");
    if (pw) pw.addEventListener("input", applyGoals);
    // A mode card resets options to that mode's defaults; put the goals back.
    var grid = document.querySelector("#tab-home .preset-grid");
    if (grid) grid.addEventListener("click", function () {
      if (document.body.classList.contains("svcs-simple")) setTimeout(applyGoals, 0);
    });
  }

  // ── totals card (fills the side column with something useful) ────────────
  function fmtBytes(b) {
    if (!(b > 0)) return "0 MB";
    var u = ["B", "KB", "MB", "GB", "TB"], i = 0;
    while (b >= 1024 && i < u.length - 1) { b /= 1024; i++; }
    return (i >= 2 ? b.toFixed(1) : Math.round(b)) + " " + u[i];
  }
  async function loadTotals() {
    if (!$("sh-totals")) return;
    try {
      var s = await (await fetch("/api/savings")).json();
      var m = (s && s.measured) || {};
      var saved = (m.source_bytes || 0) - (m.output_bytes || 0);
      if (!(saved > 0) && m.saved_bytes) saved = m.saved_bytes;
      $("sh-tot-saved").textContent = saved > 0 ? fmtBytes(saved) + (m.ratio ? " (" + Number(m.ratio).toFixed(1) + "x smaller)" : "") : "-";
      $("sh-tot-files").textContent = m.files != null ? String(m.files) : "-";
    } catch (e) { /* keep dashes */ }
    try {
      var j = await (await fetch("/api/jobs/recent?limit=30")).json();
      var runs = (j.jobs || []).filter(function (x) { return x.counts && x.counts.realtime_x > 0; });
      if (runs.length) {
        var avg = runs.reduce(function (a, x) { return a + x.counts.realtime_x; }, 0) / runs.length;
        $("sh-tot-speed").textContent = avg.toFixed(1) + "x faster than playback";
      }
    } catch (e) { /* keep dashes */ }
  }

  function init() {
    wireGoals();
    apply(readAdv());
    loadTotals();
    // Refresh the totals whenever Recent Jobs reloads (a run just finished).
    if (typeof window.loadRecentJobs === "function") {
      var orig = window.loadRecentJobs;
      window.loadRecentJobs = function () { var r = orig.apply(this, arguments); loadTotals(); return r; };
    }
    if (!readAdv()) setTimeout(applyGoals, 0);
  }

  window.SvcsSimple = { toggle: toggle, apply: apply, applyGoals: applyGoals };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();

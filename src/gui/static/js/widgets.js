/*
 * Keyboard and screen reader support for two custom controls (redesign 2026-11, see docs/REDESIGN.md).
 *
 * 1. The four mode cards (.preset-card) are a radio group: one tab stop, arrow keys move the
 *    choice, Space or Enter picks it. State comes from the existing "selected" class, so the
 *    existing selectPreset() and syncModeChips() code keeps working and stays the source of truth.
 * 2. The "Advanced settings" toggle becomes a real button with aria-expanded, driven by the
 *    existing "open" class that toggleAdvanced() sets.
 */
(function () {
  "use strict";

  function cards() { return Array.prototype.slice.call(document.querySelectorAll(".preset-card")); }

  function syncCards() {
    var list = cards();
    var sel = list.filter(function (c) { return c.classList.contains("selected"); })[0] || list[0];
    list.forEach(function (c) {
      var on = c === sel;
      c.setAttribute("aria-checked", on ? "true" : "false");
      c.tabIndex = on ? 0 : -1;
      var locked = c.style.pointerEvents === "none";
      if (locked) c.setAttribute("aria-disabled", "true"); else c.removeAttribute("aria-disabled");
    });
  }

  function pick(card) {
    if (card.style.pointerEvents === "none") return; // locked while a job is running
    if (typeof window.selectPreset === "function") window.selectPreset(card); else card.click();
    syncCards();
    card.focus();
  }

  function initCards() {
    var list = cards();
    if (!list.length) return;
    var group = list[0].parentElement;
    group.setAttribute("role", "radiogroup");
    group.setAttribute("aria-label", "Compression mode");
    list.forEach(function (c) {
      c.setAttribute("role", "radio");
      new MutationObserver(syncCards).observe(c, { attributes: true, attributeFilter: ["class", "style"] });
      c.addEventListener("keydown", function (ev) {
        var i = list.indexOf(c), next = null;
        if (ev.key === "ArrowRight" || ev.key === "ArrowDown") next = list[(i + 1) % list.length];
        else if (ev.key === "ArrowLeft" || ev.key === "ArrowUp") next = list[(i - 1 + list.length) % list.length];
        else if (ev.key === " " || ev.key === "Enter") { ev.preventDefault(); pick(c); return; }
        if (next) { ev.preventDefault(); pick(next); }
      });
    });
    syncCards();
  }

  function initAdvanced() {
    var t = document.getElementById("advanced-toggle");
    var panel = document.getElementById("advanced-panel");
    if (!t || !panel) return;
    t.setAttribute("role", "button");
    t.tabIndex = 0;
    t.setAttribute("aria-controls", "advanced-panel");
    function sync() { t.setAttribute("aria-expanded", panel.classList.contains("open") ? "true" : "false"); }
    new MutationObserver(sync).observe(panel, { attributes: true, attributeFilter: ["class"] });
    t.addEventListener("keydown", function (ev) {
      if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); t.click(); }
    });
    sync();
  }

  // Result and status messages are plain text that other scripts rewrite. Mark them as polite
  // live regions so a screen reader hears "Saved" or an error without the user hunting for it.
  // The text itself carries the meaning, so colour is never the only signal.
  var MESSAGE_IDS = ["enc-encrypt-status", "enc-decrypt-status", "archive-status", "hls-sidebar-msg",
    "hls-status-msg", "keygen-result", "enc-keygen-result", "upload-status", "gdrive-status",
    "rtsp-server-msg", "rtsp-push-msg", "rtsp-dl-label"];
  function initMessages() {
    MESSAGE_IDS.forEach(function (id) {
      var el = document.getElementById(id);
      if (el && !el.hasAttribute("aria-live")) el.setAttribute("aria-live", "polite");
    });
  }
  function init() { initCards(); initAdvanced(); initMessages(); }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

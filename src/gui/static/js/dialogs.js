/*
 * Dialog accessibility for the dashboard overlays (redesign 2026-11, see docs/REDESIGN.md).
 * When one of the overlays below opens: the page behind it becomes inert, focus moves into
 * the dialog, and Escape closes it by clicking its own close button. When it closes, focus
 * returns to whatever opened it. The first-run setup dialog is excluded from Escape because
 * it asks for a required choice. The DONE modal has its own handling in ui.js.
 */
(function () {
  "use strict";
  var IDS = ["help-overlay", "decrypt-overlay", "setup-overlay", "library-browse-modal", "plate-modal"];
  var NO_ESCAPE = { "setup-overlay": true };
  var FOCUSABLE = "button, a[href], input:not([type=hidden]), select, textarea, [tabindex]:not([tabindex=\"-1\"])";
  var openers = {};
  function isOpen(el) {
    if (el.classList.contains("open")) return true;
    return getComputedStyle(el).display !== "none";
  }
  function page() { return document.querySelector(".page"); }
  function anyOpen() { return IDS.some(function (id) { var e = document.getElementById(id); return e && isOpen(e); }); }
  function onChange(el) {
    var open = isOpen(el), was = !!el.__a11yOpen;
    if (open === was) return;
    el.__a11yOpen = open;
    var pg = page();
    if (open) {
      openers[el.id] = document.activeElement;
      if (pg) pg.setAttribute("inert", "");
      var first = el.querySelector(FOCUSABLE);
      if (first) setTimeout(function () { first.focus(); }, 0);
    } else {
      if (pg && !anyOpen()) pg.removeAttribute("inert");
      var back = openers[el.id];
      if (back && document.contains(back) && typeof back.focus === "function") back.focus();
      delete openers[el.id];
    }
  }
  function init() {
    IDS.forEach(function (id) {
      var el = document.getElementById(id);
      if (!el) return;
      new MutationObserver(function () { onChange(el); })
        .observe(el, { attributes: true, attributeFilter: ["class", "style"] });
      onChange(el);
    });
    document.addEventListener("keydown", function (ev) {
      if (ev.key !== "Escape") return;
      for (var i = 0; i < IDS.length; i++) {
        var el = document.getElementById(IDS[i]);
        if (!el || !isOpen(el) || NO_ESCAPE[IDS[i]]) continue;
        var btns = el.querySelectorAll("button");
        for (var j = 0; j < btns.length; j++) {
          if (/^(close|cancel|done|ok|\u00d7|x)$/i.test((btns[j].textContent || "").trim()) || /^close/i.test(btns[j].getAttribute("aria-label") || "")) {
            ev.preventDefault(); btns[j].click(); return;
          }
        }
      }
    });
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init); else init();
})();

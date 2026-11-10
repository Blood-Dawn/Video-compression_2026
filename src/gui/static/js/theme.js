/*
 * Light and dark theme (redesign 2026-11, see docs/REDESIGN.md and docs/DESIGN_SYSTEM.md).
 * The dashboard stays dark by default. It follows the system setting when the user has not
 * chosen, and a header button lets them choose. The choice is remembered per browser.
 * Loaded in <head> so the theme is set before first paint and the page does not flash.
 */
(function () {
  "use strict";
  var KEY = "svcs-theme";
  var root = document.documentElement;
  var mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: light)") : null;

  function stored() {
    try { var v = window.localStorage.getItem(KEY); return v === "light" || v === "dark" ? v : null; }
    catch (e) { return null; }
  }
  function save(v) { try { window.localStorage.setItem(KEY, v); } catch (e) { /* private window */ } }
  function system() { return mq && mq.matches ? "light" : "dark"; }
  function current() { return root.getAttribute("data-theme") === "light" ? "light" : "dark"; }

  function apply(theme) {
    root.setAttribute("data-theme", theme);
    var btn = document.getElementById("theme-toggle");
    if (btn) {
      var next = theme === "light" ? "dark" : "light";
      btn.setAttribute("aria-label", "Switch to " + next + " theme");
      btn.title = "Switch to " + next + " theme";
      var g = btn.querySelector("[data-glyph]");
      if (g) g.textContent = theme === "light" ? "☾" : "☀";
    }
  }

  apply(stored() || system());

  if (mq && mq.addEventListener) {
    mq.addEventListener("change", function () { if (!stored()) apply(system()); });
  }

  function addButton() {
    if (document.getElementById("theme-toggle")) return;
    var host = document.querySelector(".header-right");
    if (!host) return;
    var btn = document.createElement("button");
    btn.type = "button";
    btn.id = "theme-toggle";
    btn.className = "theme-toggle";
    var g = document.createElement("span");
    g.setAttribute("data-glyph", "");
    g.setAttribute("aria-hidden", "true");
    btn.appendChild(g);
    btn.addEventListener("click", function () {
      var next = current() === "light" ? "dark" : "light";
      save(next);
      apply(next);
    });
    var pill = document.getElementById("status-pill");
    if (pill && pill.nextSibling) host.insertBefore(btn, pill.nextSibling); else host.appendChild(btn);
    apply(current());
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addButton); else addButton();
})();

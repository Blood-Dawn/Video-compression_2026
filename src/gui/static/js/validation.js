/*
 * Accessible validation state (redesign 2026-11, see docs/REDESIGN.md).
 * The browser's :user-invalid styling does not set aria-invalid on its own. This keeps the
 * two in step, and only after the user has interacted with the field, so a screen reader
 * does not announce an error the moment someone tabs into an empty required field.
 */
(function () {
  "use strict";
  var FIELDS = "input, textarea, select";
  function sync(ev) {
    var el = ev.target;
    if (!el || !el.matches || !el.matches(FIELDS)) return;
    var bad = false;
    try { bad = el.matches(":user-invalid"); } catch (e) { bad = false; }
    if (bad) el.setAttribute("aria-invalid", "true");
    else el.removeAttribute("aria-invalid");
  }
  document.addEventListener("blur", sync, true);
  document.addEventListener("focus", sync, true);
  document.addEventListener("input", function (ev) {
    var el = ev.target;
    if (el && el.getAttribute && el.getAttribute("aria-invalid") === "true") sync(ev);
  }, true);
})();

/*
 * src/gui/static/js/security_cam.js
 *
 * Security cam tab: a paired phone records short clips and uploads them, and
 * this computer compresses what arrives. The tab turns receiving on and off,
 * sets the clip length and compression mode, lists paired phones, and shows
 * recent clips with real source and output sizes (shared result algorithm).
 *
 * Talks to /api/security-cam only. It never touches compression code.
 *
 * Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, task 13.1).
 */
"use strict";

let _scTimer = null;
let _scState = null;

function _scEsc(s) {
  return String(s == null ? "" : s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function _scLen(seconds) {
  return window.SvcsNumbers ? window.SvcsNumbers.fmtLength(seconds) : seconds + " s";
}

function _scWhen(epoch) {
  if (!epoch) return "";
  const d = new Date(epoch * 1000);
  return d.toLocaleString([], { month: "numeric", day: "numeric", hour: "numeric", minute: "2-digit" });
}

async function _scPost(body) {
  const note = document.getElementById("sc-note");
  try {
    const resp = await fetch("/api/security-cam", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json();
    if (!resp.ok || !data.ok) {
      if (note) note.textContent = data.error || ("Could not save (" + resp.status + ")");
    } else if (note) {
      note.textContent = "";
    }
    if (data && data.segment_seconds) scRender(data);
  } catch (e) {
    if (note) note.textContent = "Could not reach the server.";
  }
}

function scRender(d) {
  _scState = d;
  const on = !!d.receiving;
  const badge = document.getElementById("sc-state-badge");
  badge.textContent = on ? "RECEIVING" : "OFF";
  badge.classList.toggle("is-on", on);
  badge.classList.toggle("is-off", !on);
  document.getElementById("sc-status-title").textContent = on ? "Security cam is receiving" : "Security cam is off";
  document.getElementById("sc-status-line").textContent = on
    ? "Watching " + d.watch_folder + ". New clips from your phone are compressed as they arrive."
    : "Not watching. Turn it on, then start Security cam on the phone.";
  const btn = document.getElementById("sc-toggle-btn");
  btn.textContent = on ? "Turn OFF" : "Turn ON";
  btn.classList.toggle("btn-primary", !on);
  btn.classList.toggle("btn-ghost", on);

  const lens = document.getElementById("sc-lengths");
  lens.innerHTML = (d.segment_choices || []).map(function (s) {
    const pressed = s === d.segment_seconds;
    return '<button type="button" class="btn btn-ghost seg-pbtn' + (pressed ? " on" : "") +
      '" aria-pressed="' + pressed + '" onclick="scSetLength(' + s + ')">' + _scEsc(_scLen(s)) + "</button>";
  }).join("");
  document.getElementById("sc-mode").value = d.mode;

  const phones = document.getElementById("sc-phones");
  phones.innerHTML = (d.phones || []).length
    ? d.phones.map(function (p) {
        return '<div class="x-row x-between"><span><b>' + _scEsc(p.label) + '</b></span><span class="x-hint x-mono">' +
          (p.last_seen ? "Last seen " + _scEsc(p.last_seen) : "Not used yet") + "</span></div>";
      }).join("")
    : '<div class="x-hint">No phone is paired. Pair one in Tools, then open Security cam in the app.</div>';

  const rows = document.getElementById("sc-clips");
  rows.innerHTML = (d.recent || []).length
    ? d.recent.map(function (c) {
        return "<tr><td>" + _scEsc(_scWhen(c.when)) + "</td><td>" + _scEsc(c.name) + "</td><td>" +
          (c.before_mb != null ? c.before_mb.toFixed(1) + " MB" : "") + "</td><td>" +
          (c.after_mb != null ? c.after_mb.toFixed(1) + " MB" : "") + "</td><td>" +
          _scEsc(c.verdict === "saved" ? c.saved_pct + "%" : "None") + "</td></tr>";
      }).join("")
    : '<tr><td colspan="5" class="x-hint">No clips yet. They appear here after the phone uploads one.</td></tr>';
}

async function scLoad() {
  try {
    const resp = await fetch("/api/security-cam");
    if (resp.ok) scRender(await resp.json());
  } catch (e) { /* keep the last view */ }
}

function scToggle() {
  const next = !(_scState && _scState.receiving);
  _scPost({ enabled: next, mode: document.getElementById("sc-mode").value });
}
function scSetLength(seconds) { _scPost({ segment_seconds: seconds }); }
function scSetMode(mode) { _scPost({ mode: mode }); }

function scOnTabShow() {
  scLoad();
  if (_scTimer) clearInterval(_scTimer);
  _scTimer = setInterval(scLoad, 5000);
}
function scOnTabHide() {
  if (_scTimer) { clearInterval(_scTimer); _scTimer = null; }
}

window.scToggle = scToggle;
window.scSetLength = scSetLength;
window.scSetMode = scSetMode;
window.scOnTabShow = scOnTabShow;
window.scOnTabHide = scOnTabHide;

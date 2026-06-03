/*
 * src/gui/static/js/tools.js
 *
 * TOOLS tab relocation (FIX 4).
 *
 * The Local RTSP Server (MediaMTX) and Live Stream (HLS) controls plus the HLS
 * player used to sit in the left sidebar / home pane. This moves their existing
 * DOM nodes into the new TOOLS topbar tab at load time, so every id and event
 * handler is preserved (no markup was duplicated and no API changed). If this
 * script does not run, the controls simply stay where they were (graceful
 * degradation). Author: Bloodawn (KheivenD), 2026-06-03 (FIX 4).
 */
"use strict";

function _relocateTools() {
  const body = document.getElementById("tab-tools-body");
  if (!body) return;
  const move = (el) => { if (el) body.appendChild(el); };

  // HLS live-stream controls (the .config-section wrapping #hls-input).
  const hlsInput = document.getElementById("hls-input");
  if (hlsInput && hlsInput.closest(".config-section")) {
    move(hlsInput.closest(".config-section"));
  }
  // Local RTSP server controls (the .config-section wrapping the details).
  const rtsp = document.getElementById("rtsp-server-details");
  if (rtsp && rtsp.closest(".config-section")) {
    move(rtsp.closest(".config-section"));
  }
  // HLS player panel (hidden until a stream is active).
  move(document.getElementById("hls-section"));
}
window.addEventListener("DOMContentLoaded", _relocateTools);

/*
 * src/gui/static/js/cameras.js
 *
 * SVCS dashboard - ONVIF camera discovery + RTSP auto-config (M-CAM TASK 1).
 *
 * "Discover cameras" runs a WS-Discovery scan via /api/cameras/discover and
 * lists the ONVIF cameras found in the source panel. Picking a camera fills the
 * input-source field with a suggested RTSP URL (optionally with credentials,
 * built server-side via /api/cameras/rtsp_url so special characters encode
 * correctly). If discovery finds nothing - common when Windows Firewall blocks
 * multicast - the UI says so and the operator just types the RTSP URL manually.
 *
 * All functions are global (classic script). Degrades to no-ops if the optional
 * DOM hooks aren't present. Author: Bloodawn (KheivenD), 2026-06-03 (M-CAM.1).
 */
"use strict";

function _camStatus(msg) {
  const el = document.getElementById("camera-discover-status");
  if (el) el.textContent = msg || "";
}

function _setInputSource(url) {
  const el = document.getElementById("input-source");
  if (!el) return;
  el.value = url;
  el.dispatchEvent(new Event("input", { bubbles: true }));
  if (typeof _onInputSourceChange === "function") _onInputSourceChange(url);
}

// Build an RTSP URL server-side (correct credential encoding) for a chosen
// candidate path, folding in the username/password from the form if given.
async function useCamera(host, path) {
  const user = (document.getElementById("camera-username") || {}).value || "";
  const pass = (document.getElementById("camera-password") || {}).value || "";
  if (!user && !pass) {
    // No creds: the candidate URL is already complete.
    _setInputSource(`rtsp://${host}:554${path}`);
    _camStatus(`Selected ${host}${path}`);
    return;
  }
  try {
    const res = await fetch("/api/cameras/rtsp_url", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ host, path, username: user, password: pass }),
    });
    const data = await res.json();
    if (data.rtsp_url) {
      _setInputSource(data.rtsp_url);
      _camStatus(`Selected ${host}${path}`);
    } else {
      _camStatus(data.error || "Could not build RTSP URL");
    }
  } catch (e) {
    _camStatus("Could not build RTSP URL");
  }
}
window.useCamera = useCamera;

function _renderCameras(cameras) {
  const list = document.getElementById("camera-list");
  if (!list) return;
  list.innerHTML = "";
  cameras.forEach((cam) => {
    const path = (cam.rtsp_candidates[0] || "rtsp://x:554/stream1").split(":554")[1] || "/stream1";
    const label = [cam.name, cam.hardware].filter(Boolean).join(" · ") || cam.address;
    const row = document.createElement("div");
    row.style.cssText = "display:flex;justify-content:space-between;align-items:center;gap:6px;padding:3px 0;";
    const text = document.createElement("span");
    text.style.cssText = "font-family:var(--mono);font-size:0.65rem;";
    text.textContent = `${label} (${cam.address})`;
    const btn = document.createElement("button");
    btn.className = "btn btn-ghost";
    btn.textContent = "Use";
    btn.onclick = () => useCamera(cam.address, path);
    row.appendChild(text);
    row.appendChild(btn);
    list.appendChild(row);
  });
}

// Honest help for cloud-locked cameras (Ring/Nest/Arlo) with no RTSP/export:
// point the operator at a local bridge. SVCS never touches the vendor cloud.
function showBridgeHelp() {
  const msg =
    "Ring / Nest / Arlo have no RTSP stream. Two honest options:\n\n"
    + "1. Export clips from the camera's app to a folder, then use the "
    + "export/watch-folder path.\n"
    + "2. Run a local bridge (Scrypted, Home Assistant, or Frigate) that "
    + "re-exposes the camera as a local RTSP URL, then paste that URL above.\n\n"
    + "SVCS never logs into or scrapes a vendor cloud - the bridge does, on "
    + "your hardware. See docs/camera-ingestion.md for setup.";
  if (typeof pushNotif === "function") {
    pushNotif("Cloud-locked camera?", msg, "info", null, 12000);
  } else {
    _camStatus(msg);
  }
}
window.showBridgeHelp = showBridgeHelp;

async function discoverCameras() {
  _camStatus("Scanning the local network for ONVIF cameras…");
  const list = document.getElementById("camera-list");
  if (list) list.innerHTML = "";
  try {
    const res = await fetch("/api/cameras/discover");
    const data = await res.json();
    const cams = data.cameras || [];
    if (!cams.length) {
      _camStatus("No ONVIF cameras found. Enter the RTSP URL manually below "
                 + "(firewalls often block discovery).");
      return;
    }
    _renderCameras(cams);
    _camStatus(`Found ${cams.length} camera(s). Pick one to use its RTSP stream.`);
  } catch (e) {
    _camStatus("Discovery failed. Enter the RTSP URL manually below.");
  }
}
window.discoverCameras = discoverCameras;

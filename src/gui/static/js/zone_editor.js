/*
 * src/gui/static/js/zone_editor.js
 *
 * Zone editor canvas draft (Week 3 TASK 3.8).
 *
 * Draws exclude regions, crossing lines, and loiter zones for one camera on
 * a canvas over that camera's cached still (GET /api/zones/frame, TASK 3.7),
 * and reads/writes the existing GET/POST /api/zones contract (R5 TASKS
 * 5.6/5.7) unchanged. All geometry is normalized 0..1 client-side before it
 * is sent, matching zones_config.py exactly, so nothing server-side needed
 * to change for this panel to work.
 *
 * This is a draft: one camera at a time, click-drag to draw, no drag-to-move
 * or resize of an existing shape yet (that is Week 4 TASK 4.7 in the plan).
 *
 * Author: Bloodawn (KheivenD), Week 3 (3.8).
 */
"use strict";

const ZONE_COLORS = { exclude: "#e05a5a", line: "#e0c93a", zone: "#3ac9d9" };

let _zoneState = { exclude: [], lines: [], zones: [] };
let _zoneImage = null;      // the loaded background <img>, or null
let _zoneDrag = null;       // {x0,y0,x1,y1} in canvas pixels while dragging
let _zoneHistory = [];      // [{kind:'exclude'|'line'|'zone'}] in add order, for Undo

function _zoneSay(text, kind) {
  const el = document.getElementById("zone-editor-status");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = kind === "error" ? "var(--red)"
                 : kind === "ok" ? "var(--green)" : "var(--text-dim)";
}

function _zoneCameraId() {
  return (document.getElementById("zone-camera-id")?.value || "").trim();
}

function _zoneCanvas() {
  return document.getElementById("zone-canvas");
}

function _zoneToNorm(px, canvas) {
  // px = [x1,y1,x2,y2] in canvas pixel space -> 0..1 of canvas size, matching
  // zones_config.py's "normalized so a config survives resolution changes".
  return [px[0] / canvas.width, px[1] / canvas.height,
          px[2] / canvas.width, px[3] / canvas.height];
}

function _zoneToPx(norm, canvas) {
  return [norm[0] * canvas.width, norm[1] * canvas.height,
          norm[2] * canvas.width, norm[3] * canvas.height];
}

function _zoneRedraw() {
  const canvas = _zoneCanvas();
  if (!canvas) return;
  const ctx = canvas.getContext("2d");
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  if (_zoneImage) {
    ctx.drawImage(_zoneImage, 0, 0, canvas.width, canvas.height);
  } else {
    ctx.fillStyle = "#000";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }

  ctx.lineWidth = 2;
  for (const rect of _zoneState.exclude) {
    const [x1, y1, x2, y2] = _zoneToPx(rect, canvas);
    ctx.strokeStyle = ZONE_COLORS.exclude;
    ctx.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
  }
  for (const ln of _zoneState.lines) {
    const [x1, y1, x2, y2] = _zoneToPx(ln.line, canvas);
    ctx.strokeStyle = ZONE_COLORS.line;
    ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
    ctx.fillStyle = ZONE_COLORS.line;
    ctx.font = "11px monospace";
    ctx.fillText(ln.id, (x1 + x2) / 2 + 4, (y1 + y2) / 2 - 4);
  }
  for (const zn of _zoneState.zones) {
    const [x1, y1, x2, y2] = _zoneToPx(zn.rect, canvas);
    ctx.strokeStyle = ZONE_COLORS.zone;
    ctx.strokeRect(Math.min(x1, x2), Math.min(y1, y2), Math.abs(x2 - x1), Math.abs(y2 - y1));
    ctx.fillStyle = ZONE_COLORS.zone;
    ctx.font = "11px monospace";
    ctx.fillText(zn.id, Math.min(x1, x2) + 3, Math.min(y1, y2) + 12);
  }

  if (_zoneDrag) {
    const mode = document.getElementById("zone-draw-mode")?.value || "exclude";
    ctx.strokeStyle = ZONE_COLORS[mode] || "#fff";
    ctx.setLineDash([4, 3]);
    if (mode === "line") {
      ctx.beginPath(); ctx.moveTo(_zoneDrag.x0, _zoneDrag.y0);
      ctx.lineTo(_zoneDrag.x1, _zoneDrag.y1); ctx.stroke();
    } else {
      ctx.strokeRect(Math.min(_zoneDrag.x0, _zoneDrag.x1), Math.min(_zoneDrag.y0, _zoneDrag.y1),
                      Math.abs(_zoneDrag.x1 - _zoneDrag.x0), Math.abs(_zoneDrag.y1 - _zoneDrag.y0));
    }
    ctx.setLineDash([]);
  }
}

function _zoneCanvasPoint(evt, canvas) {
  const r = canvas.getBoundingClientRect();
  const scaleX = canvas.width / r.width, scaleY = canvas.height / r.height;
  return { x: (evt.clientX - r.left) * scaleX, y: (evt.clientY - r.top) * scaleY };
}

function _zoneOnDown(evt) {
  const canvas = _zoneCanvas();
  const p = _zoneCanvasPoint(evt, canvas);
  _zoneDrag = { x0: p.x, y0: p.y, x1: p.x, y1: p.y };
}

function _zoneOnMove(evt) {
  if (!_zoneDrag) return;
  const canvas = _zoneCanvas();
  const p = _zoneCanvasPoint(evt, canvas);
  _zoneDrag.x1 = p.x; _zoneDrag.y1 = p.y;
  _zoneRedraw();
}

function _zoneOnUp() {
  if (!_zoneDrag) return;
  const canvas = _zoneCanvas();
  const mode = document.getElementById("zone-draw-mode")?.value || "exclude";
  const moved = Math.hypot(_zoneDrag.x1 - _zoneDrag.x0, _zoneDrag.y1 - _zoneDrag.y0);
  const drag = _zoneDrag;
  _zoneDrag = null;
  if (moved < 4) { _zoneRedraw(); return; }   // a click, not a drag: ignore

  const norm = _zoneToNorm([drag.x0, drag.y0, drag.x1, drag.y1], canvas);
  if (mode === "exclude") {
    _zoneState.exclude.push(norm);
    _zoneHistory.push({ kind: "exclude" });
  } else {
    const id = (document.getElementById("zone-shape-id")?.value || "").trim();
    if (!id) {
      _zoneSay("Type an id for this " + (mode === "line" ? "line" : "zone") + " first.", "error");
      _zoneRedraw();
      return;
    }
    if (mode === "line") {
      _zoneState.lines.push({ id, line: norm });
      _zoneHistory.push({ kind: "line" });
    } else {
      _zoneState.zones.push({ id, rect: norm });
      _zoneHistory.push({ kind: "zone" });
    }
  }
  _zoneRedraw();
}

function zoneEditorUndo() {
  const last = _zoneHistory.pop();
  if (!last) return;
  if (last.kind === "exclude") _zoneState.exclude.pop();
  else if (last.kind === "line") _zoneState.lines.pop();
  else if (last.kind === "zone") _zoneState.zones.pop();
  _zoneRedraw();
}
window.zoneEditorUndo = zoneEditorUndo;

function zoneEditorClear() {
  _zoneState = { exclude: [], lines: [], zones: [] };
  _zoneHistory = [];
  _zoneRedraw();
  _zoneSay("Cleared. Nothing is saved until you click Save.");
}
window.zoneEditorClear = zoneEditorClear;

async function zoneEditorLoad() {
  const cam = _zoneCameraId();
  if (!cam) { _zoneSay("Enter a camera id first.", "error"); return; }
  _zoneSay("Loading...");
  try {
    const cfgData = await (await fetch("/api/zones?camera_id=" + encodeURIComponent(cam))).json();
    if (cfgData && cfgData.config) {
      const c = cfgData.config;
      _zoneState = { exclude: c.exclude || [], lines: c.lines || [], zones: c.zones || [] };
      _zoneHistory = [];
      const loiter = document.getElementById("zone-loiter-s");
      const classes = document.getElementById("zone-class-filter");
      if (loiter) loiter.value = c.loiter_s ?? 30;
      if (classes) classes.value = (c.class_filter || []).join(", ");
    }
  } catch (e) {
    _zoneSay("Could not load the saved config: " + e, "error");
  }

  const canvas = _zoneCanvas();
  const img = new Image();
  img.onload = () => { _zoneImage = img; _zoneRedraw(); _zoneSay("Loaded. Draw over the image, then Save.", "ok"); };
  img.onerror = () => { _zoneImage = null; _zoneRedraw(); _zoneSay("Loaded config; no camera still available yet.", "ok"); };
  img.src = "/api/zones/frame?camera_id=" + encodeURIComponent(cam) + "&_=" + Date.now();

  if (canvas && !canvas.dataset.wired) {
    canvas.addEventListener("mousedown", _zoneOnDown);
    canvas.addEventListener("mousemove", _zoneOnMove);
    window.addEventListener("mouseup", _zoneOnUp);
    canvas.dataset.wired = "1";
  }
  _zoneRedraw();
}
window.zoneEditorLoad = zoneEditorLoad;

async function zoneEditorSave() {
  const cam = _zoneCameraId();
  if (!cam) { _zoneSay("Enter a camera id first.", "error"); return; }
  const loiter = Number(document.getElementById("zone-loiter-s")?.value || 30);
  const classFilter = (document.getElementById("zone-class-filter")?.value || "")
    .split(",").map((s) => s.trim()).filter(Boolean);
  _zoneSay("Saving...");
  try {
    const res = await fetch("/api/zones", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        camera_id: cam, exclude: _zoneState.exclude, lines: _zoneState.lines,
        zones: _zoneState.zones, loiter_s: loiter, class_filter: classFilter,
      }),
    });
    const data = await res.json();
    if (!res.ok || data.error) { _zoneSay(data.error || "Could not save.", "error"); return; }
    _zoneSay("Saved. Applies to " + cam + "'s next run.", "ok");
  } catch (e) {
    _zoneSay(String(e), "error");
  }
}
window.zoneEditorSave = zoneEditorSave;

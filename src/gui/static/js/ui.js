/*
 * src/gui/static/js/ui.js
 *
 * SVCS dashboard - ui module. Carved verbatim from the former single
 * inline <script> in index.html (TASK 1.5). Loaded as a classic script in
 * original execution order, so behavior is identical; all functions stay
 * global (reachable from inline on* handlers and the other modules).
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - JS split).
 */
function setPipelineRunning(running) {
  // Reset segment counter so the first new segment fires a notification
  if (!running) _lastSegmentCount = 0;

  const pill = document.getElementById('status-pill');
  const text = document.getElementById('status-text');
  const btnStart = document.getElementById('btn-start');
  const btnStop  = document.getElementById('btn-stop');

  pill.className = 'pill ' + (running ? 'running' : 'offline');
  text.textContent = running ? 'RUNNING' : 'OFFLINE';
  btnStart.disabled = running;
  btnStop.disabled  = !running;

  // Disable config fields while running
  const fields = document.querySelectorAll(
    '#input-source, #camera-id, #output-dir, #mode-select, #bg-method, ' +
    '#segment-seconds, #warmup-frames, #enhance-toggle, #enhance-model, ' +
    '#enhance-scale, #enhance-every-n, #enhance-max-roi, #enhance-device, #encrypt-toggle, #encrypt-password, #encrypt-keyfile, ' +
    '#sensitivity-slider, #segment-seconds-slider'
  );
  fields.forEach(f => { f.disabled = running; });
  // Grey out preset cards while running
  document.querySelectorAll('.preset-card').forEach(c => {
    c.style.pointerEvents = running ? 'none' : '';
    c.style.opacity = running ? '0.6' : '';
  });
}

function showError(msg) {
  const el = document.getElementById('error-banner');
  el.textContent = '[!] ' + msg;
  el.classList.add('show');
}
function clearError() {
  document.getElementById('error-banner').classList.remove('show');
}

// ── Formatting helpers ────────────────────────────────────────
function fmtNum(n) {
  return n >= 1_000_000 ? (n/1e6).toFixed(1)+'M'
       : n >= 1_000     ? (n/1e3).toFixed(1)+'K'
       : String(n);
}
function fmtDuration(s) {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  if (h > 0) return `${h}h ${m}m ${sec}s`;
  if (m > 0) return `${m}m ${sec}s`;
  return `${sec}s`;
}
function formatTimestamp(ts) {
  // "20260407T143022Z" → "2026-04-07 14:30:22"
  if (!ts) return ' - ';
  try {
    const y = ts.slice(0,4), mo = ts.slice(4,6), d = ts.slice(6,8);
    const h = ts.slice(9,11), mi = ts.slice(11,13), s = ts.slice(13,15);
    return `${y}-${mo}-${d} ${h}:${mi}:${s}`;
  } catch { return ts; }
}
function escHtml(s) {
  return String(s)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

/**
 * Map a color label coming from the dominant_color DB column to a CSS
 * color so we can render a small swatch next to the label in the
 * Metrics + Search tables. Falls back to the literal label if it's
 * already a valid CSS color, or to grey for unknowns.
 *
 * Author: Bloodawn (KheivenD), 2026-05-03 (UI cleanup pass).
 */
function _colorSwatch(label) {
  const l = String(label || '').toLowerCase();
  const map = {
    red:    '#e76f51', orange:'#f4a261', yellow:'#f1c40f',
    green:  '#50c878', blue:  '#4e9af1', purple:'#9b59b6',
    white:  '#f5f7fa', black: '#222222', gray:  '#888888',
    grey:   '#888888', silver:'#b0b0b0', brown: '#8b5a2b',
  };
  return map[l] || '#888888';
}

/**
 * Pick a friendly display name for a segment row's "Cam" column.
 *
 * Old segments were all written with the default camera_id "cam_00",
 * which makes the metrics table impossible to scan when the user
 * has 30+ recordings from different source files. This helper
 * derives a meaningful label from the segment's own file path when
 * camera_id is unhelpful, falling back to camera_id as a last resort.
 *
 * Strategy: `<camera_id>_segment_NNN.mp4` → `<camera_id>` is what we
 * already have. So the segment basename doesn't add new info there.
 * BUT - we look at the parent directory name first, because demo runs
 * write to `<output_root>/demo_comp_<source-filename>/...`, and the
 * pipeline's output dir often encodes the source clip too. That gives
 * us the source filename even for cam_00 recordings.
 *
 * Author: Bloodawn (KheivenD), 2026-05-03 (UI fix pass).
 */
/**
 * Derive the SVCS mode used to encode a segment from its file path.
 * The pipeline writes mode-specific subfolders ("mode0/", "mode1/", ...)
 * under each demo run, so we can reverse-engineer which mode was used
 * without adding a column to the segments DB schema.
 *
 * Returns one of "Mode 0..3" or " - " if the path doesn't reveal it.
 *
 * Author: Bloodawn (KheivenD), 2026-05-03 (mode column).
 */
function _segMode(s) {
  const fp = String(s.file_path || '').toLowerCase();

  // 1. Server-provided modes_combined wins (set on demo splitscreen rows
  //    where multiple modes are stitched into one video).
  if (Array.isArray(s.modes_combined) && s.modes_combined.length > 1) {
    return 'Split (' + s.modes_combined.map(m => 'M' + m).join('+') + ')';
  }

  // 2. Heuristic: split-screen / composite videos. The demo runner
  //    writes the stitched output into demo_comp<suffix>/ alongside a
  //    "splitscreen" or "compare" filename. Treat these as multi-mode.
  if (fp.includes('demo_comp') || fp.includes('splitscreen') ||
      /[\\/](compare|composite|stitched)[\\/.]/.test(fp)) {
    // Pull every modeN that appears anywhere in the path
    const modes = new Set();
    let m; const re = /mode([0-3])/g;
    while ((m = re.exec(fp)) !== null) modes.add(m[1]);
    if (modes.size >= 2) {
      return 'Split (' + [...modes].sort().map(d => 'M' + d).join('+') + ')';
    }
    return 'Split-screen';
  }

  // 3. Direct subfolder marker - most reliable signal for single-mode files
  const m = fp.match(/[\\/]mode([0-3])\b/);
  if (m) return 'Mode ' + m[1];

  // 4. Fallback: filename suffix (some pipelines write segment_modeN.mp4)
  const m2 = fp.match(/_mode([0-3])(?:[._]|$)/);
  if (m2) return 'Mode ' + m2[1];

  return ' - ';
}

function _segDisplayName(s) {
  const fp = String(s.file_path || '');
  if (!fp) return s.camera_id || ' - ';
  // Split on either Windows or POSIX separator
  const parts = fp.split(/[\\/]/);
  // Walk up looking for a parent dir that smells like a source clip.
  // Skip generic dirs ("outputs", "data", "segments", ...).
  const skip = new Set([
    '', 'outputs', 'output', 'data', 'segments', 'mode0', 'mode1',
    'mode2', 'mode3', 'standard', 'compressed', 'demo', 'cam_00',
  ]);
  for (let i = parts.length - 2; i >= 0; i--) {
    const p = parts[i];
    if (!p || skip.has(p.toLowerCase())) continue;
    // Strip a leading "demo_comp_" prefix that the demo runner adds
    let name = p.replace(/^demo_comp_/i, '').replace(/^run_/i, '');
    // Strip a trailing "_modeN" or "_NNN" suffix
    name = name.replace(/_mode\d.*$/i, '').replace(/_\d{3,}$/i, '');
    if (name && name !== 'cam_00') return name;
  }
  // Last resort: the segment basename without its own extension/segment idx
  const base = parts[parts.length - 1] || '';
  const stem = base.replace(/\.[^.]+$/, '').replace(/_segment_\d+$/i, '');
  return stem || (s.camera_id || ' - ');
}

/**
 * Escape a string so it can be safely embedded inside a JS single-quoted
 * string literal that is itself already inside an HTML attribute. Critical
 * for Windows paths: `escHtml` doesn't touch backslashes, but a path like
 * `C:\Users\kheiven\OneDrive` injected into `onclick="fn('...')"` gets
 * interpreted by the JS parser as containing escape sequences (\U, \D, etc.)
 * which then get silently eaten. Use this helper for any file path or URL
 * passed via inline onclick.
 *
 * Author: Bloodawn (KheivenD), 2026-05-03 (encrypt path-strip bug fix).
 */
function jsAttr(s) {
  return String(s)
    .replace(/\\/g, '\\\\')   // escape backslashes FIRST
    .replace(/'/g,  "\\'")    // then escape single quotes
    .replace(/&/g,  '&amp;')  // HTML-attribute-safe
    .replace(/</g,  '&lt;')
    .replace(/>/g,  '&gt;')
    .replace(/"/g,  '&quot;');
}

// ── HLS live streaming (task 4.1) ─────────────────────────────
let _hlsInstance = null;
let _hlsStatusTimer = null;


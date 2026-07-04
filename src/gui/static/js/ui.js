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

// ── Shared modal + job summaries (R4 Phase 1, docs/RESEARCH-UIUX.md) ─────────
// NN/g: after a long wait the user has disengaged, so completion feedback must
// be an explicit user-dismissed dialog with start/stop/elapsed and what
// happened - not an auto-fading toast. svcsModalShow drives the one static
// dialog in index.html; every long-job summary goes through it.

function fmtBytes(n) {
  n = Number(n) || 0;
  if (n >= 1024 * 1024 * 1024) return (n / (1024 ** 3)).toFixed(2) + ' GB';
  if (n >= 1024 * 1024) return (n / (1024 ** 2)).toFixed(1) + ' MB';
  if (n >= 1024) return (n / 1024).toFixed(1) + ' KB';
  return n + ' B';
}

function fmtClock(epoch) {
  if (!epoch) return ' - ';
  try { return new Date(epoch * 1000).toLocaleTimeString(); } catch { return ' - '; }
}

let _modalPrevFocus = null;

function svcsModalShow(title, bodyHtml) {
  const overlay = document.getElementById('svcs-modal-overlay');
  if (!overlay) return;
  document.getElementById('svcs-modal-title').textContent = title;
  document.getElementById('svcs-modal-body').innerHTML = bodyHtml;
  _modalPrevFocus = document.activeElement;
  overlay.classList.add('open');
  const closeBtn = document.getElementById('svcs-modal-close');
  if (closeBtn) closeBtn.focus();
}

function svcsModalHide() {
  const overlay = document.getElementById('svcs-modal-overlay');
  if (overlay) overlay.classList.remove('open');
  if (_modalPrevFocus && typeof _modalPrevFocus.focus === 'function') {
    try { _modalPrevFocus.focus(); } catch (e) {}
  }
  _modalPrevFocus = null;
}
window.svcsModalHide = svcsModalHide;

// Dialog a11y: Escape dismisses, and Tab is trapped inside the dialog while
// it is open (aria-modal promises the background is inert - without the trap,
// Tab reaches visually-hidden controls behind the overlay).
document.addEventListener('keydown', (ev) => {
  const overlay = document.getElementById('svcs-modal-overlay');
  if (!overlay || !overlay.classList.contains('open')) return;
  if (ev.key === 'Escape') { svcsModalHide(); return; }
  if (ev.key !== 'Tab') return;
  const focusables = overlay.querySelectorAll(
    'button, a[href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
  if (!focusables.length) return;
  const first = focusables[0], last = focusables[focusables.length - 1];
  if (!overlay.contains(document.activeElement)) {
    ev.preventDefault(); first.focus();
  } else if (ev.shiftKey && document.activeElement === first) {
    ev.preventDefault(); last.focus();
  } else if (!ev.shiftKey && document.activeElement === last) {
    ev.preventDefault(); first.focus();
  }
});

function _jobSumRow(label, value) {
  return '<div class="job-sum-row"><span>' + escHtml(label) + '</span><span>' +
         escHtml(value) + '</span></div>';
}

/** Build and show the completion summary for one job-history entry. */
function showJobSummaryModal(job) {
  if (!job) return;
  const c = job.counts || {};
  const rows = [];
  rows.push(_jobSumRow('Source', job.label || ' - '));
  rows.push(_jobSumRow('Started', fmtClock(job.started_at)));
  rows.push(_jobSumRow('Finished', fmtClock(job.ended_at)));
  if (job.elapsed_s != null) rows.push(_jobSumRow('Elapsed', fmtDuration(job.elapsed_s)));
  if (job.kind === 'autocompress') {
    rows.push(_jobSumRow('Files compressed', String(c.compressed ?? 0) + ' of ' + String(c.files ?? 0)));
    if (c.skipped) rows.push(_jobSumRow('Skipped / failed', String(c.skipped)));
    if (job.bytes_in > 0 && job.bytes_out > 0) {
      rows.push(_jobSumRow('Input size', fmtBytes(job.bytes_in)));
      rows.push(_jobSumRow('Output size', fmtBytes(job.bytes_out)));
      rows.push(_jobSumRow('Space saved', fmtBytes(Math.max(0, job.bytes_in - job.bytes_out))));
    }
  } else {
    rows.push(_jobSumRow('Frames processed', fmtNum(c.frames || 0)));
    rows.push(_jobSumRow('Segments written', String(c.segments ?? 0)));
    if (c.mode) rows.push(_jobSumRow('Mode', String(c.mode)));
  }
  if (job.error) rows.push(_jobSumRow('Error', String(job.error)));
  const title = job.status === 'error' ? 'JOB FAILED'
              : job.status === 'stopped' ? 'JOB STOPPED'
              : 'JOB COMPLETE';
  svcsModalShow(title, rows.join(''));
}

/** Fetch the newest job and show its summary if it matches kind + is fresh. */
async function maybeShowLatestJobSummary(kind) {
  try {
    const data = await (await fetch('/api/jobs/recent?limit=1')).json();
    const job = (data.jobs || [])[0];
    // Only surface a summary for a job of the expected kind that ended in the
    // last two minutes - never replay an old entry on page load.
    if (job && job.kind === kind && job.ended_at &&
        (Date.now() / 1000 - job.ended_at) < 120) {
      showJobSummaryModal(job);
    }
  } catch (e) { /* history unavailable - skip the summary quietly */ }
}

// ── Recent jobs panel (HOME) ─────────────────────────────────────────────────
async function loadRecentJobs() {
  const list = document.getElementById('jobs-list');
  if (!list) return;
  try {
    const data = await (await fetch('/api/jobs/recent?limit=8')).json();
    const jobs = data.jobs || [];
    if (!jobs.length) {
      list.innerHTML = '<div class="jobs-empty">No jobs yet. Finished compressions (manual runs and auto-compress batches) will be listed here.</div>';
      return;
    }
    list.innerHTML = jobs.map(j => {
      const c = j.counts || {};
      const what = j.kind === 'autocompress' ? (c.compressed ?? 0) + ' file(s)'
                 : j.kind === 'retention'    ? (c.deleted ?? 0) + ' purged'
                 : (c.segments ?? 0) + ' segment(s)';
      // For retention, bytes_in is the space freed (no bytes_out).
      const saved = j.kind === 'retention'
        ? (j.bytes_in > 0 ? ', freed ' + fmtBytes(j.bytes_in) : '')
        : ((j.bytes_in > 0 && j.bytes_out > 0)
            ? ', saved ' + fmtBytes(Math.max(0, j.bytes_in - j.bytes_out)) : '');
      const status = String(j.status || 'completed');
      return '<div class="job-row">' +
        '<span class="job-status ' + escHtml(status) + '">' + escHtml(status.toUpperCase()) + '</span>' +
        '<span class="job-label" title="' + escHtml(j.label || '') + '">' + escHtml(j.label || ' - ') + '</span>' +
        '<span class="job-meta">' + escHtml(what + saved +
          (j.elapsed_s != null ? ', ' + fmtDuration(j.elapsed_s) : '')) + '</span>' +
        '</div>';
    }).join('');
  } catch (e) { /* panel keeps its previous contents */ }
}

// ── HLS live streaming (task 4.1) ─────────────────────────────
let _hlsInstance = null;
let _hlsStatusTimer = null;


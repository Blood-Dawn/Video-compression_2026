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
  pill.title = running
    ? 'Compression pipeline is running.'
    : 'Pipeline is idle: nothing is compressing right now. The web server itself is up. Press Start to begin.';
  // Start stays locked until Setup is complete, even when the pipeline is idle.
  const setupDone = !!(window._svcsSetup && window._svcsSetup.complete);
  btnStart.disabled = running || !setupDone;
  btnStart.style.opacity = btnStart.disabled ? "0.5" : "";
  btnStart.style.pointerEvents = btnStart.disabled ? "none" : "";
  btnStop.disabled  = !running;

  // Disable config fields while running
  const fields = document.querySelectorAll(
    '#input-source, #camera-id, #output-dir, #mode-select, #bg-method, ' +
    '#segment-seconds, #warmup-frames, #detector-size, #enhance-toggle, #enhance-model, ' +
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
 * Metrics + Search tables. Unknown labels get grey.
 *
 * Author: Bloodawn (KheivenD), 2026-05-03 (UI cleanup pass).
 */
const _SWATCH_HEX = {
  red:    '#e76f51', orange:'#f4a261', yellow:'#f1c40f',
  green:  '#50c878', blue:  '#4e9af1', purple:'#9b59b6',
  white:  '#f5f7fa', black: '#222222', gray:  '#888888',
  grey:   '#888888', silver:'#b0b0b0', brown: '#8b5a2b',
};

function _colorSwatch(label) {
  return _SWATCH_HEX[String(label || '').toLowerCase()] || '#888888';
}

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

/** Text color for a _segMode() label, shared by the metrics and search tables. */
function _segModeColor(mode) {
  return mode === ' - ' ? 'var(--text-dim)'
    : mode.startsWith('Split') ? 'var(--purple)'
    : mode === 'Mode 0' ? 'var(--text)'
    : mode === 'Mode 1' ? 'var(--teal)'
    : mode === 'Mode 2' ? 'var(--yellow)'
    : 'var(--green)';
}

// Generic folder names that say nothing about which source a segment came from.
const _GENERIC_SEG_DIRS = new Set([
  '', 'outputs', 'output', 'data', 'segments', 'mode0', 'mode1',
  'mode2', 'mode3', 'standard', 'compressed', 'demo', 'cam_00',
]);

/**
 * Pick a friendly display name for a segment row's "Cam" column.
 *
 * Old segments were all written with the default camera_id "cam_00",
 * which makes the metrics table impossible to scan when the user
 * has 30+ recordings from different source files. This helper
 * derives a meaningful label from the segment's own file path when
 * camera_id is unhelpful, falling back to camera_id as a last resort.
 *
 * The segment basename (`<camera_id>_segment_NNN.mp4`) adds nothing, so the
 * parent directories are checked first: demo runs write to
 * `<output_root>/demo_comp_<source-filename>/...`, and the pipeline's output
 * dir often encodes the source clip too.
 *
 * Author: Bloodawn (KheivenD), 2026-05-03 (UI fix pass).
 */
function _segDisplayName(s) {
  const fp = String(s.file_path || '');
  if (!fp) return s.camera_id || ' - ';
  const parts = fp.split(/[\\/]/);
  // Walk up looking for a parent dir that smells like a source clip.
  for (let i = parts.length - 2; i >= 0; i--) {
    const p = parts[i];
    if (!p || _GENERIC_SEG_DIRS.has(p.toLowerCase())) continue;
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

/** Label for a "Camera" cell: the camera_id, unless it is the legacy cam_00 default. */
function _segCamLabel(s) {
  return (!s.camera_id || s.camera_id === 'cam_00') ? _segDisplayName(s) : s.camera_id;
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
    if (c.note) rows.push(_jobSumRow('Why no output', String(c.note)));
    if (c.larger_note) rows.push(_jobSumRow('Heads up', String(c.larger_note)));
  }
  if (job.error) rows.push(_jobSumRow('Error', String(job.error)));
  const title = job.status === 'error' ? 'JOB FAILED'
              : job.status === 'stopped' ? 'JOB STOPPED'
              : (c.note ? 'JOB COMPLETE, NO OUTPUT' : 'JOB COMPLETE');
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

// ── Compression speed (video length against compression time) ─────────────
// Under a minute, keep one decimal so a 0.4 s run does not read as "0s".
function _fmtSecs(s) {
  return s < 60 ? (Math.round(s * 10) / 10).toFixed(1) + 's' : fmtDuration(s);
}

function _speedText(c) {
  if (!c || !c.realtime_x || !c.video_seconds || !c.wall_seconds) return '';
  return ', ' + _fmtSecs(c.video_seconds) + ' of video in ' + _fmtSecs(c.wall_seconds) +
    ' (' + c.realtime_x.toFixed(1) + 'x playback)';
}

async function loadSpeedPanel() {
  const body = document.getElementById('mspeed-rows');
  if (!body) return;
  const summary = document.getElementById('mspeed-summary');
  const wrap = document.getElementById('mspeed-wrap');
  const note = document.getElementById('mspeed-note');
  try {
    const data = await (await fetch('/api/jobs/recent?limit=30')).json();
    const runs = (data.jobs || []).filter(j => j.kind === 'pipeline' && j.counts && j.counts.realtime_x > 0);
    if (!runs.length) {
      if (wrap) wrap.hidden = true;
      if (note) note.hidden = true;
      return;
    }
    body.innerHTML = runs.map(j => {
      const c = j.counts;
      const fast = c.realtime_x >= 1;
      const smaller = (j.bytes_in > 0 && j.bytes_out > 0) ? (j.bytes_in / j.bytes_out).toFixed(1) + 'x' : ' - ';
      const ratio = c.time_ratio != null ? c.time_ratio.toFixed(2) : (c.wall_seconds / c.video_seconds).toFixed(2);
      return '<tr><td class="sp-label" title="' + escHtml(j.label || '') + '">' + escHtml(j.label || ' - ') + '</td>' +
        '<td>' + escHtml(String(c.mode || '').replace('mode', 'Mode ')) + '</td>' +
        '<td>' + (c.yolo === undefined ? ' - ' : (c.yolo ? 'On' : 'Off')) + '</td>' +
        '<td>' + escHtml(_fmtSecs(c.video_seconds)) + '</td>' +
        '<td>' + escHtml(_fmtSecs(c.wall_seconds)) + '</td>' +
        '<td>' + escHtml(ratio) + '</td>' +
        '<td class="' + (fast ? 'sp-ok' : 'sp-slow') + '">' + c.realtime_x.toFixed(1) + 'x ' +
          (fast ? 'faster than playback' : 'slower than playback') + '</td>' +
        '<td>' + escHtml(smaller) + '</td></tr>';
    }).join('');
    const slow = runs.filter(j => j.counts.realtime_x < 1).length;
    // With YOLO on, the slowest run in each mode, so "stays above 1x" is one glance.
    const yoloRuns = runs.filter(j => j.counts.yolo);
    const perMode = {};
    yoloRuns.forEach(j => {
      const m = String(j.counts.mode || '');
      if (!perMode[m] || j.counts.realtime_x < perMode[m]) perMode[m] = j.counts.realtime_x;
    });
    const modeBits = Object.keys(perMode).sort().map(m => m.replace('mode', 'Mode ') + ' ' + perMode[m].toFixed(1) + 'x');
    const yoloLine = modeBits.length
      ? ' With YOLO on, the slowest run per mode: ' + modeBits.join(', ') + '.'
      : '';
    if (summary) {
      summary.textContent = (slow === 0
        ? 'Every recorded run finished faster than the video plays (' + runs.length + ' run' + (runs.length === 1 ? '' : 's') + ').'
        : slow + ' of ' + runs.length + ' recorded runs were slower than the video plays.') + yoloLine;
    }
    if (wrap) wrap.hidden = false;
    if (note) note.hidden = false;
  } catch (e) { /* panel keeps its previous contents */ }
}

// ── Recent jobs panel (HOME) ─────────────────────────────────────────────────
// One merged list: every finished job, with the video files it produced.
// Each file has Play (or Unlock when encrypted) and Encrypt, like Metrics.
const _JOB_FILES_SHOWN = 6;
let _jobFileIndex = [];   // flat list so onclick handlers need no escaped paths

function _jobFileButtons(f) {
  const i = _jobFileIndex.push(f) - 1;
  if (!f.exists) return '<span class="jf-missing" title="The file is no longer on disk">missing</span>';
  if (f.encrypted) {
    return '<button class="btn-play-sm btn-enc x-act" title="Encrypted. Click to unlock and play" ' +
      'aria-label="Unlock and play ' + escHtml(f.name) + '" onclick="_jobUnlock(' + i + ')">Unlock</button>' +
      '<span class="x-badge is-on" title="Already encrypted">Locked</span>';
  }
  return (f.url
      ? '<button class="btn-play-sm x-act" aria-label="Play ' + escHtml(f.name) + '" onclick="_jobPlay(' + i + ')">Play</button>'
      : '') +
    '<button class="btn-play-sm x-act" title="Encrypt this video" aria-label="Encrypt ' + escHtml(f.name) +
    '" onclick="_jobEncrypt(' + i + ')">Encrypt</button>';
}
function _jobPlay(i)    { const f = _jobFileIndex[i]; if (f) playSegment(f.url, f.path); }
function _jobUnlock(i)  { const f = _jobFileIndex[i]; if (f) promptDecrypt(f.path); }
function _jobEncrypt(i) { const f = _jobFileIndex[i]; if (f) promptEncryptSegment(f.path); }
function _jobShowAll(el, i) {
  const box = document.getElementById('job-files-' + i);
  if (!box) return;
  box.querySelectorAll('.job-file.is-extra').forEach(n => n.style.display = '');
  el.remove();
}

// "Today: 12 clips, 1.4 GB saved". Counts runs that ended since local
// midnight; space saved only from jobs that recorded both sizes.
function _renderJobsSummary(jobs) {
  let box = document.getElementById('jobs-summary');
  const list = document.getElementById('jobs-list');
  if (!box && list && list.parentNode) {
    box = document.createElement('div');
    box.id = 'jobs-summary';
    box.className = 'jobs-summary';
    list.parentNode.insertBefore(box, list);
  }
  if (!box) return;
  const midnight = new Date(); midnight.setHours(0, 0, 0, 0);
  const since = midnight.getTime() / 1000;
  let clips = 0, saved = 0, runs = 0;
  (jobs || []).forEach((j) => {
    if (j.kind === 'retention' || !(j.ended_at >= since)) return;
    if (String(j.status || 'completed') === 'error') return;
    const c = j.counts || {};
    runs++;
    clips += j.kind === 'autocompress' ? (c.compressed || 0) : 1;
    if (j.bytes_in > 0 && j.bytes_out > 0) saved += Math.max(0, j.bytes_in - j.bytes_out);
  });
  if (!runs) { box.hidden = true; box.textContent = ''; return; }
  box.hidden = false;
  box.innerHTML = 'Today: <b>' + clips + (clips === 1 ? ' clip' : ' clips') + '</b>' +
    (saved > 0 ? ', <b>' + fmtBytes(saved) + '</b> saved' : '');
}

async function loadRecentJobs() {
  const list = document.getElementById('jobs-list');
  if (!list) return;
  try {
    const data = await (await fetch('/api/jobs/recent?limit=30')).json();
    const jobs = data.jobs || [];
    const count = document.getElementById('jobs-count');
    if (count) count.textContent = jobs.length ? jobs.length + ' job' + (jobs.length === 1 ? '' : 's') : '';
    if (!jobs.length) {
      list.innerHTML = '<div class="jobs-empty">No jobs yet. Finished compressions (manual runs and auto-compress batches) will be listed here, each with Play and Encrypt.</div>';
      return;
    }
    _jobFileIndex = [];
    _renderJobsSummary(jobs);
    list.innerHTML = jobs.map((j, ji) => {
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
      const files = j.files || [];
      const fileRows = files.map((f, fi) =>
        '<div class="job-file' + (fi >= _JOB_FILES_SHOWN ? ' is-extra' : '') + '"' +
          (fi >= _JOB_FILES_SHOWN ? ' style="display:none"' : '') + '>' +
          '<span class="jf-name" title="' + escHtml(f.path) + '">' + escHtml(f.name) + '</span>' +
          '<span class="jf-size">' + (f.exists ? fmtBytes(f.size) : '') + '</span>' +
          _jobFileButtons(f) + '</div>').join('');
      const more = files.length > _JOB_FILES_SHOWN
        ? '<div class="job-files-more"><a href="#" onclick="_jobShowAll(this,' + ji + ');return false;">+ ' +
          (files.length - _JOB_FILES_SHOWN) + ' more</a></div>' : '';
      return '<div class="job-block"><div class="job-row">' +
        '<span class="job-status ' + escHtml(status) + '">' + escHtml(status.toUpperCase()) + '</span>' +
        '<span class="job-label" title="' + escHtml(j.label || '') + '">' + escHtml(j.label || ' - ') + '</span>' +
        '<span class="job-meta">' + escHtml(what + saved +
          (j.kind === 'pipeline' && _speedText(c) ? _speedText(c) : (j.elapsed_s != null ? ', ' + fmtDuration(j.elapsed_s) : ''))) + '</span></div>' +
        (files.length ? '<div class="job-files" id="job-files-' + ji + '">' + fileRows + more + '</div>' : '') +
        '</div>';
    }).join('');
  } catch (e) { /* panel keeps its previous contents */ }
}

// ── HLS live streaming (task 4.1) ─────────────────────────────
let _hlsInstance = null;
let _hlsStatusTimer = null;



// ── One-line "what happened" for the newest run ───────────────────────────────
// "45s of video, 1.6 MB, 17.0x smaller, finished in 24s". Built from the job
// record, so it only states what was measured; a part that is not known (a
// live camera has no video length to compare with) is left out.
function runSummaryLine(job) {
  if (!job || !job.counts) return '';
  const c = job.counts;
  const bits = [];
  const vs = Number(c.video_seconds) || 0;
  if (vs > 0) bits.push(fmtDuration(vs) + ' of video');
  const out = Number(job.bytes_out) || 0;
  const inn = Number(job.bytes_in) || 0;
  if (out > 0) bits.push(fmtBytes(out));
  if (out > 0 && inn > out) bits.push((inn / out).toFixed(1) + 'x smaller');
  const wall = Number(c.wall_seconds) || Number(job.elapsed_s) || 0;
  if (wall > 0) bits.push((job.status === 'stopped' ? 'stopped after ' : 'finished in ') + _fmtSecs(wall));
  return bits.length > 1 ? bits.join(', ') : '';
}

async function refreshRunSummary() {
  const el = document.getElementById('lr-summary');
  if (!el) return;
  try {
    const data = await (await fetch('/api/jobs/recent?limit=10')).json();
    const job = (data.jobs || []).find(j => j.kind === 'pipeline');
    const line = runSummaryLine(job);
    el.textContent = line;
    el.hidden = !line;
  } catch (e) { /* the card keeps what it had */ }
}
window.refreshRunSummary = refreshRunSummary;
document.addEventListener('DOMContentLoaded', () => setTimeout(refreshRunSummary, 800));

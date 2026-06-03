/*
 * src/gui/static/js/pipeline.js
 *
 * SVCS dashboard — pipeline module. Carved verbatim from the former single
 * inline <script> in index.html (TASK 1.5). Loaded as a classic script in
 * original execution order, so behavior is identical; all functions stay
 * global (reachable from inline on* handlers and the other modules).
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — JS split).
 */
/* ──────────────────────────────────────────────────────────────
   SVCS Dashboard: client-side logic
   ────────────────────────────────────────────────────────────── */

let logEventSource = null;
let statusInterval  = null;
let storageInterval = null;
let segmentsInterval = null;


// ── Preset card selection ──────────────────────────────────────
function selectPreset(card) {
  document.querySelectorAll('.preset-card').forEach(c => c.classList.remove('selected'));
  card.classList.add('selected');
  const mode = card.dataset.mode;
  document.getElementById('mode-select').value = mode;
  syncModeChips();
}

// ── Advanced panel toggle ──────────────────────────────────────
function toggleAdvanced() {
  const toggle = document.getElementById('advanced-toggle');
  const panel  = document.getElementById('advanced-panel');
  const open   = panel.classList.contains('open');
  if (open) {
    panel.classList.remove('open');
    toggle.classList.remove('open');
  } else {
    panel.classList.add('open');
    toggle.classList.add('open');
  }
}

// ── Sensitivity slider ─────────────────────────────────────────
const _sensitivityLabels = ['Very Low', 'Low', 'Balanced', 'High', 'Very High'];
const _sensitivityBgMethod = ['KNN', 'KNN', 'MOG2', 'MOG2', 'MOG2'];
const _sensitivityWarmup   = [60, 90, 120, 60, 30];

function _onSensitivityChange(val) {
  const idx = parseInt(val) - 1;
  document.getElementById('sensitivity-label').textContent = _sensitivityLabels[idx];
  // Update hidden technical fields
  document.getElementById('bg-method').value    = _sensitivityBgMethod[idx];
  document.getElementById('warmup-frames').value = _sensitivityWarmup[idx];
}

function _onObjectFilterChange(enabled) {
  document.getElementById('filter-confidence-row').style.display = enabled ? '' : 'none';
}

// ── Segment length slider ──────────────────────────────────────
function _onSegLenChange(val) {
  const v = parseInt(val);
  document.getElementById('segment-seconds').value = v;
  const label = v >= 60 ? `${Math.floor(v/60)}m ${v%60 > 0 ? (v%60)+'s' : ''}`.trim() : `${v}s`;
  document.getElementById('seg-len-val').textContent = label;
}

// ── Human-readable status messages ────────────────────────────
function _friendlyStatus(data) {
  if (!data.running) {
    if (data.segment_count > 0) {
      const mb = _lastStorageMb || 0;
      const ratio = _lastCompressionRatio;
      if (ratio && ratio > 1) {
        return { text: `Done: ${data.segment_count} segment${data.segment_count > 1 ? 's' : ''} saved · ${ratio}× smaller than raw`, cls: 'done' };
      }
      return { text: `Done: ${data.segment_count} segment${data.segment_count > 1 ? 's' : ''} saved`, cls: 'done' };
    }
    return { text: 'Ready. Configure a source and press Start.', cls: '' };
  }
  // Running states
  const seg = data.segment_count || 0;
  const fps = data.fps != null ? ` · ${data.fps} fps` : '';
  if (data.progress_pct != null) {
    const pct = data.progress_pct;
    if (pct < 2) return { text: `Warming up…${fps}`, cls: 'running' };
    const eta = data.eta_seconds;
    const etaStr = eta != null
      ? (eta >= 60 ? `~${Math.ceil(eta/60)}min left` : `~${eta}s left`)
      : '';
    return { text: `Processing: segment ${seg + 1}  ·  ${pct.toFixed(0)}% through video${etaStr ? '  ·  ' + etaStr : ''}${fps}`, cls: 'running' };
  }
  // Live stream
  const elapsed = data.elapsed_seconds != null ? fmtDuration(data.elapsed_seconds) : '';
  return { text: `Recording live${elapsed ? ' (' + elapsed + ')' : ''} · Segment ${seg + 1}${fps}`, cls: 'running' };
}

let _lastStorageMb = 0;
let _lastCompressionRatio = null;

// ── Toggle helpers ────────────────────────────────────────────
function updateEnhanceFields() {
  const on = document.getElementById('enhance-toggle').checked;
  const el = document.getElementById('enhance-extra');
  el.style.opacity = on ? '1' : '0.4';
  el.style.pointerEvents = on ? 'all' : 'none';
}
function updateEncryptFields() {
  const on = document.getElementById('encrypt-toggle').checked;
  const el = document.getElementById('encrypt-extra');
  el.style.opacity = on ? '1' : '0.4';
  el.style.pointerEvents = on ? 'all' : 'none';
}

async function generateKeyFile() {
  // Called from both the sidebar encryption <details> and the enc-panel keygen strip.
  // Determine which context we're in by checking the caller's strip.
  const panelNameInput = document.getElementById('enc-keygen-name');
  const filename = panelNameInput ? (panelNameInput.value.trim() || 'camera.key') : 'camera.key';

  const sidebarResult = document.getElementById('keygen-result');
  const panelResult   = document.getElementById('enc-keygen-result');
  if (sidebarResult) { sidebarResult.textContent = 'Generating…'; sidebarResult.style.display = 'block'; }
  if (panelResult)   { panelResult.textContent = 'Generating…'; panelResult.style.color = 'var(--text-dim)'; }

  try {
    const res  = await fetch('/api/keygen', { method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ filename }) });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || res.statusText);

    // Update sidebar
    const sideKF = document.getElementById('encrypt-keyfile');
    if (sideKF) sideKF.value = data.path;
    if (sidebarResult) { sidebarResult.textContent = ` Key saved → ${data.path}`; sidebarResult.style.color = 'var(--green)'; }

    // Update enc-panel — pre-fill both keyfile inputs and show result
    const encKF = document.getElementById('enc-keyfile-path');
    if (encKF) encKF.value = data.path;
    const decKF = document.getElementById('dec-keyfile-path');
    if (decKF) decKF.value = data.path;
    if (panelResult) { panelResult.textContent = ` Saved: ${data.path}`; panelResult.style.color = 'var(--green)'; }
  } catch(e) {
    if (sidebarResult) { sidebarResult.textContent = '[!] ' + e.message; sidebarResult.style.color = 'var(--red)'; }
    if (panelResult)   { panelResult.textContent = '[!] ' + e.message; panelResult.style.color = 'var(--red)'; }
  }
}

// ── Mode select sync to mode chips + preset cards ──────────────
document.getElementById('mode-select').addEventListener('change', syncModeChips);
document.getElementById('enhance-toggle').addEventListener('change', syncModeChips);
document.getElementById('encrypt-toggle').addEventListener('change', syncModeChips);
function syncModeChips() {
  const mode = document.getElementById('mode-select').value;
  document.querySelectorAll('.mode-chip[data-mode]').forEach(c => {
    c.classList.toggle('active', c.dataset.mode === mode);
  });
  document.getElementById('chip-enhance').classList.toggle(
    'active', document.getElementById('enhance-toggle').checked);
  document.getElementById('chip-encrypt').classList.toggle(
    'active', document.getElementById('encrypt-toggle').checked);
  // Sync preset cards
  document.querySelectorAll('.preset-card').forEach(c => {
    c.classList.toggle('selected', c.dataset.mode === mode);
  });
}
syncModeChips();

// ── Scan videos in data/ folder ───────────────────────────────
async function scanVideos() {
  try {
    const res = await fetch('/api/scan_videos');
    const data = await res.json();
    const listEl = document.getElementById('video-list');
    if (!data.videos.length) {
      listEl.innerHTML = `<div style="font-family:var(--mono);font-size:0.6rem;color:var(--text-dim);">
        No videos found in ${escHtml(data.data_dir)}</div>`;
      return;
    }
    listEl.innerHTML = data.videos.map(v => {
      const name = v.split('/').pop();
      return `<div onclick="document.getElementById('input-source').value='${escHtml(v)}';_onInputSourceChange('${escHtml(v)}')"
                   style="font-family:var(--mono);font-size:0.62rem;color:var(--amber);
                          cursor:pointer;padding:0.2rem 0;border-bottom:1px solid var(--border);"
                   title="${escHtml(v)}">▸ ${escHtml(name)}</div>`;
    }).join('');
  } catch(e) {
    console.error('scanVideos', e);
  }
}

// ── Input source helpers ──────────────────────────────────────
function _isLiveSource(val) {
  // Live = integer webcam index or URL scheme (rtsp/http/etc)
  return /^\d+$/.test(val.trim()) ||
         /^(rtsp|rtsps|rtmp|http|https):\/\//i.test(val.trim());
}

function _autoCamera(val) {
  // Derive a short camera ID from filename, e.g. "cameraJitter_traffic" → "cameraJitter_traffic"
  const fname = val.trim().split(/[\\/]/).pop().replace(/\.[^.]+$/, '');
  // Sanitize to alphanum/underscore/hyphen
  return fname.replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 40) || 'cam_00';
}

function _onInputSourceChange(val) {
  const field = document.getElementById('camera-id-field');
  if (_isLiveSource(val)) {
    field.style.display = '';   // show Camera ID for live sources
  } else {
    field.style.display = 'none'; // hide for file sources
    // Store the auto-derived ID in the hidden field
    document.getElementById('camera-id-auto').value = _autoCamera(val);
  }
  // Keep DEMO tab source display in sync
  _syncDemoSrcDisplay();
}

// ── File upload from remote device ────────────────────────────
async function _uploadVideoFile(file) {
  const status = document.getElementById('upload-status');
  status.textContent = `Uploading ${file.name}…`;
  const form = new FormData();
  form.append('file', file);
  try {
    const res = await fetch('/api/upload', { method: 'POST', body: form });
    const data = await res.json();
    if (!res.ok) { status.textContent = `Error: ${data.error}`; return; }
    document.getElementById('input-source').value = data.path;
    _onInputSourceChange(data.path);
    status.textContent = ` ${data.filename} ready`;
  } catch(e) {
    status.textContent = `Upload failed: ${e}`;
  }
}

async function _uploadVideo(input) {
  if (!input.files.length) return;
  await _uploadVideoFile(input.files[0]);
  input.value = '';  // reset so same file can be re-selected
}

// ── Drag-and-drop on upload zone ──────────────────────────────
(function _initUploadZoneDnD() {
  document.addEventListener('DOMContentLoaded', () => {
    const zone = document.getElementById('upload-zone');
    if (!zone) return;
    zone.addEventListener('dragover', (e) => {
      e.preventDefault();
      zone.classList.add('drag-over');
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', async (e) => {
      e.preventDefault();
      zone.classList.remove('drag-over');
      const file = e.dataTransfer.files[0];
      if (file) await _uploadVideoFile(file);
    });
  });
})();

// ── Clear output segments ─────────────────────────────────────
async function clearSegments() {
  if (!confirm('Hide all segments from the dashboard? Files on disk are kept. This only clears the view.')) return;
  try {
    const res = await fetch('/api/segments/clear', { method: 'POST' });
    const data = await res.json();
    if (!res.ok) { alert(data.error || 'Clear failed'); return; }
    await loadSegments();
  } catch(e) {
    alert(`Clear failed: ${e}`);
  }
}

// ── Hide a single segment row ─────────────────────────────────
// Per-row [×] button. Doesn't delete the file — just sets hidden=1
// in the metadata DB so the row stops showing up. Used for the
// dangling test rows that have no file on disk.
// Author: Bloodawn (KheivenD), 2026-05-03 (cleanup of dead rows).
async function _hideSegmentRow(filePath) {
  if (!filePath) return;
  try {
    const res = await fetch('/api/segments/hide_one', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath }),
    });
    const data = await res.json();
    if (!res.ok) { alert(data.error || 'Hide failed'); return; }
    await loadSegments();
  } catch(e) {
    alert(`Hide failed: ${e}`);
  }
}

// One-shot cleanup: hide every row whose file is gone from disk.
// Called once on dashboard load so old test rows don't pile up.
async function _cleanupMissingSegments() {
  try {
    const res = await fetch('/api/segments/cleanup_missing', { method: 'POST' });
    const data = await res.json();
    if (data && data.hidden > 0) {
      console.log(`[svcs] auto-hid ${data.hidden} dangling segment row(s)`);
    }
  } catch (e) {
    // Best effort — never block dashboard startup on this sweep
    console.warn('cleanup_missing failed:', e);
  }
}

// ── Cloud storage output — auto-detect on load ──────────────────
let _cloudWebUrl = null;   // populated by _initGDriveOutput, used by _openCloudFolder

async function _initGDriveOutput() {
  // FIX 1: no silent cloud default. The output folder comes from the user's
  // explicit Setup choice (see setup.js, /api/setup/state). This function used
  // to auto-detect OneDrive/Drive and fill the field; it now only refreshes the
  // status line and hides the "View Online" button unless the chosen path is a
  // cloud folder. setup.js owns populating #output-dir.
  const statusEl = document.getElementById('gdrive-status');
  const viewBtn  = document.getElementById('gdrive-view-btn');
  if (viewBtn && !_cloudWebUrl) viewBtn.style.display = 'none';
  if (statusEl) {
    statusEl.textContent = '';
    statusEl.style.background = 'transparent';
  }
}

function _openCloudFolder() {
  if (_cloudWebUrl) window.open(_cloudWebUrl, '_blank');
}

// ── Start pipeline ────────────────────────────────────────────
async function startPipeline() {
  clearError();
  const inputSrc = document.getElementById('input-source').value.trim();
  // Use Camera ID field for live sources, auto-derive from filename for files
  const cameraId = _isLiveSource(inputSrc)
    ? (document.getElementById('camera-id').value.trim() || 'cam_00')
    : (document.getElementById('camera-id-auto').value || _autoCamera(inputSrc));
  const config = {
    input_source:     inputSrc,
    camera_id:        cameraId,
    output_dir:       document.getElementById('output-dir').value.trim(),
    segment_seconds:  parseInt(document.getElementById('segment-seconds').value),
    warmup_frames:    parseInt(document.getElementById('warmup-frames').value),
    bg_method:        document.getElementById('bg-method').value,
    mode:             document.getElementById('mode-select').value,
    enhance:          document.getElementById('enhance-toggle').checked,
    enhance_model:    document.getElementById('enhance-model').value,
    enhance_scale:    parseInt(document.getElementById('enhance-scale').value),
    enhance_every_n:  parseInt(document.getElementById('enhance-every-n').value),
    enhance_max_roi_px: parseInt(document.getElementById('enhance-max-roi').value),
    enhance_device:   document.getElementById('enhance-device').value,
    upscale_output:   document.getElementById('upscale-output-toggle').checked,
    encrypt:          document.getElementById('encrypt-toggle').checked,
    encrypt_password: document.getElementById('encrypt-password').value,
    encrypt_key_file: document.getElementById('encrypt-keyfile').value.trim(),
    object_filter:    document.getElementById('object-filter-toggle').checked,
    filter_confidence: parseFloat(document.getElementById('filter-confidence').value),
    // Codec selector — Save To section. Pass through to /api/start. Default
    // "auto" lets the backend pick the per-mode codec (H.264 for mode0/1, AV1
    // for mode2/3); explicit choices override. Author: Bloodawn (KheivenD),
    // 2026-05-02, updated 2026-06-02 (TASK 1.6 per-mode codec).
    codec:            (document.getElementById('codec-select') || {}).value || 'auto',
    // CRF override. Empty string means "use the mode default" — the
    // backend treats unset/blank as None and falls back to 18 / 38.
    crf:              ((document.getElementById('crf-input') || {}).value || '').trim(),
    // Named preset + background CRF (M3 TASK 3.1). Set by presets.js when the
    // operator picks a named surveillance preset; blank otherwise.
    background_crf:   (window._svcsPreset && window._svcsPreset.background_crf != null
                       ? String(window._svcsPreset.background_crf) : ''),
    preset:           (window._svcsPreset && window._svcsPreset.key) || '',
    // Verbose logging toggle (FIX 7): adds per-frame / per-segment detail.
    verbose:          (document.getElementById('verbose-toggle') || {}).checked || false,
  };

  try {
    const res = await fetch('/api/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(config),
    });
    const data = await res.json();
    if (!res.ok) {
      showError(data.error || 'Failed to start pipeline');
      return;
    }
    setPipelineRunning(true);
    startSSE();
    startPolling();
  } catch(e) {
    showError(String(e));
  }
}

// ── Stop pipeline ─────────────────────────────────────────────
async function stopPipeline() {
  try {
    await fetch('/api/stop', { method: 'POST' });
  } catch(e) {
    console.error('stop', e);
  }
}

// ── Config export ─────────────────────────────────────────────
function saveConfig() {
  window.location.href = '/api/config/export';
}

// ── Config import ─────────────────────────────────────────────
function loadConfig() {
  document.getElementById('config-import-input').value = '';
  document.getElementById('config-import-input').click();
}

async function _onConfigFileSelected(evt) {
  const file = evt.target.files[0];
  if (!file) return;

  let raw;
  try {
    raw = await file.text();
  } catch (e) {
    _configImportToast('Could not read file: ' + e.message, true);
    return;
  }

  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch (e) {
    _configImportToast('Not valid JSON: ' + e.message, true);
    return;
  }

  // Send to backend for validation and storage as last_config
  let cfg;
  try {
    const resp = await fetch('/api/config/import', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(parsed),
    });
    const result = await resp.json();
    if (!resp.ok || result.error) {
      _configImportToast('Import error: ' + (result.error || resp.statusText), true);
      return;
    }
    cfg = result.config;
  } catch (e) {
    _configImportToast('Server error: ' + e.message, true);
    return;
  }

  // Apply each field to the form
  _applyImportedConfig(cfg);
  _configImportToast('Config loaded from ' + file.name);
}

function _applyImportedConfig(cfg) {
  // Input source + camera + output dir
  if (cfg.input_source != null) document.getElementById('input-source').value = cfg.input_source;
  if (cfg.camera_id   != null) document.getElementById('camera-id').value    = cfg.camera_id;
  if (cfg.output_dir  != null) {
    document.getElementById('output-dir').value = cfg.output_dir;
    // If import overrides the Drive path, re-run detection so the status badge stays accurate
    _initGDriveOutput();
  }

  // Mode: click the matching preset card
  if (cfg.mode) {
    const card = document.querySelector(`.preset-card[data-mode="${cfg.mode}"]`);
    if (card) selectPreset(card);
  }

  // Segment length: drive both slider and hidden input
  if (cfg.segment_seconds != null) {
    const slider = document.getElementById('segment-seconds-slider');
    slider.value = cfg.segment_seconds;
    _onSegLenChange(cfg.segment_seconds);
  }

  // BG method + warmup: try to find matching sensitivity slider position,
  // otherwise set the hidden fields directly and open Advanced settings so
  // the operator can see they were applied.
  if (cfg.bg_method != null) {
    const bgMethodEl = document.getElementById('bg-method');
    if (bgMethodEl) bgMethodEl.value = cfg.bg_method;
    const wfEl = document.getElementById('warmup-frames');
    if (cfg.warmup_frames != null && wfEl) wfEl.value = cfg.warmup_frames;

    // Try to snap sensitivity slider to nearest equivalent position
    const bgMethods  = ['KNN', 'KNN', 'MOG2', 'MOG2', 'MOG2'];
    const warmupVals = [60, 90, 120, 60, 30];
    let bestIdx = 2; // default "Balanced"
    for (let i = 0; i < bgMethods.length; i++) {
      if (bgMethods[i] === cfg.bg_method &&
          (cfg.warmup_frames == null || warmupVals[i] === cfg.warmup_frames)) {
        bestIdx = i;
        break;
      }
    }
    const sensitivityEl = document.getElementById('sensitivity-slider');
    if (sensitivityEl) {
      sensitivityEl.value = bestIdx + 1;
      _onSensitivityChange(bestIdx + 1);
    }
  }

  // Enhancement
  const enhToggle = document.getElementById('enhance-toggle');
  if (enhToggle && cfg.enhance != null) {
    enhToggle.checked = !!cfg.enhance;
    updateEnhanceFields();
  }
  if (cfg.enhance_model != null) {
    const el = document.getElementById('enhance-model');
    if (el) el.value = cfg.enhance_model;
  }
  if (cfg.enhance_scale != null) {
    const el = document.getElementById('enhance-scale');
    if (el) el.value = String(cfg.enhance_scale);
  }
  if (cfg.enhance_every_n != null) {
    const el = document.getElementById('enhance-every-n');
    if (el) el.value = String(cfg.enhance_every_n);
  }
  if (cfg.enhance_device != null) {
    const el = document.getElementById('enhance-device');
    if (el) el.value = cfg.enhance_device;
  }
  const upscaleOutToggle = document.getElementById('upscale-output-toggle');
  if (upscaleOutToggle && cfg.upscale_output != null) {
    upscaleOutToggle.checked = !!cfg.upscale_output;
  }

  // Object filter
  const filterToggle = document.getElementById('object-filter-toggle');
  if (filterToggle && cfg.object_filter != null) {
    filterToggle.checked = !!cfg.object_filter;
    _onObjectFilterChange(filterToggle.checked);
  }
  if (cfg.filter_confidence != null) {
    const el = document.getElementById('filter-confidence');
    if (el) el.value = String(cfg.filter_confidence);
  }

  // Encryption (toggle only — credentials are never in the config file)
  const encToggle = document.getElementById('encrypt-toggle');
  if (encToggle && cfg.encrypt != null) {
    encToggle.checked = !!cfg.encrypt;
    updateEncryptFields();
  }

  // Sync mode indicator chips
  syncModeChips();

  // Open Advanced settings if any advanced field was set so the operator
  // can see what was applied
  const advancedWasSet = cfg.enhance || cfg.object_filter || cfg.encrypt ||
    cfg.bg_method !== 'MOG2' || (cfg.warmup_frames != null && cfg.warmup_frames !== 120);
  if (advancedWasSet) {
    const panel = document.getElementById('advanced-panel');
    if (panel && !panel.classList.contains('open')) toggleAdvanced();
  }
}

// Small toast message for import feedback (reuses error-banner element)
function _configImportToast(msg, isError = false) {
  const banner = document.getElementById('error-banner');
  if (!banner) { console.log('[config-import]', msg); return; }
  banner.textContent = msg;
  banner.style.display = 'block';
  banner.style.background = isError ? 'var(--red-dim, #4a1f1f)' : 'var(--surface3)';
  banner.style.color = isError ? 'var(--red)' : 'var(--green)';
  banner.style.padding = '0.4rem 0.75rem';
  banner.style.borderRadius = '4px';
  banner.style.fontFamily = 'var(--mono)';
  banner.style.fontSize = '0.65rem';
  banner.style.marginBottom = '0.5rem';
  clearTimeout(banner._toastTimer);
  banner._toastTimer = setTimeout(() => {
    banner.style.display = 'none';
    banner.textContent = '';
  }, 4000);
}

// ── HLS latency poller ────────────────────────────────────────
// Polls /api/hls/latency after the manifest parses, surfacing two metrics
// in the LIVE banner:
//
//   • ingest latency — one-shot, FFmpeg-launch → first .ts segment.
//   • end-to-end avg — rolling median frame age across the last N segments
//     (ROADMAP 5.1 — Cody's hardware-sizing ask from the April 22 meeting).
//
// We keep polling for the first ~30 s to catch the ingest sample, then
// downshift to a 5 s cadence so the rolling avg keeps refreshing without
// hammering the server.
//
// Author: Bloodawn (KheivenD)
let _hlsLatencyTimer = null;

function _stopHlsLatencyPoller() {
  if (_hlsLatencyTimer) { clearTimeout(_hlsLatencyTimer); _hlsLatencyTimer = null; }
}

async function _pollHlsLatency(camId, attempt) {
  const FAST_MAX = 30;          // 1 s cadence for the first 30 polls
  const FAST_MS  = 1000;
  const SLOW_MS  = 5000;        // 5 s cadence after that
  if (attempt > 600) { _stopHlsLatencyPoller(); return; }

  try {
    const r = await fetch('/api/hls/latency');
    const d = await r.json();

    const msgEl = document.getElementById('hls-status-msg');
    if (msgEl) {
      const parts = [];
      if (d.ingest_latency_s !== null && d.ingest_latency_s !== undefined) {
        parts.push('ingest ' + d.ingest_latency_s + 's');
      }
      if (d.latency_avg_s !== null && d.latency_avg_s !== undefined) {
        // Show samples count so the operator can tell when the average is
        // still stabilising (e.g. "avg 1.04s n=3" right after start).
        parts.push('avg ' + d.latency_avg_s + 's' + ' n=' + (d.latency_samples || 0));
      }
      if (parts.length) {
        msgEl.textContent = '● LIVE: ' + camId + '  (' + parts.join(' · ') + ')';
      } else if (d.measuring) {
        msgEl.textContent = '● LIVE: ' + camId + '  (measuring latency…)';
      }
    }

    // Keep polling: rolling avg drifts as more segments come in. Slow down
    // after the first burst to spare the server.
    const wait = (attempt < FAST_MAX) ? FAST_MS : SLOW_MS;
    _hlsLatencyTimer = setTimeout(() => _pollHlsLatency(camId, attempt + 1), wait);
  } catch (_e) {
    // Non-fatal: keep polling at the slow cadence so transient errors don't
    // wedge the latency display.
    _hlsLatencyTimer = setTimeout(() => _pollHlsLatency(camId, attempt + 1), 5000);
  }
}

// ── SSE log stream ────────────────────────────────────────────
function startSSE() {
  if (logEventSource) { logEventSource.close(); }
  logEventSource = new EventSource('/api/logs');
  logEventSource.onmessage = (ev) => {
    const line = JSON.parse(ev.data);
    appendLog(line);
  };
  logEventSource.onerror = () => {
    // reconnect after 3s
    setTimeout(startSSE, 3000);
  };
}

function appendLog(line) {
  const el = document.getElementById('log-terminal');
  const span = document.createElement('span');
  span.className = 'log-line ' + getLogLevel(line);
  span.textContent = line + '\n';
  el.appendChild(span);
  // cap at 600 lines
  while (el.children.length > 600) { el.removeChild(el.firstChild); }
  el.scrollTop = el.scrollHeight;
}

function getLogLevel(line) {
  if (line.includes(' ERROR ') || line.includes(' CRITICAL ')) return 'ERROR';
  if (line.includes(' WARNING ')) return 'WARNING';
  if (line.includes(' DEBUG ')) return 'DEBUG';
  return 'INFO';
}

function clearLog() {
  document.getElementById('log-terminal').innerHTML = '';
}

// ── Resizable panels (both horizontal and vertical) ──────
let isResizingV = false;
let startY = 0;
let startHeight = 0;

// Vertical drag: resizes content-top by updating the main grid's first row height
document.getElementById('resize-divider-v')?.addEventListener('mousedown', (e) => {
  isResizingV = true;
  startY = e.clientY;
  // Read current first-row height from the grid
  const main = document.querySelector('main');
  startHeight = parseInt(getComputedStyle(main).gridTemplateRows.split(' ')[0], 10) || 320;
  document.getElementById('resize-divider-v').classList.add('active');
  e.preventDefault();
});

document.addEventListener('mousemove', (e) => {
  if (!isResizingV) return;
  const main = document.querySelector('main');
  const delta = e.clientY - startY;
  const newHeight = startHeight + delta;
  const minH = 160;
  const maxH = main.offsetHeight - 160;
  const h = Math.max(minH, Math.min(newHeight, maxH));
  main.style.gridTemplateRows = h + 'px 6px 1fr';
});

document.addEventListener('mouseup', () => {
  if (isResizingV) {
    document.getElementById('resize-divider-v').classList.remove('active');
  }
  isResizingV = false;
});

// ── Toggle log panel ──────────────────────────────────────
function toggleLogPanel() { toggleHomeLog(); }  // legacy alias

function toggleHomeLog() {
  const section = document.getElementById('home-log-section');
  if (!section) return;
  const isOpen = section.classList.contains('expanded');
  if (isOpen) {
    section.classList.remove('expanded');
  } else {
    section.classList.add('expanded');
    const terminal = document.getElementById('log-terminal');
    if (terminal) setTimeout(() => { terminal.scrollTop = terminal.scrollHeight; }, 50);
  }
}

// ── Segment hover tooltip ─────────────────────────────────
const _tooltip = document.getElementById('seg-tooltip');

function _showSegTooltip(evt, seg) {
  const rawMb  = (seg.duration_s * (seg.width || 640) * (seg.height || 480) * 3 * (seg.fps || 25)) / 1e6;
  const compMb = seg.file_size_kb / 1024;
  const ratio  = rawMb > 0 ? (rawMb / compMb).toFixed(1) : null;
  const savedPct = rawMb > 0 ? Math.round((1 - compMb / rawMb) * 100) : null;
  const isEnc  = seg.file_path && seg.file_path.endsWith('.enc');

  // ── Plain-English lines ──────────────────────────────────
  const lines = [];

  // Was anything detected?
  if (seg.target_detected) {
    lines.push(`Motion detected — ${seg.object_type !== 'unknown' ? seg.object_type : 'object'} captured`);
  } else {
    lines.push(`Background only — no movement detected`);
  }

  // Compression result
  if (ratio !== null) {
    lines.push(`Compressed: ${savedPct}% smaller than raw`);
    lines.push(`   Before: ~${rawMb.toFixed(0)} MB uncompressed`);
    lines.push(`   After:  ${compMb >= 1 ? compMb.toFixed(1) + ' MB' : seg.file_size_kb + ' KB'} saved to disk`);
    lines.push(`   Ratio:  ${ratio}× space saving`);
  } else {
    lines.push(` File size: ${compMb >= 1 ? compMb.toFixed(1) + ' MB' : seg.file_size_kb + ' KB'}`);
  }

  // Clip info
  lines.push(`Length:  Length: ${seg.duration_s} seconds`);
  lines.push(`Detections: ${seg.roi_count} motion region${seg.roi_count !== 1 ? 's' : ''} in this clip`);

  // Quality
  if (seg.sharpness_label) {
    const q = seg.sharpness_label;
    const readable = q.includes('blurry') ? 'Blurry (low res camera or motion blur)' :
                     q.includes('1080') ? 'Sharp — 1080p quality' :
                     q.includes('720')  ? 'Good — 720p quality'  :
                     q.includes('480')  ? 'Fair — 480p quality'  :
                     q.includes('240')  ? 'Poor — 240p quality'  : q;
    lines.push(`Quality: ${readable}`);
  }

  // Encryption
  if (isEnc) {
    lines.push(` File is encrypted (AES-256) — password required to view`);
  }

  // Camera
  lines.push(`Camera: ${seg.camera_id}`);

  _tooltip.textContent = lines.join('\n');
  _tooltip.classList.add('visible');
  _moveTooltip(evt);
}

function _moveTooltip(evt) {
  const tw = _tooltip.offsetWidth;
  const th = _tooltip.offsetHeight;
  let x = evt.clientX + 14;
  let y = evt.clientY + 14;
  if (x + tw > window.innerWidth - 8) x = evt.clientX - tw - 14;
  if (y + th > window.innerHeight - 8) y = evt.clientY - th - 14;
  _tooltip.style.left = x + 'px';
  _tooltip.style.top  = y + 'px';
}

function _hideTooltip() {
  _tooltip.classList.remove('visible');
}

// ── Status polling ────────────────────────────────────────────

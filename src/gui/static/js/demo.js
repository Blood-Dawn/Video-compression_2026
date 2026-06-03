/*
 * src/gui/static/js/demo.js
 *
 * SVCS dashboard — demo module. Carved verbatim from the former single
 * inline <script> in index.html (TASK 1.5). Loaded as a classic script in
 * original execution order, so behavior is identical; all functions stay
 * global (reachable from inline on* handlers and the other modules).
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — JS split).
 */
async function browseFile() {
  try {
    const res = await fetch('/api/browse');
    const data = await res.json();
    if (data.path) {
      document.getElementById('input-source').value = data.path;
      _onInputSourceChange(data.path);
    }
  } catch(e) {
    console.error('browseFile', e);
  }
}

// ── Demo compare ──────────────────────────────────────────────
let _demoPollTimer = null;

// Keep demo-src-display in sync with sidebar #input-source
function _syncDemoSrcDisplay() {
  const src  = document.getElementById('input-source');
  const disp = document.getElementById('demo-src-display');
  if (!disp) return;
  const val = src ? src.value.trim() : '';
  disp.value = val;
  const status = document.getElementById('demo-src-status');
  if (status) {
    status.textContent = val ? 'Ready — ' + val.split(/[\\/]/).pop() : '';
    status.style.color = val ? 'var(--green)' : 'var(--text-dim)';
  }
}

// Upload a file chosen directly from the DEMO tab's file picker
async function _demoPickFile(input) {
  if (!input.files.length) return;
  const status = document.getElementById('demo-src-status');
  if (status) { status.textContent = 'Uploading…'; status.style.color = 'var(--amber)'; }
  // Reuse the main upload logic
  await _uploadVideoFile(input.files[0]);
  // _uploadVideoFile sets #input-source — mirror it
  _syncDemoSrcDisplay();
  input.value = '';
}

// ── Notification system ───────────────────────────────────────
function pushNotif(title, msg, type, actions, autoDismissMs) {
  // type: 'success' | 'info' | 'error'
  // actions: [{label, fn}]
  autoDismissMs = autoDismissMs != null ? autoDismissMs : 0;
  const dock = document.getElementById('notif-dock');
  if (!dock) return;

  const card = document.createElement('div');
  card.className = 'notif-card notif-' + (type || 'info');

  let actionsHtml = '';
  if (actions && actions.length) {
    actionsHtml = '<div class="notif-actions">';
    actions.forEach(function(a, i) {
      actionsHtml += '<button class="notif-btn" data-ai="' + i + '">' + a.label + '</button>';
    });
    actionsHtml += '</div>';
  }

  card.innerHTML =
    '<div class="notif-body">' +
      '<div class="notif-title">' + title + '</div>' +
      '<div class="notif-msg">' + msg + '</div>' +
      actionsHtml +
    '</div>' +
    '<button class="notif-close" title="Dismiss">&times;</button>';

  dock.appendChild(card);

  // Wire action buttons
  if (actions && actions.length) {
    card.querySelectorAll('.notif-btn').forEach(function(btn) {
      const idx = parseInt(btn.dataset.ai, 10);
      btn.addEventListener('click', function() { actions[idx].fn(); });
    });
  }
  card.querySelector('.notif-close').addEventListener('click', function() {
    card.style.opacity = '0';
    card.style.transition = 'opacity 0.2s';
    setTimeout(function() { card.remove(); }, 220);
  });

  if (autoDismissMs > 0) {
    setTimeout(function() {
      if (card.parentNode) {
        card.style.opacity = '0';
        card.style.transition = 'opacity 0.2s';
        setTimeout(function() { card.remove(); }, 220);
      }
    }, autoDismissMs);
  }
  return card;
}

async function openFolder(folderPath) {
  try {
    await fetch('/api/open_folder', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: folderPath }),
    });
  } catch(e) { console.warn('open_folder failed:', e); }
}

// ── Demo (sidebar) ────────────────────────────────────────────
const _DEMO_PHASE_LABELS = {
  start: 'STARTING', pipeline: 'COMPRESSING',
  render: 'RENDERING', stitch: 'STITCHING', done: 'COMPLETE',
};
let _demoPct = 0;

async function runDemo() {
  const modes = ['mode0', 'mode1', 'mode2', 'mode3'].filter(function(m) {
    const el = document.getElementById('demo-' + m);
    return el && el.checked;
  });
  if (!modes.length) { alert('Select at least one demo mode.'); return; }

  const inputPath = document.getElementById('input-source').value.trim();
  if (!inputPath) { alert('Set an input source first.'); return; }

  // Use whatever is in the field (pre-filled by _initGDriveOutput on load).
  // Send empty string when blank — backend will resolve to OneDrive or local outputs/.
  const outputRoot = document.getElementById('demo-output-dir').value.trim();
  const noBoxes    = document.getElementById('demo-no-boxes').checked;
  // Camera ID priority for demo runs:
  //   1. Live source (webcam idx / RTSP URL) → use the visible #camera-id field
  //   2. File source                          → use the filename stem (auto-derived)
  // The visible #camera-id field is HIDDEN for file sources, so reading it
  // unconditionally was always falling through to "cam_00" — that's why
  // every recording from a file showed up as "cam_00" in the metrics table.
  // Fixed 2026-05-03 (UI fix pass). Author: Bloodawn (KheivenD).
  const cameraId = _isLiveSource(inputPath)
    ? (document.getElementById('camera-id').value.trim() || 'cam_00')
    : (document.getElementById('camera-id-auto').value || _autoCamera(inputPath));

  document.getElementById('btn-run-demo').disabled = true;
  _demoShowProgress('Starting…', 5);

  try {
    const res = await fetch('/api/demo', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input_path: inputPath, output_root: outputRoot,
                             camera_id: cameraId, modes, views: ['standard'],
                             no_boxes: noBoxes, no_tint: noTint }),
    });
    const data = await res.json();
    if (!res.ok) {
      _demoHideProgress();
      pushNotif('DEMO ERROR', data.error || ('HTTP ' + res.status), 'error', null, 8000);
      document.getElementById('btn-run-demo').disabled = false;
      return;
    }
    _demoPct = 5;
    pollDemoStatus();
  } catch(e) {
    _demoHideProgress();
    pushNotif('DEMO ERROR', String(e), 'error', null, 8000);
    document.getElementById('btn-run-demo').disabled = false;
  }
}

function _demoShowProgress(msg, pct) {
  const wrap = document.getElementById('demo-sidebar-status');
  const msgEl = document.getElementById('demo-sidebar-msg');
  const bar   = document.getElementById('demo-progress-bar');
  if (wrap)  wrap.style.display = '';
  if (msgEl) msgEl.textContent  = msg || '';
  if (bar)   bar.style.width    = (pct || 0) + '%';
  // Expand the demo details panel so user can see progress
  const det = document.getElementById('demo-sidebar-details');
  if (det && !det.open) det.open = true;
}

function _demoHideProgress() {
  const wrap = document.getElementById('demo-sidebar-status');
  if (wrap) wrap.style.display = 'none';
  const bar = document.getElementById('demo-progress-bar');
  if (bar)  bar.style.width = '0%';
}

function pollDemoStatus() {
  if (_demoPollTimer) clearTimeout(_demoPollTimer);
  _demoPollTimer = setTimeout(async function() {
    try {
      const res  = await fetch('/api/demo/status');
      const data = await res.json();

      if (data.status === 'running' || data.status === 'queued') {
        const phase = data.demo_phase || 'running';
        const label = _DEMO_PHASE_LABELS[phase] || phase.toUpperCase();
        const step  = data.demo_step  ? ' — ' + data.demo_step  : '';
        const mode  = data.demo_mode  ? ' (' + data.demo_mode.toUpperCase() + ')' : '';
        _demoShowProgress(label + step + mode, _demoPct);

        if (phase === 'pipeline' && _demoPct < 70) _demoPct = Math.min(_demoPct + 8, 70);
        if (phase === 'render'   && _demoPct < 88) _demoPct = Math.min(_demoPct + 6, 88);
        if (phase === 'stitch'   && _demoPct < 95) _demoPct = Math.min(_demoPct + 4, 95);
        pollDemoStatus();

      } else if (data.status === 'done' && data.result) {
        _demoHideProgress();
        document.getElementById('btn-run-demo').disabled = false;
        _demoNotifyDone(data.result);

      } else if (data.status === 'error') {
        _demoHideProgress();
        document.getElementById('btn-run-demo').disabled = false;
        pushNotif('DEMO ERROR', data.error || 'Unknown error', 'error', null, 10000);

      } else {
        pollDemoStatus();
      }
    } catch(e) {
      pollDemoStatus();
    }
  }, 1000);
}

/**
 * Build the flat list of playable demo videos returned by /api/demo/status.
 *
 * The backend returns:
 *   result.split_screen  – string URL or null
 *   result.videos        – { mode: { view: url|null } }
 *
 * Each entry is `{ label, url }` where `url` is already a `/api/media?path=`
 * URL ready for an inline <video src=…>. Filters out entries without a URL
 * (mode rendered but file missing).
 *
 * Author: Bloodawn (KheivenD)
 */
function _demoCollectPlayables(result) {
  const out = [];
  if (result && result.split_screen) {
    out.push({ label: 'SPLIT SCREEN', url: result.split_screen });
  }
  const videos = (result && result.videos) || {};
  Object.keys(videos).sort().forEach(function(mode) {
    const views = videos[mode] || {};
    Object.keys(views).sort().forEach(function(view) {
      const url = views[view];
      if (!url) return;
      const tag = (view === 'standard') ? mode.toUpperCase() : (mode.toUpperCase() + ' / ' + view.toUpperCase());
      out.push({ label: tag, url: url });
    });
  });
  return out;
}

/**
 * Render the in-sidebar list of demo results. Each entry is a tiny row with
 * a label and a "▶ PLAY" button that calls playSegment() — which already
 * routes to the inline home/search/metrics player based on the active tab.
 *
 * Hidden by default; shown only after a demo run completes successfully.
 *
 * Author: Bloodawn (KheivenD)
 */
function _demoRenderResults(result) {
  const panel = document.getElementById('demo-result-panel');
  const list  = document.getElementById('demo-result-list');
  if (!panel || !list) return;

  const items = _demoCollectPlayables(result);
  if (!items.length) {
    list.innerHTML = '<div style="font-family:var(--mono);font-size:0.6rem;color:var(--text-dim);">No playable output found.</div>';
    panel.style.display = '';
    return;
  }

  let html = '';
  items.forEach(function(it) {
    // decode for the label fallback so we can show a filename if needed
    const safeUrl   = it.url.replace(/'/g, "\\'");
    const safeLabel = it.label.replace(/'/g, "\\'");
    html += '<div style="display:flex;align-items:center;gap:0.4rem;font-family:var(--mono);font-size:0.6rem;">' +
              '<span style="flex:1;color:var(--text);">' + it.label + '</span>' +
              '<button class="btn-play-sm" onclick="_demoPlayResult(\'' + safeUrl + '\',\'' + safeLabel + '\')">&#9654; PLAY</button>' +
            '</div>';
  });
  list.innerHTML = html;
  panel.style.display = '';
}

/** Clear and hide the demo-result-panel (X button on the panel header). */
function _demoClearResults() {
  const panel = document.getElementById('demo-result-panel');
  const list  = document.getElementById('demo-result-list');
  if (panel) panel.style.display = 'none';
  if (list)  list.innerHTML = '';
}

/**
 * Play a demo output URL inline. Routes through playSegment() so the player
 * lands on whichever tab the user is currently viewing (HOME by default,
 * since the demo controls live in the home sidebar).
 *
 * Author: Bloodawn (KheivenD)
 */
function _demoPlayResult(url, label) {
  // playSegment() expects (url, path). The "path" is just used as the
  // human-readable label, so passing the demo label is fine here.
  if (typeof playSegment === 'function') {
    playSegment(url, label || url);
  } else {
    // Defensive fallback: shouldn't happen in the shipped GUI, but means
    // the demo result still works even if playSegment() is renamed/removed.
    window.open(url, '_blank');
  }
}

function _demoNotifyDone(result) {
  const modesRan = result.modes || Object.keys(result.videos || {});
  const modeStr  = modesRan.map(function(m) { return m.toUpperCase(); }).join(' + ');
  const dir      = result.dir || '';

  // Build the in-sidebar results panel so the operator has a permanent list
  // of every rendered video for this run, with one-click inline playback.
  // This is the core of ROADMAP 5.3 — Cody's "watching the output still
  // required opening a file locally" complaint from the April 22 demo.
  // Author: Bloodawn (KheivenD)
  try { _demoRenderResults(result); } catch (e) { console.warn('demo result render failed', e); }

  // Pick the first playable URL — split-screen if multiple modes were run,
  // otherwise the first per-mode standard view. This drives the "Watch Now"
  // action so the operator never has to dig through the file system.
  let watchUrl = result.split_screen || '';
  let watchLabel = 'Demo split-screen';
  if (!watchUrl && result.videos) {
    const order = Object.keys(result.videos).sort();
    for (const m of order) {
      const views = result.videos[m] || {};
      const v = views.standard || Object.values(views).find(Boolean);
      if (v) { watchUrl = v; watchLabel = m.toUpperCase() + ' demo'; break; }
    }
  }

  // Figure out the folder to open — pull from split_screen path or first video
  let folderPath = '';
  if (result.split_screen) {
    const p = decodeURIComponent(result.split_screen.replace('/api/media?path=', ''));
    folderPath = p.replace(/[\\/][^\\/]+$/, '');  // strip filename
  } else if (result.videos) {
    for (const views of Object.values(result.videos)) {
      for (const url of Object.values(views)) {
        if (url) {
          const p = decodeURIComponent(url.replace('/api/media?path=', ''));
          folderPath = p.replace(/[\\/][^\\/]+$/, '');
          break;
        }
      }
      if (folderPath) break;
    }
  }

  const actions = [];
  if (watchUrl) {
    actions.push({ label: '▶ Watch Now', fn: function() { _demoPlayResult(watchUrl, watchLabel); } });
  }
  if (folderPath) {
    actions.push({ label: 'Open Folder', fn: function() { openFolder(folderPath); } });
  }
  actions.push({ label: 'Dismiss', fn: function() {} });

  pushNotif(
    'DEMO COMPLETE',
    modeStr + ' — render finished' + (dir ? '\n' + dir : ''),
    'success',
    actions,
    0  // no auto-dismiss — user must click
  );
}

// Stub: no tab to navigate to anymore, keep function alive for any legacy calls
function showDemoPanel() {}
function closeDemoPanel() { _demoHideProgress(); }
function renderDemoResult(result) { _demoNotifyDone(result); }
function loadDemoVideo() {}

// ── Demo comparison videos in SEARCH tab ─────────────────────
async function loadSearchDemoVideos() {
  const body  = document.getElementById('search-demo-body');
  const count = document.getElementById('search-demo-count');
  if (!body) return;
  try {
    const res  = await fetch('/api/demo/history');
    if (!res.ok) { body.innerHTML = '<div style="font-family:var(--mono);font-size:0.65rem;color:var(--text-dim);padding:0.5rem 0;">Could not load demo runs.</div>'; return; }
    const runs = await res.json();

    if (!runs.length) {
      body.innerHTML = '<div style="font-family:var(--mono);font-size:0.65rem;color:var(--text-dim);padding:0.5rem 0;">No demo runs found. Run a demo from the sidebar to generate comparison videos.</div>';
      if (count) count.textContent = '';
      return;
    }

    // Flatten all videos from all runs into a list
    const allVids = [];
    runs.forEach(r => {
      const date = r.ts ? new Date(r.ts * 1000).toLocaleString() : '—';
      if (r.split_screen) {
        allVids.push({ label: 'Split Screen', run: r.dir, date, url: r.split_screen, modes: r.modes });
      }
      for (const [mode, views] of Object.entries(r.videos || {})) {
        for (const [view, url] of Object.entries(views || {})) {
          if (url) allVids.push({ label: `${mode.toUpperCase()} / ${view}`, run: r.dir, date, url, modes: r.modes });
        }
      }
    });

    if (count) count.textContent = allVids.length + ' video' + (allVids.length !== 1 ? 's' : '') + ' in ' + runs.length + ' run' + (runs.length !== 1 ? 's' : '');

    let html = '<table class="demo-history-table" style="width:100%;">';
    html += '<thead><tr><th>Run</th><th>Modes</th><th>Video</th><th>Date</th><th></th></tr></thead><tbody>';
    allVids.forEach(v => {
      html += `<tr>
        <td style="color:var(--text-dim);font-size:0.6rem;">${v.run}</td>
        <td>${(v.modes || []).map(m => m.toUpperCase()).join(', ')}</td>
        <td style="color:var(--teal);">${v.label}</td>
        <td style="color:var(--text-dim);font-size:0.6rem;">${v.date}</td>
        <td><button class="btn-play-sm" onclick="playSearchDemoVid(${JSON.stringify(v.url)})">▶ PLAY</button></td>
      </tr>`;
    });
    html += '</tbody></table>';
    body.innerHTML = html;
  } catch(e) {
    body.innerHTML = '<div style="font-family:var(--mono);font-size:0.65rem;color:var(--text-dim);padding:0.5rem 0;">[!] Error loading demo videos: ' + e.message + '</div>';
  }
}

function playSearchDemoVid(url) {
  const wrap  = document.getElementById('search-preview-wrap');
  const video = document.getElementById('search-preview-video');
  if (!wrap || !video) return;
  wrap.style.display = '';
  video.src = url;
  video.load();
  video.play().catch(() => {});
  wrap.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

// ── Demo history (stubs — history UI removed, notifications used instead) ──
async function loadDemoHistory() { /* no-op: history shown via notifications */ }
function _loadHistoryRun(idx) {
  const runs = window._demoHistoryRuns || [];
  const r = runs[idx];
  if (r) renderDemoResult(r);
}

// ── Archive Search Panel ──────────────────────────────────────
const _COLOR_HEX = {
  red:'#e05252', orange:'#e07840', yellow:'#d4b830', green:'#4caf6e',
  cyan:'#1fd4c8', blue:'#4a90e2', purple:'#9b6bc4',
  white:'#e8e8e8', black:'#444', gray:'#888',
};

// ── Encryption Manager panel ────────────────────────────────────

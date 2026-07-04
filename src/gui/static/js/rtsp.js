/*
 * src/gui/static/js/rtsp.js
 *
 * SVCS dashboard - rtsp module. Carved verbatim from the former single
 * inline <script> in index.html (TASK 1.5). Loaded as a classic script in
 * original execution order, so behavior is identical; all functions stay
 * global (reachable from inline on* handlers and the other modules).
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - JS split).
 */
function _rtspApplyState(d) {
  const badge       = document.getElementById('rtsp-server-badge');
  const dlSection   = document.getElementById('rtsp-dl-section');
  const btnDl       = document.getElementById('btn-rtsp-dl');
  const dlBarWrap   = document.getElementById('rtsp-dl-bar-wrap');
  const dlBar       = document.getElementById('rtsp-dl-bar');
  const dlLabel     = document.getElementById('rtsp-dl-label');
  const btnStart    = document.getElementById('btn-rtsp-start');
  const btnStop     = document.getElementById('btn-rtsp-stop');
  const serverMsg   = document.getElementById('rtsp-server-msg');
  const btnPush     = document.getElementById('btn-rtsp-push');
  const btnStopPush = document.getElementById('btn-rtsp-stop-push');
  const pushMsg     = document.getElementById('rtsp-push-msg');
  const urlBox      = document.getElementById('rtsp-url-box');
  const urlText     = document.getElementById('rtsp-url-text');

  // ── download section ──────────────────────────────────────
  if (d.binary_present) {
    dlSection.style.display = 'none';
    btnStart.disabled = false;
  } else if (d.downloading) {
    btnDl.disabled = true;
    dlBarWrap.style.display = 'block';
    const prog = d.download_progress || '';
    if (prog === 'extracting') {
      dlBar.style.width = '95%';
      dlLabel.textContent = 'Extracting…';
    } else if (prog === 'done') {
      dlBar.style.width = '100%';
      dlLabel.textContent = 'Done';
    } else if (prog.endsWith('%')) {
      dlBar.style.width = prog;
      dlLabel.textContent = `Downloading ${prog}`;
    }
  } else if (d.download_error) {
    dlLabel.textContent = '[!] ' + d.download_error;
    dlLabel.style.color = 'var(--red)';
    dlBarWrap.style.display = 'block';
    btnDl.disabled = false;
  }

  // ── server badge ──────────────────────────────────────────
  if (d.server_running) {
    badge.textContent = '● RUNNING';
    badge.style.color = 'var(--green)';
  } else if (d.binary_present) {
    badge.textContent = '○ STOPPED';
    badge.style.color = 'var(--text-dim)';
  } else {
    badge.textContent = '(not installed)';
    badge.style.color = 'var(--text-dim)';
  }

  // ── start/stop buttons ────────────────────────────────────
  btnStart.disabled = !d.binary_present || d.server_running;
  btnStart.style.opacity = btnStart.disabled ? '0.4' : '1';
  btnStop.disabled  = !d.server_running;
  btnStop.style.opacity = btnStop.disabled ? '0.4' : '1';

  if (d.server_error) {
    serverMsg.textContent = '[!] ' + d.server_error;
    serverMsg.style.color = 'var(--red)';
  } else if (d.server_running) {
    serverMsg.textContent = '● Server running on rtsp://localhost:8554/';
    serverMsg.style.color = 'var(--green)';
  } else {
    serverMsg.textContent = '';
  }

  // ── push buttons ──────────────────────────────────────────
  btnPush.disabled     = !d.server_running || d.pushing;
  btnPush.style.opacity     = btnPush.disabled ? '0.4' : '1';
  btnStopPush.disabled = !d.pushing;
  btnStopPush.style.opacity = btnStopPush.disabled ? '0.4' : '1';

  if (d.pushing) {
    const short = (d.push_source || '').split(/[\\/]/).pop();
    pushMsg.textContent = `● Pushing: ${short} → /${d.push_stream || 'live'}`;
    pushMsg.style.color = 'var(--green)';
  } else {
    pushMsg.textContent = '';
  }

  // ── RTSP URL box ──────────────────────────────────────────
  if (d.rtsp_url) {
    urlBox.style.display = 'block';
    urlText.textContent = d.rtsp_url;
  } else if (d.server_running) {
    urlBox.style.display = 'block';
    urlText.textContent = 'rtsp://localhost:8554/live';
  } else {
    urlBox.style.display = 'none';
  }
}

async function _rtspRefresh() {
  try {
    const r = await fetch('/api/rtsp/status');
    if (!r.ok) return;
    _rtspApplyState(await r.json());
  } catch (_) {}
}

async function rtspDownload() {
  document.getElementById('btn-rtsp-dl').disabled = true;
  document.getElementById('rtsp-dl-bar-wrap').style.display = 'block';
  document.getElementById('rtsp-dl-label').textContent = 'Starting download…';
  document.getElementById('rtsp-dl-label').style.color = 'var(--text-dim)';
  try {
    const r = await fetch('/api/rtsp/download', { method: 'POST' });
    const d = await r.json();
    if (d.error) {
      document.getElementById('rtsp-dl-label').textContent = '[!] ' + d.error;
      document.getElementById('rtsp-dl-label').style.color = 'var(--red)';
      document.getElementById('btn-rtsp-dl').disabled = false;
      return;
    }
    // Poll status every second until download is done
    if (_rtspPollTimer) clearInterval(_rtspPollTimer);
    _rtspPollTimer = setInterval(async () => {
      await _rtspRefresh();
      const st = await (await fetch('/api/rtsp/status')).json();
      if (!st.downloading) clearInterval(_rtspPollTimer);
    }, 1000);
  } catch (e) {
    document.getElementById('rtsp-dl-label').textContent = '[!] ' + e.message;
    document.getElementById('btn-rtsp-dl').disabled = false;
  }
}

async function rtspStart() {
  document.getElementById('btn-rtsp-start').disabled = true;
  document.getElementById('rtsp-server-msg').textContent = 'Starting…';
  document.getElementById('rtsp-server-msg').style.color = 'var(--text-dim)';
  try {
    const r = await fetch('/api/rtsp/start', { method: 'POST' });
    const d = await r.json();
    if (d.error) {
      document.getElementById('rtsp-server-msg').textContent = '[!] ' + d.error;
      document.getElementById('rtsp-server-msg').style.color = 'var(--red)';
      document.getElementById('btn-rtsp-start').disabled = false;
    } else {
      await _rtspRefresh();
      if (!_rtspPollTimer) _rtspPollTimer = setInterval(_rtspRefresh, 3000);
    }
  } catch (e) {
    document.getElementById('rtsp-server-msg').textContent = '[!] ' + e.message;
    document.getElementById('btn-rtsp-start').disabled = false;
  }
}

async function rtspStop() {
  await fetch('/api/rtsp/stop', { method: 'POST' });
  if (_rtspPollTimer) { clearInterval(_rtspPollTimer); _rtspPollTimer = null; }
  await _rtspRefresh();
}

async function rtspBrowse() {
  try {
    const r = await fetch('/api/browse');
    const d = await r.json();
    if (d.path) document.getElementById('rtsp-push-path').value = d.path;
  } catch (_) {}
}

async function rtspPush() {
  const path   = document.getElementById('rtsp-push-path').value.trim();
  const stream = document.getElementById('rtsp-stream-name').value.trim() || 'live';
  if (!path) {
    document.getElementById('rtsp-push-msg').textContent = '[!] Enter a video file path first.';
    document.getElementById('rtsp-push-msg').style.color = 'var(--red)';
    return;
  }
  document.getElementById('btn-rtsp-push').disabled = true;
  document.getElementById('rtsp-push-msg').textContent = 'Starting FFmpeg push…';
  document.getElementById('rtsp-push-msg').style.color = 'var(--text-dim)';
  try {
    const r = await fetch('/api/rtsp/push', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ video_path: path, stream_name: stream }),
    });
    const d = await r.json();
    if (d.error) {
      document.getElementById('rtsp-push-msg').textContent = '[!] ' + d.error;
      document.getElementById('rtsp-push-msg').style.color = 'var(--red)';
      document.getElementById('btn-rtsp-push').disabled = false;
    } else {
      // Auto-fill the HLS input with the new RTSP URL
      document.getElementById('hls-input').value = d.rtsp_url;
      await _rtspRefresh();
    }
  } catch (e) {
    document.getElementById('rtsp-push-msg').textContent = '[!] ' + e.message;
    document.getElementById('btn-rtsp-push').disabled = false;
  }
}

async function rtspStopPush() {
  await fetch('/api/rtsp/stop_push', { method: 'POST' });
  await _rtspRefresh();
}

function rtspCopyUrl() {
  const url = document.getElementById('rtsp-url-text').textContent.trim();
  if (url) {
    document.getElementById('hls-input').value = url;
    // Scroll the sidebar to the HLS section so the user sees it filled in
    document.querySelector('[summary="Live Stream (HLS)"]')?.closest('details')?.setAttribute('open', '');
  }
}

// Initial RTSP state load on page open. Skipped in the field (offline) build,
// where the RTSP server routes are not registered (R4 Phase 4).
window.addEventListener('DOMContentLoaded', () => {
  if (window.SVCS_SERVER_FEATURES === false) return;
  _rtspRefresh();
});

// Auto-detect Google Drive and set as default output on page load
window.addEventListener('DOMContentLoaded', () => { _initGDriveOutput(); });

// ── Home tab resizable vertical divider ──────────────────────
// Drag handle between the video / controls area and Recent
// Recordings. Writes inline height onto #home-recordings; the
// flex parent (#tab-home) stretches the upper area to fill the
// rest. Persisted to localStorage so the user's chosen split
// survives reloads.
// Author: Bloodawn (KheivenD), 2026-05-04 (home divider).
(function _initHomeVSplit() {
  document.addEventListener('DOMContentLoaded', () => {
    const split = document.getElementById('home-vsplit');
    const recs  = document.getElementById('home-recordings');
    const tab   = document.getElementById('tab-home');
    if (!split || !recs || !tab) return;

    const apply = (h) => {
      // Clamp: at least one row fits, at most ~70% of the tab height
      const tabH = tab.getBoundingClientRect().height;
      const min = 80;
      const max = Math.max(min + 1, Math.round(tabH * 0.7));
      const clamped = Math.max(min, Math.min(max, h));
      recs.style.flex = '0 0 ' + clamped + 'px';
      recs.style.maxHeight = '';  // override the default 340px so JS can grow it
      // Inner scroll wrapper should match the new height (less header)
      const scroll = document.getElementById('home-rec-scroll');
      if (scroll) scroll.style.maxHeight = (clamped - 36) + 'px';
    };

    // Restore saved height on load (clamp narrow values away)
    try {
      const saved = parseInt(localStorage.getItem('svcs.home.recHeight') || '0', 10);
      if (saved && saved >= 80) apply(saved);
    } catch (_) { /* ignore */ }

    let dragging = false;
    let startY   = 0;
    let startH   = 0;

    split.addEventListener('mousedown', (e) => {
      dragging = true;
      startY   = e.clientY;
      startH   = recs.getBoundingClientRect().height;
      split.classList.add('dragging');
      document.body.classList.add('home-resizing');
      e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      // Mouse moving DOWN shrinks the recordings panel, so subtract
      const dy = e.clientY - startY;
      apply(startH - dy);
    });

    document.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      split.classList.remove('dragging');
      document.body.classList.remove('home-resizing');
      try {
        const h = Math.round(recs.getBoundingClientRect().height);
        localStorage.setItem('svcs.home.recHeight', String(h));
      } catch (_) { /* ignore */ }
    });

    // Double-click resets
    split.addEventListener('dblclick', () => {
      recs.style.flex = '';
      recs.style.maxHeight = '';
      const scroll = document.getElementById('home-rec-scroll');
      if (scroll) scroll.style.maxHeight = '340px';
      try { localStorage.removeItem('svcs.home.recHeight'); } catch(_) {}
    });
  });
})();

// ── Metrics resizable divider ─────────────────────────────────
// Manual JS drag handle between #metrics-left (table) and
// #metrics-right (detail card). Writes inline style.width on
// mousemove, persists the user's choice to localStorage so the
// preference survives page reloads.
//
// Why not CSS resize:horizontal? Because flex-grow on
// .metrics-right would silently override it whenever the layout
// recalculated. This handler is bulletproof.
//
// Author: Bloodawn (KheivenD), 2026-05-03 (metrics divider fix).
(function _initMetricsDivider() {
  document.addEventListener('DOMContentLoaded', () => {
    const divider = document.getElementById('metrics-divider');
    const left    = document.getElementById('metrics-left');
    const panes   = document.querySelector('.metrics-panes');
    if (!divider || !left || !panes) return;

    // Restore saved width on first load - clamped both directions so a
    // tiny saved value (which produces the "jumbled metrics" look the
    // user reported) gets normalized to something readable. We require
    // at least 400px now; if the saved value is narrower we wipe it.
    // Author: Bloodawn (KheivenD), 2026-05-03 (jumbled-metrics guard).
    try {
      const saved = parseInt(localStorage.getItem('svcs.metrics.leftWidth') || '0', 10);
      const MIN_USABLE = 400;
      if (saved && saved >= MIN_USABLE) {
        const max = Math.min(saved, panes.getBoundingClientRect().width - 320);
        left.style.width = Math.max(360, max) + 'px';
      } else if (saved && saved < MIN_USABLE) {
        // Saved value is uselessly narrow - drop it and use the default
        localStorage.removeItem('svcs.metrics.leftWidth');
      }
    } catch (_) { /* localStorage may be blocked */ }

    let dragging = false;
    let startX   = 0;
    let startW   = 0;

    divider.addEventListener('mousedown', (e) => {
      dragging = true;
      startX   = e.clientX;
      startW   = left.getBoundingClientRect().width;
      divider.classList.add('dragging');
      document.body.classList.add('metrics-resizing');
      e.preventDefault();
    });

    document.addEventListener('mousemove', (e) => {
      if (!dragging) return;
      const panesRect = panes.getBoundingClientRect();
      const dx = e.clientX - startX;
      // Clamp: 360px..(panes width - 320px for the right detail card)
      const min = 360;
      const max = Math.max(min + 1, panesRect.width - 320);
      const newW = Math.max(min, Math.min(max, startW + dx));
      left.style.width = newW + 'px';
    });

    document.addEventListener('mouseup', () => {
      if (!dragging) return;
      dragging = false;
      divider.classList.remove('dragging');
      document.body.classList.remove('metrics-resizing');
      try {
        const w = Math.round(left.getBoundingClientRect().width);
        localStorage.setItem('svcs.metrics.leftWidth', String(w));
      } catch (_) { /* ignore */ }
    });

    // Double-click to reset to 60% default
    divider.addEventListener('dblclick', () => {
      left.style.width = '60%';
      try { localStorage.removeItem('svcs.metrics.leftWidth'); } catch(_) {}
    });
  });
})();

// ── Help modal ────────────────────────────────────────────────

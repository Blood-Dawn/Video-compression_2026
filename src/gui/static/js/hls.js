/*
 * src/gui/static/js/hls.js
 *
 * SVCS dashboard — hls module. Carved verbatim from the former single
 * inline <script> in index.html (TASK 1.5). Loaded as a classic script in
 * original execution order, so behavior is identical; all functions stay
 * global (reachable from inline on* handlers and the other modules).
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — JS split).
 */
async function hlsStart() {
  const input   = document.getElementById('hls-input').value.trim();
  const camId   = document.getElementById('hls-camera-id').value.trim() || 'cam_00';
  const outDir  = document.getElementById('output-dir').value.trim();
  const sideMsg = document.getElementById('hls-sidebar-msg');
  const msgEl   = document.getElementById('hls-status-msg');

  // Read mode from the pipeline config dropdown so the corner overlay matches
  const modeRaw   = document.getElementById('mode-select').value || 'mode0';
  const modeLabel = modeRaw === 'mode0' ? 'MODE 0' : modeRaw === 'mode1' ? 'MODE 1' : modeRaw.toUpperCase();

  if (!input) {
    sideMsg.textContent = '[!] Enter an input source first.';
    sideMsg.style.color = 'var(--red)';
    return;
  }

  sideMsg.textContent = 'Starting annotated HLS stream…';
  sideMsg.style.color = 'var(--text-dim)';
  msgEl.textContent = '';
  document.getElementById('btn-hls-start').disabled = true;

  try {
    const res  = await fetch('/api/hls/start', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ input_source: input, camera_id: camId, output_dir: outDir, mode: modeLabel }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      sideMsg.textContent = '[!] ' + (data.error || 'Failed to start stream.');
      sideMsg.style.color = 'var(--red)';
      document.getElementById('btn-hls-start').disabled = false;
      return;
    }

    // Show the main panel and update its title
    document.getElementById('hls-panel-title').textContent = 'Live Stream: ' + camId;
    document.getElementById('hls-section').style.display = 'block';
    sideMsg.textContent = '● Streaming (see main panel)';
    sideMsg.style.color = 'var(--green)';
    msgEl.textContent = 'Waiting for first segment…';
    msgEl.style.color = 'var(--text-dim)';

    document.getElementById('btn-hls-stop').disabled = false;
    document.getElementById('btn-hls-stop').style.opacity = '1';

    // Retry attaching the player until the playlist is ready (max 10 retries, 2s each)
    _attachHlsPlayer(data.playlist_url, camId, 0);

    // Poll HLS status every 1s for the first 15s (catches fast connection failures),
    // then drop to 3s once the stream is established.
    _hlsStatusTimer = setInterval(_hlsPollStatus, 1000);
    setTimeout(() => {
      clearInterval(_hlsStatusTimer);
      // Only restart slow polling if the stream is still running
      fetch('/api/hls/status').then(r => r.json()).then(d => {
        if (d.running) _hlsStatusTimer = setInterval(_hlsPollStatus, 3000);
      }).catch(() => {});
    }, 15000);
  } catch (e) {
    sideMsg.textContent = '[!] Network error: ' + e.message;
    sideMsg.style.color = 'var(--red)';
    document.getElementById('btn-hls-start').disabled = false;
  }
}

async function _attachHlsPlayer(playlistUrl, camId, attempt) {
  const MAX_RETRIES = 10;   // 10 × 2s = 20s total wait budget
  const RETRY_MS   = 2000;
  const video  = document.getElementById('hls-video');
  const msgEl  = document.getElementById('hls-status-msg');

  // Probe the playlist. If it does not exist yet, wait and retry.
  try {
    const probe = await fetch(playlistUrl);
    if (!probe.ok) {
      if (attempt < MAX_RETRIES) {
        msgEl.textContent = `Waiting for FFmpeg… (attempt ${attempt + 1}/${MAX_RETRIES})`;
        setTimeout(() => _attachHlsPlayer(playlistUrl, camId, attempt + 1), RETRY_MS);
        return;
      }
      msgEl.textContent = '[!] Playlist not ready after ' + MAX_RETRIES + ' retries. Check FFmpeg logs.';
      msgEl.style.color = 'var(--red)';
      return;
    }
  } catch (e) {
    if (attempt < MAX_RETRIES) {
      setTimeout(() => _attachHlsPlayer(playlistUrl, camId, attempt + 1), RETRY_MS);
      return;
    }
    msgEl.textContent = '[!] Could not reach stream: ' + e.message;
    msgEl.style.color = 'var(--red)';
    return;
  }

  // Playlist is ready. Attach hls.js.
  if (Hls.isSupported()) {
    if (_hlsInstance) { _hlsInstance.destroy(); }
    _hlsInstance = new Hls({ enableWorker: false });
    _hlsInstance.loadSource(playlistUrl);
    _hlsInstance.attachMedia(video);
    _hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
      video.play().catch(() => {});
      msgEl.textContent = '● LIVE: ' + camId;
      msgEl.style.color = 'var(--green)';
      _pollHlsLatency(camId, 0);
    });
    _hlsInstance.on(Hls.Events.ERROR, (_evt, data) => {
      if (data.fatal) {
        msgEl.textContent = '[!] HLS error: ' + data.type;
        msgEl.style.color = 'var(--red)';
      }
    });
  } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
    // Safari native HLS
    video.src = playlistUrl;
    video.play().catch(() => {});
    msgEl.textContent = '● LIVE (native HLS): ' + camId;
    msgEl.style.color = 'var(--green)';
  } else {
    msgEl.textContent = '[!] HLS not supported in this browser.';
  }
}

async function hlsStop() {
  clearInterval(_hlsStatusTimer);
  // Cut the latency poller so it doesn't keep updating the banner after the
  // stream is gone (ROADMAP 5.1). Author: Bloodawn (KheivenD)
  if (typeof _stopHlsLatencyPoller === 'function') _stopHlsLatencyPoller();
  if (_hlsInstance) { _hlsInstance.destroy(); _hlsInstance = null; }

  const video   = document.getElementById('hls-video');
  const msgEl   = document.getElementById('hls-status-msg');
  const sideMsg = document.getElementById('hls-sidebar-msg');
  video.pause();
  video.src = '';

  msgEl.style.color = 'var(--text-dim)';
  msgEl.textContent = 'Stopping…';

  try {
    await fetch('/api/hls/stop', { method: 'POST' });
    document.getElementById('hls-section').style.display = 'none';
    sideMsg.textContent = 'Stream stopped.';
    sideMsg.style.color = 'var(--text-dim)';
  } catch (e) {
    msgEl.textContent = '[!] Stop request failed: ' + e.message;
  }

  document.getElementById('btn-hls-start').disabled = false;
  document.getElementById('btn-hls-stop').disabled = true;
  document.getElementById('btn-hls-stop').style.opacity = '0.4';
}

async function _hlsPollStatus() {
  try {
    const res  = await fetch('/api/hls/status');
    const data = await res.json();

    if (!data.running) {
      clearInterval(_hlsStatusTimer);
      const msgEl   = document.getElementById('hls-status-msg');
      const sideMsg = document.getElementById('hls-sidebar-msg');
      const btnStart = document.getElementById('btn-hls-start');
      const btnStop  = document.getElementById('btn-hls-stop');

      if (data.error) {
        // Distinguish connection failures from mid-stream crashes
        const isConnErr = data.error.toLowerCase().includes('connect')
                       || data.error.toLowerCase().includes('unreachable')
                       || data.error.toLowerCase().includes('could not open');
        const prefix = isConnErr ? ' Connection failed' : ' Stream stopped';
        msgEl.textContent = prefix + ': ' + data.error.slice(0, 160);
        msgEl.style.color = 'var(--red)';
        sideMsg.textContent = prefix;
        sideMsg.style.color = 'var(--red)';
      } else {
        // Stopped cleanly (e.g. file ended, user hit stop)
        msgEl.textContent = 'Stream ended.';
        msgEl.style.color = 'var(--text-dim)';
        sideMsg.textContent = '◼ Stopped';
        sideMsg.style.color = 'var(--text-dim)';
      }

      btnStart.disabled = false;
      btnStop.disabled  = true;
      btnStop.style.opacity = '0.4';
    }
  } catch (_) { /* ignore network blips */ }
}

// ── Local RTSP Server (MediaMTX) ─────────────────────────────
let _rtspPollTimer = null;


/*
 * src/gui/static/js/status.js
 *
 * SVCS dashboard - status module. Carved verbatim from the former single
 * inline <script> in index.html (TASK 1.5). Loaded as a classic script in
 * original execution order, so behavior is identical; all functions stay
 * global (reachable from inline on* handlers and the other modules).
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - JS split).
 */
function startPolling() {
  if (statusInterval) clearInterval(statusInterval);
  if (storageInterval) clearInterval(storageInterval);
  if (segmentsInterval) clearInterval(segmentsInterval);
  if (jobsInterval) clearInterval(jobsInterval);
  statusInterval  = setInterval(pollStatus,   1200);
  storageInterval = setInterval(pollStorage,  5000);
  segmentsInterval = setInterval(loadSegments, 8000);
  // Recent-jobs panel (R4 Phase 1): cheap read of a small JSON; a slow
  // refresh also picks up auto-compress batches finished by the daemon.
  jobsInterval = setInterval(loadRecentJobs, 15000);
  loadRecentJobs();
}

let _statusPollInFlight = false;

async function pollStatus() {
  // One poll at a time: a slow response arriving after a newer one would
  // replay a stale running=true snapshot and re-fire the stopped transition
  // (reopening the completion modal the user already dismissed).
  if (_statusPollInFlight) return;
  _statusPollInFlight = true;
  try {
    const res  = await fetch('/api/status');
    const data = await res.json();

    document.getElementById('stat-frames').textContent   = fmtNum(data.frame_count || 0);
    document.getElementById('stat-segments').textContent = fmtNum(data.segment_count || 0);
    document.getElementById('stat-fps').textContent      = data.fps != null ? data.fps : ' - ';

    // Notify when a new segment is saved
    const curSeg = data.segment_count || 0;
    if (data.running && _lastSegmentCount > 0 && curSeg > _lastSegmentCount) {
      const delta = curSeg - _lastSegmentCount;
      pushNotif('SEGMENT SAVED', `${delta} new compressed clip${delta > 1 ? 's' : ''} written - ${curSeg} total`, 'success', null, 4000);
    }
    _lastSegmentCount = curSeg;

    const fill  = document.getElementById('progress-fill');
    const pctEl = document.getElementById('progress-pct');

    if (data.running) {
      const pct = data.progress_pct;   // null for live/unknown-length sources
      if (pct != null) {
        // Known-length file: show real percentage
        fill.classList.remove('running');
        fill.style.width = pct + '%';
        pctEl.textContent = pct.toFixed(1) + '%';
      } else {
        // Live stream / unknown length: animated shimmer
        fill.classList.add('running');
        fill.style.width = '100%';
        pctEl.textContent = '';
      }
    } else {
      fill.classList.remove('running');
      fill.style.width = '0%';
      pctEl.textContent = '';
    }

    // Human-readable status message
    const statusEl = document.getElementById('status-message');
    if (statusEl) {
      const friendly = _friendlyStatus(data);
      statusEl.textContent = friendly.text;
      statusEl.className = 'status-message' + (friendly.cls ? ' ' + friendly.cls : '');
    }

    if (data.running !== lastRunning) {
      setPipelineRunning(data.running);
      const wasRunning = lastRunning;
      lastRunning = data.running;
      if (!data.running && data.error) {
        showError('Pipeline error: ' + data.error);
      }
      if (!data.running && wasRunning) {
        // R4 Phase 1 (NN/g): a long run just ended - show the explicit,
        // user-dismissed completion summary and refresh the job record.
        maybeShowLatestJobSummary('pipeline');
        loadRecentJobs();
      }
    }

    // sync mode chips from last running config
    if (data.config && data.config.mode) {
      document.querySelectorAll('.mode-chip[data-mode]').forEach(c => {
        c.classList.toggle('active', c.dataset.mode === data.config.mode);
      });
      document.getElementById('chip-enhance').classList.toggle('active', !!data.config.enhance);
      document.getElementById('chip-encrypt').classList.toggle('active', !!data.config.encrypt);
    }

    // ── HOME hero strip ────────────────────────────────────────
    _updateHeroStrip(data);

  } catch(e) { /* ignore network errors during poll */ }
  finally { _statusPollInFlight = false; }
}

function _updateHeroStrip(data) {
  const dot   = document.getElementById('home-hero-dot');
  const label = document.getElementById('home-hero-label');
  const camChip  = document.getElementById('hero-chip-camera');
  const modeChip = document.getElementById('hero-chip-mode');
  const encChip  = document.getElementById('hero-chip-enc');
  const upChip   = document.getElementById('hero-chip-uptime');
  if (!dot) return;

  if (data.running) {
    dot.className   = 'home-hero-dot running';
    label.textContent = 'LIVE';
    label.style.color = 'var(--green)';
  } else if (data.error) {
    dot.className   = 'home-hero-dot error';
    label.textContent = 'ERROR';
    label.style.color = 'var(--red)';
  } else {
    dot.className   = 'home-hero-dot';
    label.textContent = 'OFFLINE';
    label.style.color = 'var(--text-dim)';
  }

  if (data.config) {
    const src = data.config.input_source || data.config.camera_id || ' - ';
    camChip.textContent = src.split(/[\/]/).pop() || src;
    camChip.classList.toggle('lit', data.running);
    const mode = data.config.mode || ' - ';
    modeChip.textContent = 'Mode: ' + mode;
    const encrypted = !!(data.config.encrypt);
    encChip.style.display = encrypted ? '' : 'none';
  }

  // Uptime from segment count (rough)
  const segs = data.segment_count || 0;
  if (data.running && segs > 0) {
    upChip.textContent = segs + ' seg' + (segs !== 1 ? 's' : '') + ' written';
  } else if (data.running) {
    upChip.textContent = 'Starting…';
  } else {
    upChip.textContent = 'Uptime:  - ';
  }
}

let lastRunning = false;
let _lastSegmentCount = 0;

async function pollStorage() {
  try {
    const res  = await fetch('/api/storage');
    const data = await res.json();
    if (data.available) {
      const mb = data.total_mb;
      _lastStorageMb = mb;
      if (mb >= 1000) {
        document.getElementById('stat-storage').textContent = (mb/1024).toFixed(2);
        document.getElementById('stat-storage-unit').textContent = 'GB used';
      } else {
        document.getElementById('stat-storage').textContent = mb > 0 ? mb.toFixed(1) : ' - ';
        document.getElementById('stat-storage-unit').textContent = 'MB used';
      }
      // Compression ratio from segments table
      _updateCompressionRatio();
    }
  } catch(e) {}
}

function _updateCompressionRatio() {
  const ratioEl = document.getElementById('stat-savings-ratio');
  if (!ratioEl || !_segmentData.length) return;
  // Estimate raw size from segment metadata and compare to actual file sizes
  let totalRawMb = 0;
  let totalCompMb = 0;
  _segmentData.forEach(s => {
    const rawMb = (s.duration_s * (s.width || 640) * (s.height || 480) * 3 * (s.fps || 25)) / 1e6;
    const compMb = (s.file_size_kb || 0) / 1024;
    totalRawMb += rawMb;
    totalCompMb += compMb;
  });
  if (totalCompMb > 0 && totalRawMb > 0) {
    const ratio = totalRawMb / totalCompMb;
    _lastCompressionRatio = ratio.toFixed(1);
    ratioEl.textContent = `~${_lastCompressionRatio}× smaller than raw`;
    ratioEl.style.color = ratio >= 10 ? 'var(--green)' : ratio >= 3 ? 'var(--teal)' : 'var(--text-dim)';
  }
}

// Store segment data for tooltip lookups (keyed by row index)
let _segmentData = [];


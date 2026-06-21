/*
 * src/gui/static/js/metrics.js
 *
 * SVCS dashboard - metrics module. Carved verbatim from the former single
 * inline <script> in index.html (TASK 1.5). Loaded as a classic script in
 * original execution order, so behavior is identical; all functions stay
 * global (reachable from inline on* handlers and the other modules).
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - JS split).
 */
function openHelp() {
  document.getElementById('help-overlay').classList.add('open');
  document.body.style.overflow = 'hidden';
}
function closeHelp() {
  document.getElementById('help-overlay').classList.remove('open');
  document.body.style.overflow = '';
}
function _helpOverlayClick(evt) {
  if (evt.target === document.getElementById('help-overlay')) closeHelp();
}
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') closeHelp();
});

// ── GPU detection ─────────────────────────────────────────────
async function checkGpu() {
  const msgEl = document.getElementById('gpu-status-msg');
  msgEl.textContent = 'Checking GPU…';
  msgEl.style.color = 'var(--text-dim)';
  try {
    const res  = await fetch('/api/gpu_info');
    const data = await res.json();
    const sel  = document.getElementById('enhance-device');

    // Auto-select best device
    if (data.available && sel.value === 'auto') {
      // leave as auto, just display info
    }

    const color = data.will_work ? 'var(--green)' : data.available ? 'var(--amber)' : 'var(--text-dim)';
    msgEl.style.color = color;
    let msg = data.note || '';
    if (data.mobile_note) msg += ' ' + data.mobile_note;
    if (data.torch_version) msg += ` (torch ${data.torch_version})`;
    msgEl.textContent = msg || 'No GPU detected. CPU will be used.';
  } catch(e) {
    msgEl.textContent = 'GPU check failed: ' + e;
    msgEl.style.color = 'var(--red)';
  }
}

// ── LAN IP display ────────────────────────────────────────────
async function _loadLanUrl() {
  try {
    const res  = await fetch('/api/network_info');
    const data = await res.json();
    const wrap = document.getElementById('lan-url-wrap');
    const link = document.getElementById('lan-url-link');
    if (data.url) {
      link.textContent = data.url;
      link.href = data.url;
      wrap.style.display = 'flex';
    }
  } catch(e) {}
}
function _copyLanUrl() {
  const link = document.getElementById('lan-url-link');
  if (!link) return;
  navigator.clipboard.writeText(link.href).then(() => {
    const orig = link.title;
    link.style.color = 'var(--green)';
    setTimeout(() => { link.style.color = ''; }, 1200);
  }).catch(() => {});
}

// ── Hardware / power metrics ──────────────────────────────────
let _hwInterval = null;

async function pollHardware() {
  try {
    const res  = await fetch('/api/system_metrics');
    const d    = await res.json();
    if (!d.available) return;
    _applyHardwareMetrics(d);
  } catch(_) {}
}

function _applyHardwareMetrics(d) {
  // ── HOME strip ─────────────────────────────────────────────
  const cpuPct = d.cpu_pct ?? 0;
  const ramPct = d.ram_pct ?? 0;
  const batPct = d.battery_pct;

  _hwSet('hw-cpu-fill',  'width', cpuPct + '%');
  _hwSet('hw-ram-fill',  'width', ramPct + '%');
  _hwSet('hw-cpu-val',   'text',  cpuPct.toFixed(0) + '%');
  _hwSet('hw-ram-val',   'text',  (d.ram_used_mb ?? 0) >= 1024
    ? ((d.ram_used_mb / 1024).toFixed(1) + ' GB')
    : ((d.ram_used_mb ?? 0) + ' MB'));

  // Color cpu bar by load
  const cpuFill = document.getElementById('hw-cpu-fill');
  if (cpuFill) cpuFill.style.background = cpuPct > 80 ? 'var(--red)' : cpuPct > 50 ? 'var(--amber)' : 'var(--green)';

  if (batPct !== null && batPct !== undefined) {
    const batCell = document.getElementById('hw-battery-cell');
    if (batCell) batCell.style.display = '';
    _hwSet('hw-bat-fill', 'width', batPct + '%');
    const plugged = d.battery_plugged;
    _hwSet('hw-bat-val', 'text', batPct.toFixed(0) + '%' + (plugged ? ' CHG' : ''));
    const batFill = document.getElementById('hw-bat-fill');
    if (batFill) batFill.style.background = batPct < 20 ? 'var(--red)' : batPct < 50 ? 'var(--amber)' : 'var(--green)';
  }

  if (d.storage_mb_hr !== null && d.storage_mb_hr !== undefined) {
    _hwSet('hw-rate-val', 'text', d.storage_mb_hr.toFixed(1) + ' MB/hr');
  }

  if (d.estimated_hrs !== null && d.estimated_hrs !== undefined) {
    const etaCell = document.getElementById('hw-eta-cell');
    if (etaCell) etaCell.style.display = '';
    const hrs = d.estimated_hrs;
    const hStr = hrs >= 1 ? hrs.toFixed(1) + ' hr' : Math.round(hrs * 60) + ' min';
    _hwSet('hw-eta-val', 'text', hStr + ' left');
  }

  // ── METRICS per-mode bars ──────────────────────────────────
  const avgs = d.mode_avgs || {};
  const modeLabels = {
    mode0: 'Mode 0 · Live Surveillance',
    mode1: 'Mode 1 · Event Recording',
    mode2: 'Mode 2 · Smart Compress',
    mode3: 'Mode 3 · Object Only',
  };
  const rows = document.getElementById('mode-cpu-rows');
  // If a row is currently selected in the metrics table, leave the
  // CPU card alone - it's showing per-clip stats for that recording
  // and the global poller would clobber them on every tick.
  // Author: Bloodawn (KheivenD), 2026-05-03 (per-clip CPU stats).
  if (rows && !_cpuCardLockedToSelection) {
    const keys = Object.keys(modeLabels);
    const anyData = keys.some(k => avgs[k]);
    if (anyData) {
      const maxAvg = Math.max(1, ...keys.map(k => avgs[k]?.avg || 0));
      rows.innerHTML = keys.map(k => {
        const a = avgs[k];
        if (!a) return `<div class="metrics-library-row" style="opacity:0.4"><span>${modeLabels[k]}</span><span style="font-size:0.65rem;color:var(--text-dim);">no data yet</span></div>`;
        const pct = (a.avg / Math.max(maxAvg, 100)) * 100;
        const color = a.avg > 70 ? 'var(--red)' : a.avg > 40 ? 'var(--amber)' : 'var(--green)';
        // FIX 2: samples loaded from a prior install are flagged historical so
        // they are not mistaken for this install's measurements.
        const histTag = a.historical
          ? ` <span style="color:var(--text-dim);font-style:italic;">(previous runs)</span>` : '';
        return `<div style="margin:0.25rem 0;">
          <div style="display:flex;justify-content:space-between;font-size:0.68rem;margin-bottom:2px;">
            <span style="color:var(--text-dim);">${modeLabels[k]}</span>
            <span style="font-family:var(--mono);color:${color};">${a.avg}% avg · ${a.n} samples${histTag}</span>
          </div>
          <div style="height:5px;background:var(--surface3);border-radius:2px;overflow:hidden;">
            <div style="height:100%;width:${pct.toFixed(1)}%;background:${color};border-radius:2px;transition:width 0.6s;"></div>
          </div>
        </div>`;
      }).join('');
    }
  }

  // Storage rate in metrics card
  if (d.storage_mb_hr !== null && d.storage_mb_hr !== undefined) {
    _hwSet('mode-cpu-rate', 'text', d.storage_mb_hr.toFixed(1) + ' MB / hr');
  }

  // Battery in metrics card
  if (batPct !== null && batPct !== undefined && !d.battery_plugged) {
    const brow = document.getElementById('mode-cpu-battery-row');
    if (brow) brow.style.display = '';
    if (d.estimated_hrs !== null && d.estimated_hrs !== undefined) {
      const hrs = d.estimated_hrs;
      const hStr = hrs >= 1 ? hrs.toFixed(1) + ' hr remaining' : Math.round(hrs * 60) + ' min remaining';
      _hwSet('mode-cpu-battery', 'text', hStr);
    }
  }
}

function _hwSet(id, prop, val) {
  const el = document.getElementById(id);
  if (!el) return;
  if (prop === 'text') el.textContent = val;
  else if (prop === 'width') el.style.width = val;
}

// ── Tab navigation ───────────────────────────────────────────
function switchTab(name) {
  // Update nav buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.toggle('active', btn.dataset.tab === name);
  });
  // Show/hide pages
  document.querySelectorAll('.tab-page').forEach(page => {
    page.classList.toggle('active', page.id === 'tab-' + name);
  });
  // When switching to metrics, ensure library summary is current
  if (name === 'metrics') _updateLibrarySummary(_segmentData);
  // Auto-compress tab: start/stop its status poll + log stream on show/hide.
  if (name === 'autocompress' && typeof acOnTabShow === 'function') acOnTabShow();
  if (name !== 'autocompress' && typeof acOnTabHide === 'function') acOnTabHide();
  // Demo is now in the sidebar, not a tab - nothing to lazy-load here
  // Demo comparison videos are in a collapsed <details> - only load on expand
}

// ── Metrics table filter ──────────────────────────────────────
function filterMetricsTable() {
  const query   = (document.getElementById('met-filter-cam')?.value || '').toLowerCase();
  const typeSel = document.getElementById('met-filter-type')?.value || '';
  const encOnly = document.getElementById('met-filter-enc')?.checked || false;

  document.querySelectorAll('#segments-tbody tr.seg-row').forEach((row, idx) => {
    const s = _segmentData[idx];
    if (!s) { row.style.display = ''; return; }
    let show = true;
    if (query && !JSON.stringify(s).toLowerCase().includes(query)) show = false;
    if (typeSel && s.object_type !== typeSel) show = false;
    if (encOnly && !(s.file_path && s.file_path.endsWith('.enc'))) show = false;
    row.style.display = show ? '' : 'none';
  });
}

// ── Boot ─────────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded', () => {
  startSSE();
  startPolling();
  // Sweep dangling rows (file gone from disk) BEFORE first table
  // render so old test recordings don't flash up and then disappear.
  // Author: Bloodawn (KheivenD), 2026-05-03 (cleanup of dead rows).
  _cleanupMissingSegments().then(() => loadSegments());
  pollStorage();
  pollStatus();
  pollHardware();
  if (_hwInterval) clearInterval(_hwInterval);
  _hwInterval = setInterval(pollHardware, 2000);
  // Evaluate initial input source so Camera ID field visibility is correct
  const initSrc = document.getElementById('input-source').value;
  _onInputSourceChange(initSrc);
  // Initialize sensitivity slider display
  _onSensitivityChange(document.getElementById('sensitivity-slider').value);
  // Initialize segment length slider display
  _onSegLenChange(document.getElementById('segment-seconds-slider').value);
  // Load LAN IP for teammate sharing
  _loadLanUrl();

});

// ─────────────────────────────────────────────────────────────────────
// AI Plate Reader - post-process SR + ALPR on a saved segment
//
// Wires the inline preview "READ PLATES" button (and any future caller)
// to /api/enhance/plates. Pulls the absolute file path back out of the
// player's /api/media?path=... URL, fires the request, and renders the
// candidate-plate list inside #plate-modal so the operator can see
// confidence, vote count, and verdict for each read.
//
// Author: Bloodawn (KheivenD), 2026-05-02
// ─────────────────────────────────────────────────────────────────────


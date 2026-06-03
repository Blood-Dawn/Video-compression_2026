/*
 * src/gui/static/js/encryption.js
 *
 * SVCS dashboard — encryption module. Carved verbatim from the former single
 * inline <script> in index.html (TASK 1.5). Loaded as a classic script in
 * original execution order, so behavior is identical; all functions stay
 * global (reachable from inline on* handlers and the other modules).
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — JS split).
 */
function toggleEncPanel() {
  switchTab('encrypt');
}

function encMethodChanged() {
  const pw = document.querySelector('input[name="enc-method"]:checked').value === 'password';
  document.getElementById('enc-password-group').style.display = pw ? '' : 'none';
  document.getElementById('enc-keyfile-group').style.display  = pw ? 'none' : '';
}

function decMethodChanged() {
  const pw = document.querySelector('input[name="dec-method"]:checked').value === 'password';
  document.getElementById('dec-password-group').style.display = pw ? '' : 'none';
  document.getElementById('dec-keyfile-group').style.display  = pw ? 'none' : '';
}

async function browseEncFile() {
  try {
    const res = await fetch('/api/browse');
    const data = await res.json();
    if (data.path) document.getElementById('enc-src-path').value = data.path;
  } catch(e) { /* ignore */ }
}

async function browseDecFile() {
  try {
    const res = await fetch('/api/browse');
    const data = await res.json();
    if (data.path) document.getElementById('dec-src-path').value = data.path;
  } catch(e) { /* ignore */ }
}

// Called by per-row decrypt button — pre-fills the encrypt tab and switches to it
function promptEncryptSegment(filePath) {
  document.getElementById('enc-src-path').value = filePath;
  const pwRadio = document.querySelector('input[name="enc-method"][value="password"]');
  if (pwRadio) { pwRadio.checked = true; encMethodChanged(); }
  document.getElementById('enc-password').value = '';
  document.getElementById('enc-encrypt-status').textContent = '';
  switchTab('encrypt');
  setTimeout(() => document.getElementById('enc-password').focus(), 120);
}

async function doEncryptFile() {
  const filePath = document.getElementById('enc-src-path').value.trim();
  const method   = document.querySelector('input[name="enc-method"]:checked').value;
  const password = method === 'password' ? (document.getElementById('enc-password').value.trim() || null) : null;
  const keyFile  = method === 'keyfile'  ? (document.getElementById('enc-keyfile-path').value.trim() || null) : null;
  const statusEl = document.getElementById('enc-encrypt-status');

  if (!filePath) { statusEl.textContent = 'No file selected.'; statusEl.style.color = 'var(--red)'; return; }
  if (!password && !keyFile) { statusEl.textContent = 'Enter a password or key file path.'; statusEl.style.color = 'var(--red)'; return; }

  statusEl.textContent = 'Encrypting…';
  statusEl.style.color = 'var(--text-dim)';

  try {
    const res = await fetch('/api/encrypt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath, password, key_file: keyFile }),
    });
    const data = await res.json();
    if (!res.ok) {
      statusEl.textContent = '[!] ' + (data.error || 'Failed');
      statusEl.style.color = 'var(--red)';
      return;
    }
    // 2026-05-03: encrypt now COPIES to <src_dir>/Encrypted/<name>.enc
    // and leaves the original mp4 untouched. Surface the new path so
    // the user can see where it landed without digging through OneDrive.
    // Author: Bloodawn (KheivenD).
    statusEl.textContent = `Encrypted (${data.size_kb} KB) → ${(data.enc_path || '').split(/[\\/]/).pop()}`;
    statusEl.style.color = 'var(--green)';
    pushNotif('ENCRYPTED', `File locked (${data.size_kb} KB).`, 'success', null, 5000);
    document.getElementById('enc-password').value = '';
    // Refresh segments so the new .enc row appears in the table
    loadSegments();
  } catch(e) {
    statusEl.textContent = '[!] Network error: ' + e.message;
    statusEl.style.color = 'var(--red)';
  }
}

async function doDecryptPanel() {
  const filePath = document.getElementById('dec-src-path').value.trim();
  const method   = document.querySelector('input[name="dec-method"]:checked').value;
  const password = method === 'password' ? (document.getElementById('dec-password').value.trim() || null) : null;
  const keyFile  = method === 'keyfile'  ? (document.getElementById('dec-keyfile-path').value.trim() || null) : null;
  const statusEl = document.getElementById('enc-decrypt-status');

  if (!filePath) { statusEl.textContent = 'No file selected.'; statusEl.style.color = 'var(--red)'; return; }
  if (!password && !keyFile) { statusEl.textContent = 'Enter a password or key file path.'; statusEl.style.color = 'var(--red)'; return; }

  statusEl.textContent = 'Decrypting…';
  statusEl.style.color = 'var(--text-dim)';

  try {
    const res = await fetch('/api/decrypt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: filePath, password, key_file: keyFile }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      statusEl.textContent = '[!] ' + (err.error || 'Failed');
      statusEl.style.color = 'var(--red)';
      return;
    }

    // Saved path comes back in a custom header — stream the bytes for
    // playback AND tell the user where the persistent copy landed.
    // Author: Bloodawn (KheivenD), 2026-05-03 (decrypt destination).
    const savedPath = res.headers.get('X-Decrypted-Path') || '';
    const blob   = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    const savedBase = savedPath ? savedPath.split(/[\\/]/).pop() : '';
    statusEl.textContent = savedBase
      ? `Decrypted → ${savedBase} (saved to Decrypted/)`
      : 'Decrypted (playing)';
    statusEl.style.color = 'var(--green)';
    if (savedPath) {
      pushNotif('DECRYPTED',
        `Saved to: ${savedPath}`,
        'success', null, 8000);
    }
    // Switch to Metrics tab and play in the preview
    switchTab('metrics');
    playSegment(blobUrl, filePath + ' (decrypted)');

  } catch(e) {
    statusEl.textContent = '[!] Network error: ' + e.message;
    statusEl.style.color = 'var(--red)';
  }
}

function toggleArchivePanel() {
  switchTab('search');
}

function clearArchiveFilters() {
  ['arc-object-type','arc-color','arc-scene','arc-tod'].forEach(id => {
    document.getElementById(id).value = '';
  });
  ['arc-camera-id','arc-date-from','arc-date-to','arc-min-rois'].forEach(id => {
    document.getElementById(id).value = '';
  });
  document.getElementById('arc-enc-only').checked = false;
  _showArchiveStatus('Filters cleared. Press SEARCH to run a new query.');
}

function _showArchiveStatus(msg, isError) {
  const status = document.getElementById('archive-status');
  const table  = document.getElementById('archive-results-table');
  status.textContent = msg;
  status.style.color = isError ? 'var(--red)' : 'var(--text-dim)';
  status.style.display = 'block';
  table.style.display = 'none';
  document.getElementById('archive-result-count').textContent = '';
}

function _renderArchiveSegments(segments, showToast) {
  const status = document.getElementById('archive-status');
  const table  = document.getElementById('archive-results-table');
  const tbody  = document.getElementById('archive-tbody');
  const count  = document.getElementById('archive-result-count');

  if (!segments || !segments.length) {
    _showArchiveStatus('No segments match these filters.');
    if (showToast) pushNotif('SEARCH', 'No segments matched the current filters.', 'info', null, 4000);
    return;
  }
  const n = segments.length;
  count.textContent = n + ' result' + (n !== 1 ? 's' : '');
  status.style.display = 'none';
  table.style.display = 'table';
  if (showToast) pushNotif('SEARCH RESULTS', n + ' segment' + (n !== 1 ? 's' : '') + ' found.', 'success', null, 3500);

  // Mirror search results into a global so the hover-tooltip handler
  // (_onArchiveRowEnter) can look up the row's full record by index.
  // Same pattern as _segmentData on the metrics tab.
  // Author: Bloodawn (KheivenD), 2026-05-03 (search hover + mode col).
  _archiveSegmentData = segments;

  tbody.innerHTML = segments.map((s, idx) => {
    const isEnc = s.file_path && s.file_path.endsWith('.enc');
    const playBtn = isEnc
      ? `<button class="btn-play-sm btn-enc" onclick="event.stopPropagation();promptDecrypt('${jsAttr(s.file_path)}')">[ENC]</button>`
      : s.playable_url
        ? `<button class="btn-play-sm" onclick="event.stopPropagation();playSegment('${jsAttr(s.playable_url)}','${jsAttr(s.file_path)}')">▶</button>`
        : '—';

    // Type badge
    const typeLower = (s.object_type || 'unknown').toLowerCase();
    const typeCls = typeLower.includes('vehicle') && typeLower.includes('person') ? 'arc-badge-mixed'
      : typeLower.includes('vehicle') ? 'arc-badge-vehicle'
      : typeLower.includes('person')  ? 'arc-badge-person'
      : 'arc-badge-unknown';

    // Color dot
    const colorVal = s.dominant_color || '';
    const dotHex = _COLOR_HEX[colorVal] || '';
    const colorCell = colorVal
      ? `<span class="color-dot" style="background:${dotHex};"></span>${escHtml(colorVal)}`
      : '<span style="color:var(--text-dim)">—</span>';

    // Scene
    const sceneIcons = { highway:'HWY', intersection:'INT', parking:'PKG', street:'STR' };
    const sceneIcon = sceneIcons[s.scene_type] || '';
    const sceneCell = s.scene_type && s.scene_type !== 'unknown'
      ? `${sceneIcon} ${escHtml(s.scene_type)}`
      : '<span style="color:var(--text-dim)">—</span>';

    // Time of day
    const todIcons = { day:'DAY', night:'NGT', dusk_dawn:'DWN' };
    const todCell = s.time_of_day
      ? `${todIcons[s.time_of_day] || ''} ${escHtml(s.time_of_day)}`
      : '<span style="color:var(--text-dim)">—</span>';

    const sizeMb = (s.file_size_kb / 1024).toFixed(1);

    // Friendly camera label (filename when camera_id is the legacy default)
    const camDisplay = (!s.camera_id || s.camera_id === 'cam_00')
      ? _segDisplayName(s)
      : s.camera_id;

    // Mode column — same derivation as the metrics table
    const mode = _segMode(s);
    const modeColor = mode === '—' ? 'var(--text-dim)'
      : mode.startsWith('Split') ? 'var(--purple)'
      : mode === 'Mode 0' ? 'var(--text)'
      : mode === 'Mode 1' ? 'var(--teal)'
      : mode === 'Mode 2' ? 'var(--yellow)'
      : 'var(--green)';

    return `<tr class="seg-row" data-seg-idx="${idx}"
      onmouseenter="_onArchiveRowEnter(event, ${idx})"
      onmousemove="_moveTooltip(event)"
      onmouseleave="_hideTooltip()"
      style="cursor:default;">
      <td style="color:var(--text-dim)">${formatTimestamp(s.timestamp)}</td>
      <td title="${escHtml(s.camera_id)}">${escHtml(camDisplay)}</td>
      <td style="color:${modeColor};font-weight:bold;letter-spacing:0.04em;">${escHtml(mode)}</td>
      <td><span class="arc-badge ${typeCls}">${escHtml(s.object_type || 'unknown')}</span></td>
      <td style="font-size:0.63rem">${colorCell}</td>
      <td style="font-size:0.63rem">${sceneCell}</td>
      <td style="font-size:0.63rem">${todCell}</td>
      <td style="color:var(--amber);text-align:center">${s.roi_count}</td>
      <td style="color:var(--text-dim)">${s.duration_s}s</td>
      <td style="color:var(--text-dim)">${sizeMb} MB</td>
      <td style="color:var(--teal);text-align:center">${(s.vehicle_count > 0) ? s.vehicle_count : (typeLower.includes('vehicle') ? '<span title="Detected (legacy segment)" style="opacity:0.6">+</span>' : '<span style="color:var(--text-dim)">—</span>')}</td>
      <td style="color:var(--yellow);text-align:center">${(s.person_count > 0) ? s.person_count : (typeLower.includes('person') ? '<span title="Detected (legacy segment)" style="opacity:0.6">+</span>' : '<span style="color:var(--text-dim)">—</span>')}</td>
      <td>${playBtn}</td>
    </tr>`;
  }).join('');
}

// Global mirror of /api/segments/search results so the hover-tooltip
// handler can look up full records by row index. Same pattern the
// metrics tab uses with `_segmentData`.
let _archiveSegmentData = [];

// Hover handler for archive rows — feeds the same tooltip element the
// metrics table uses so the experience is identical across tabs.
// Author: Bloodawn (KheivenD), 2026-05-03 (search hover).
function _onArchiveRowEnter(evt, idx) {
  const s = _archiveSegmentData[idx];
  if (s) _showSegTooltip(evt, s);
}

function _renderArchiveDaily(rows) {
  const status = document.getElementById('archive-status');
  const table  = document.getElementById('archive-results-table');
  const tbody  = document.getElementById('archive-tbody');
  const count  = document.getElementById('archive-result-count');

  if (!rows || !rows.length) {
    _showArchiveStatus('No daily data yet.');
    return;
  }
  count.textContent = `${rows.length} day${rows.length !== 1 ? 's' : ''}`;
  status.style.display = 'none';

  // Override thead for daily view (now 13 cols total — added Mode)
  table.querySelector('thead tr').innerHTML = `
    <th>Date</th><th>Camera</th><th>Total Size</th><th>Total Duration</th>
    <th colspan="9"></th>`;
  tbody.innerHTML = rows.map(r =>
    `<tr>
      <td style="color:var(--text-dim)">${escHtml(r.date)}</td>
      <td>${escHtml(r.camera_id)}</td>
      <td style="color:var(--teal)">${r.total_mb} MB</td>
      <td style="color:var(--text-dim)">${r.total_hours}h</td>
      <td colspan="9"></td>
    </tr>`
  ).join('');
  table.style.display = 'table';
}

async function runArchiveSearch() {
  const spin = document.getElementById('arc-searching');
  spin.style.display = 'inline';

  // Restore standard thead in case DAILY view changed it (13 cols now — Mode added)
  document.getElementById('archive-results-table').querySelector('thead tr').innerHTML = `
    <th>Timestamp</th><th>Camera</th>
    <th title="SVCS encoding mode: 0=all frames, 1=event-gated, 2=BG+patches, 3=object-only blackout">Mode</th>
    <th>Type</th><th>Color</th>
    <th>Scene</th><th>Time</th><th title="Total motion regions across all frames">Motion</th><th title="Clip length">Length</th><th>Size</th>
    <th>Vehicles</th><th>People</th><th>Play</th>`;

  const params = new URLSearchParams();
  const ot  = document.getElementById('arc-object-type').value;
  const col = document.getElementById('arc-color').value;
  const sc  = document.getElementById('arc-scene').value;
  const tod = document.getElementById('arc-tod').value;
  const cam = document.getElementById('arc-camera-id').value.trim();
  const df  = document.getElementById('arc-date-from').value;
  const dt  = document.getElementById('arc-date-to').value;
  const mr  = document.getElementById('arc-min-rois').value;
  const enc = document.getElementById('arc-enc-only').checked;

  if (ot)  params.set('object_type', ot);
  if (col) params.set('color', col);
  if (sc)  params.set('scene_type', sc);
  if (tod) params.set('time_of_day', tod);
  if (cam) params.set('camera_id', cam);
  if (df)  params.set('start_time', df.replace(/-/g,'') + 'T000000Z');
  if (dt)  params.set('end_time',   dt.replace(/-/g,'') + 'T235959Z');
  if (mr)  params.set('min_roi_count', mr);
  if (enc) params.set('encrypted_only', '1');

  try {
    const res  = await fetch('/api/segments?' + params);
    const data = await res.json();
    _renderArchiveSegments(data.segments, true);  // true = show toast
  } catch(e) {
    _showArchiveStatus('Error: ' + String(e), true);
  } finally {
    spin.style.display = 'none';
  }
}

async function loadArchiveBusiest() {
  const spin = document.getElementById('arc-searching');
  spin.style.display = 'inline';
  document.getElementById('archive-results-table').querySelector('thead tr').innerHTML = `
    <th>Timestamp</th><th>Camera</th><th>Type</th><th>Color</th>
    <th>Scene</th><th>Time</th><th title="Total motion regions across all frames">Motion</th><th title="Clip length">Length</th><th>Size</th>
    <th>Vehicles</th><th>People</th><th>Play</th>`;
  try {
    const res  = await fetch('/api/busiest?limit=50');
    const data = await res.json();
    _renderArchiveSegments(data.segments);
  } catch(e) {
    _showArchiveStatus('Error: ' + String(e), true);
  } finally {
    spin.style.display = 'none';
  }
}

async function loadArchiveDaily() {
  const spin = document.getElementById('arc-searching');
  spin.style.display = 'inline';
  try {
    const res  = await fetch('/api/daily_summary');
    const data = await res.json();
    _renderArchiveDaily(data.rows);
  } catch(e) {
    _showArchiveStatus('Error: ' + String(e), true);
  } finally {
    spin.style.display = 'none';
  }
}

// Keep old names alive so any inline onclick references still work
function runQuery()         { toggleArchivePanel(); setTimeout(runArchiveSearch, 100); }
function loadBusiest()      { toggleArchivePanel(); setTimeout(loadArchiveBusiest, 100); }
function loadDailySummary() { toggleArchivePanel(); setTimeout(loadArchiveDaily, 100); }

// ── UI state helpers ──────────────────────────────────────────

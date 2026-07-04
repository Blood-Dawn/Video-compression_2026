/*
 * src/gui/static/js/files.js
 *
 * SVCS dashboard - files module. Carved verbatim from the former single
 * inline <script> in index.html (TASK 1.5). Loaded as a classic script in
 * original execution order, so behavior is identical; all functions stay
 * global (reachable from inline on* handlers and the other modules).
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - JS split).
 */
async function loadSegments() {
  try {
    const res  = await fetch('/api/segments');
    const data = await res.json();
    const tbody = document.getElementById('segments-tbody');
    if (!data.segments || !data.segments.length) {
      // Empty state (R4 Phase 1, NN/g): explain what will appear and how to
      // make it appear, instead of a bare "no data" label.
      tbody.innerHTML = '<tr><td colspan="16" class="empty-state">No compressed segments yet. Pick a source in the sidebar and press START, or drop a file on the UPLOAD tab - finished segments appear here.</td></tr>';
      _updateLibrarySummary([]);
      _segmentData = [];
      return;
    }
    _segmentData = data.segments;
    _updateCompressionRatio();
    tbody.innerHTML = data.segments.map((s, idx) => {
      const ts = formatTimestamp(s.timestamp);
      const objType = escHtml(s.object_type || 'unknown');
      const isEnc = s.file_path && s.file_path.endsWith('.enc');
      const playBtn = isEnc
        ? `<button class="btn-play-sm btn-enc" title="Encrypted - click to decrypt &amp; play" onclick="promptDecrypt('${jsAttr(s.file_path)}')">[ENC]</button>`
        : s.playable_url
          ? `<button class="btn-play-sm" onclick="playSegment('${jsAttr(s.playable_url)}','${jsAttr(s.file_path)}')">▶</button>`
          : `<span style="color:var(--text-dim);font-size:0.6rem;"> - </span>`;
      const encBtn = isEnc
        ? `<span style="color:var(--yellow);font-size:0.6rem;" title="Already encrypted">[ENC]</span>`
        : s.file_path
          ? `<button class="btn-play-sm" style="color:var(--yellow);border-color:var(--yellow);" title="Encrypt this segment" onclick="promptEncryptSegment('${jsAttr(s.file_path)}')">[DEC]</button>`
          : `<span style="color:var(--text-dim);font-size:0.6rem;"> - </span>`;
      const compMb = s.file_size_kb / 1024;
      const sizeStr = compMb >= 1 ? `${compMb.toFixed(1)} MB` : `${s.file_size_kb} KB`;
      const qualityStr = s.sharpness_label
        ? escHtml(s.sharpness_label.split(' ')[0])
        : '<span style="color:var(--text-dim)"> - </span>';
      const qualityColor = s.sharpness_label
        ? (s.sharpness_label.includes('blurry') || s.sharpness_label.includes('240p') ? 'var(--red)'
          : s.sharpness_label.includes('480p') ? 'var(--yellow)'
          : 'var(--green)')
        : '';
      // ── New columns 2026-05-03 (UI cleanup pass): Color / Scene /
      //    Light / Cars / People - same data the SEARCH tab already had.
      //    Author: Bloodawn (KheivenD).
      const dash = '<span style="color:var(--text-dim)"> - </span>';
      const color = s.dominant_color
        ? `<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:${_colorSwatch(s.dominant_color)};margin-right:4px;vertical-align:middle;"></span>${escHtml(s.dominant_color)}`
        : dash;
      const scene = s.scene_type && s.scene_type !== 'unknown'
        ? `<span style="font-size:0.62rem;color:var(--teal);text-transform:uppercase;">${escHtml(s.scene_type.slice(0,3))}</span> ${escHtml(s.scene_type)}`
        : dash;
      const tod = s.time_of_day
        ? (s.time_of_day === 'night' ? '🌙 night' : s.time_of_day === 'day' ? '☀️ day' : '🌅 ' + escHtml(s.time_of_day))
        : dash;
      const carsStr   = s.vehicle_count > 0 ? s.vehicle_count : (s.target_detected && (s.object_type || '').includes('vehicle') ? '+' : dash);
      const peopleStr = s.person_count  > 0 ? s.person_count  : (s.target_detected && (s.object_type || '').includes('person')  ? '+' : dash);
      // Display name priority for the Cam column: prefer the camera_id
      // when it's something meaningful (auto-derived filename stem from
      // _autoCamera()), but if it's the legacy "cam_00" default fall
      // back to the output file's basename so the user can still tell
      // their recordings apart instead of seeing a wall of "cam_00".
      // Author: Bloodawn (KheivenD), 2026-05-03 (UI fix pass).
      const camDisplay = (!s.camera_id || s.camera_id === 'cam_00')
        ? _segDisplayName(s)
        : s.camera_id;
      // Flag rows where the underlying file is gone - play button will
      // be a " - " (no playable_url) and the segment isn't an .enc file.
      // Author: Bloodawn (KheivenD), 2026-05-03 (cleanup of dead rows).
      const isStale = !s.playable_url && !isEnc;
      const rowStyle = isStale
        ? 'opacity:0.55;'
        : '';
      const staleTag = isStale
        ? '<span style="color:var(--red);font-size:0.55rem;margin-left:0.3rem;" title="Source file is missing on disk">[missing]</span>'
        : '';
      // [X] button - hides this row from the dashboard. Files on disk
      // are not deleted; this just sets hidden=1 in the metadata DB.
      const hideBtn = s.file_path
        ? `<button class="btn-row-hide" title="Remove this row from the dashboard (file on disk is kept)" onclick="event.stopPropagation();_hideSegmentRow('${jsAttr(s.file_path)}')">×</button>`
        : `<span style="color:var(--text-dim);font-size:0.6rem;"> - </span>`;
      const mode = _segMode(s);
      const modeColor = mode === ' - ' ? 'var(--text-dim)'
        : mode.startsWith('Split') ? 'var(--purple)'
        : mode === 'Mode 0' ? 'var(--text)'
        : mode === 'Mode 1' ? 'var(--teal)'
        : mode === 'Mode 2' ? 'var(--yellow)'
        : 'var(--green)';
      return `<tr data-seg-idx="${idx}" class="seg-row" style="${rowStyle}" onmouseenter="_onSegRowEnter(event,${idx})" onmousemove="_moveTooltip(event)" onmouseleave="_hideTooltip()" onclick="_metricsRowClick(${idx})">
        <td>${ts}</td>
        <td title="${escHtml(s.camera_id)}">${escHtml(camDisplay)}${staleTag}</td>
        <td style="color:${modeColor};font-size:0.7rem;font-weight:bold;letter-spacing:0.04em;">${escHtml(mode)}</td>
        <td style="color:var(--teal)">${objType}</td>
        <td>${color}</td>
        <td style="font-size:0.7rem">${scene}</td>
        <td style="font-size:0.7rem">${tod}</td>
        <td>${s.roi_count}</td>
        <td style="font-weight:bold;color:${s.vehicle_count>0?'var(--teal)':'var(--text-dim)'};">${carsStr}</td>
        <td style="font-weight:bold;color:${s.person_count>0?'var(--yellow)':'var(--text-dim)'};">${peopleStr}</td>
        <td>${s.duration_s}s</td>
        <td>${sizeStr}</td>
        <td style="color:${qualityColor};font-size:0.72rem">${qualityStr}</td>
        <td>${playBtn}</td>
        <td>${encBtn}</td>
        <td>${hideBtn}</td>
      </tr>`;
    }).join('');
    _updateLibrarySummary(data.segments);
    _updateHomeRecent(data.segments);
  } catch(e) {}
}

function _updateHomeRecent(segments) {
  const tbody = document.getElementById('home-rec-tbody');
  const count = document.getElementById('home-rec-count');
  if (!tbody) return;
  // /api/segments returns rows in DESC timestamp order, so the array
  // is already newest-first. Was slice(0,8) - that capped the panel at
  // 8 rows and left the scroll bar with nothing to scroll past, which
  // looked broken when the user had 25+ recordings ("25 total" shown
  // up top but only 8 visible). Show ALL of them; the parent div has
  // overflow:auto so anything past the panel height scrolls naturally.
  // Author: Bloodawn (KheivenD), 2026-05-03 (home-recent scroll fix).
  const recent = segments;
  if (count) count.textContent = segments.length + ' total';
  if (!recent.length) {
    tbody.innerHTML = '<tr><td colspan="5" style="color:var(--text-dim);text-align:center;padding:0.75rem;font-family:var(--mono);font-size:0.65rem;">No recordings yet</td></tr>';
    return;
  }
  // Each row gets the same hover-tooltip handler the Metrics tab uses
  // (`_onSegRowEnter` + `_segmentData[idx]`). The idx we pass is the
  // *global* index in `_segmentData` because the recent slice mirrors
  // the head of that array - newest-first in both places.
  tbody.innerHTML = recent.map((s, idx) => {
    const isEnc = s.file_path && s.file_path.endsWith('.enc');
    const objIcon = s.object_type === 'vehicle' ? '' : s.object_type === 'person' ? '' : s.target_detected ? '' : '';
    const playBtn = isEnc
      ? `<button class="btn-play-sm btn-enc" title="Encrypted" onclick="promptDecrypt('${jsAttr(s.file_path)}')">[ENC]</button>`
      : s.playable_url
        ? `<button class="btn-play-sm" onclick="playSegment('${jsAttr(s.playable_url)}','${jsAttr(s.file_path)}')">▶</button>`
        : ' - ';
    const sizeMb = (s.file_size_kb / 1024);
    const camDisplay = (!s.camera_id || s.camera_id === 'cam_00')
      ? _segDisplayName(s)
      : s.camera_id;
    return `<tr class="seg-row" data-seg-idx="${idx}"
      onmouseenter="_onSegRowEnter(event,${idx})"
      onmousemove="_moveTooltip(event)"
      onmouseleave="_hideTooltip()"
      style="border-bottom:1px solid rgba(42,68,102,0.4);cursor:pointer;">
      <td style="padding:0.25rem 0.5rem;color:var(--text-dim);white-space:nowrap;">${formatTimestamp(s.timestamp)}</td>
      <td style="padding:0.25rem 0.5rem;font-family:var(--mono);font-size:0.65rem;" title="${escHtml(s.camera_id)}">${escHtml(camDisplay)}</td>
      <td style="padding:0.25rem 0.5rem;">${objIcon} ${escHtml(s.object_type || ' - ')}</td>
      <td style="padding:0.25rem 0.5rem;text-align:right;font-family:var(--mono);font-size:0.65rem;">${sizeMb >= 1 ? sizeMb.toFixed(1) + ' MB' : s.file_size_kb + ' KB'}</td>
      <td style="padding:0.25rem 0.5rem;text-align:center;">${playBtn}</td>
    </tr>`;
  }).join('');
}

// ── Metrics library summary ────────────────────────────────────
function _updateLibrarySummary(segments) {
  const n = segments.length;
  const totalKb = segments.reduce((a, s) => a + (s.file_size_kb || 0), 0);
  const totalMb = totalKb / 1024;
  const totalDur = segments.reduce((a, s) => a + (s.duration_s || 0), 0);
  const encCount = segments.filter(s => s.file_path && s.file_path.endsWith('.enc')).length;

  // Estimate raw size for savings calculation
  let rawMb = 0;
  segments.forEach(s => {
    rawMb += (s.duration_s * (s.width || 640) * (s.height || 480) * 3 * (s.fps || 25)) / 1e6;
  });
  const savedMb = rawMb > 0 ? rawMb - totalMb : 0;

  const set = (id, val) => { const el = document.getElementById(id); if (el) el.textContent = val; };
  set('mlib-segments', n > 0 ? n : ' - ');
  set('mlib-size', totalMb >= 1 ? totalMb.toFixed(1) + ' MB' : (totalKb > 0 ? totalKb.toFixed(0) + ' KB' : ' - '));
  set('mlib-saved', savedMb > 1 ? '~' + savedMb.toFixed(0) + ' MB' : (n > 0 ? '<1 MB' : ' - '));
  set('mlib-avg-dur', n > 0 ? (totalDur / n).toFixed(1) + 's avg' : ' - ');
  set('mlib-enc', encCount > 0 ? encCount + ' / ' + n : (n > 0 ? 'None' : ' - '));
}

// ── Metrics row click ──────────────────────────────────────────
let _selectedSegIdx = null;

function _metricsRowClick(idx) {
  const s = _segmentData[idx];
  if (!s) return;
  _selectedSegIdx = idx;
  // Highlight row
  document.querySelectorAll('#segments-tbody tr.seg-row').forEach((r, i) => {
    r.classList.toggle('row-selected', i === idx);
  });
  showMetricsDetail(s);
}

function showMetricsDetail(s) {
  const noSel = document.getElementById('metrics-no-selection');
  const detail = document.getElementById('metrics-detail');
  if (!noSel || !detail) return;

  noSel.style.display = 'none';
  detail.style.display = 'flex';

  // Video
  const video = document.getElementById('metrics-video');
  if (video) {
    if (s.file_path && s.file_path.endsWith('.enc')) {
      video.poster = '';
      video.removeAttribute('src');
      video.load();
    } else if (s.playable_url) {
      video.src = s.playable_url;
      video.load();
      video.play().catch(() => {});
    } else {
      video.removeAttribute('src');
      video.load();
    }
  }

  // Encryption badge
  const encBadge = document.getElementById('metrics-enc-badge');
  if (encBadge) {
    encBadge.style.display = (s.file_path && s.file_path.endsWith('.enc')) ? '' : 'none';
  }

  // Encrypt button
  const encBtn = document.getElementById('metrics-enc-btn');
  if (encBtn) {
    if (s.file_path && s.file_path.endsWith('.enc')) {
      encBtn.textContent = 'ENCRYPTED';
      encBtn.disabled = true;
      encBtn.style.opacity = '0.5';
    } else {
      encBtn.textContent = 'ENCRYPT THIS FILE';
      encBtn.disabled = !s.file_path;
      encBtn.style.opacity = s.file_path ? '1' : '0.4';
      encBtn.onclick = () => promptEncryptSegment(s.file_path);
    }
  }

  // Meta grid
  const grid = document.getElementById('metrics-meta-grid');
  if (!grid) return;
  const isEnc = s.file_path && s.file_path.endsWith('.enc');
  const compMb = (s.file_size_kb || 0) / 1024;
  const rawMb = (s.duration_s * (s.width || 640) * (s.height || 480) * 3 * (s.fps || 25)) / 1e6;
  const ratio = rawMb > 0 && compMb > 0 ? (rawMb / compMb).toFixed(1) + '×' : ' - ';
  // Detail card "Camera" should match the table cell - show the friendly
  // filename-derived name when camera_id is the legacy default.
  // Author: Bloodawn (KheivenD), 2026-05-03 (UI fix pass).
  const camDisplay = (!s.camera_id || s.camera_id === 'cam_00')
    ? _segDisplayName(s)
    : s.camera_id;
  const rows = [
    ['Camera', camDisplay || ' - '],
    ['Mode', _segMode(s)],
    ['Timestamp', formatTimestamp(s.timestamp)],
    ['Duration', s.duration_s + 's'],
    ['Object Type', s.object_type || 'unknown'],
    ['Target', s.target_detected ? '▲ YES' : '○ no'],
    ['Motion Regions', s.roi_count],
    ['Size', compMb >= 1 ? compMb.toFixed(2) + ' MB' : (s.file_size_kb || 0) + ' KB'],
    ['Raw (est)', rawMb > 0 ? rawMb.toFixed(1) + ' MB' : ' - '],
    ['Compression', ratio],
    ['Quality', s.sharpness_label || ' - '],
    ['Encrypted', isEnc ? 'Yes (AES-256)' : 'No'],
  ];
  grid.innerHTML = rows.map(([k, v]) =>
    `<div class="metrics-meta-row"><span class="metrics-meta-key">${k}</span><span class="metrics-meta-val">${escHtml(String(v))}</span></div>`
  ).join('');

  // Per-clip CPU stats - replaces the old global "CPU Usage by Mode"
  // bars with stats for THIS recording only. Reads cpu_avg/max/min/etc
  // off the segment row, which the backend filled in from the run's
  // cpu_stats.json. Sticky across reloads (file-backed on disk).
  // Author: Bloodawn (KheivenD), 2026-05-03 (per-clip CPU stats).
  _renderClipCpuStats(s);
}

function _renderClipCpuStats(s) {
  const rowsEl = document.getElementById('mode-cpu-rows');
  const labelEl = document.getElementById('mode-cpu-clip-label');
  if (!rowsEl) return;
  // Suppress the global hardware poller from overwriting this card
  // while a row is selected.
  _cpuCardLockedToSelection = true;

  const hasStats = s && (s.cpu_avg !== null && s.cpu_avg !== undefined);
  if (!hasStats) {
    if (labelEl) labelEl.textContent = '· no stats for this clip';
    rowsEl.innerHTML = `
      <div style="color:var(--text-dim);font-size:0.68rem;padding:0.4rem 0;line-height:1.5;">
        No CPU sample for this recording. Stats are captured only for
        runs started after the per-clip tracking change (2026-05-03).
        Re-run a demo with this clip's source to populate it.
      </div>`;
    return;
  }

  const mode = _segMode(s);
  const camLabel = (!s.camera_id || s.camera_id === 'cam_00') ? _segDisplayName(s) : s.camera_id;
  if (labelEl) labelEl.textContent = `· ${mode}  ·  ${camLabel}`;

  const avg = s.cpu_avg;
  const max = s.cpu_max != null ? s.cpu_max : avg;
  const mn  = s.cpu_min != null ? s.cpu_min : avg;
  const n   = s.cpu_samples || 0;
  const dur = s.cpu_duration_s != null ? s.cpu_duration_s : 0;
  const color = avg > 70 ? 'var(--red)' : avg > 40 ? 'var(--amber)' : 'var(--green)';
  const pct = Math.max(2, Math.min(100, avg));

  rowsEl.innerHTML = `
    <div style="margin:0.25rem 0;">
      <div style="display:flex;justify-content:space-between;font-size:0.7rem;margin-bottom:4px;">
        <span style="color:var(--text-dim);">Average CPU</span>
        <span style="font-family:var(--mono);color:${color};font-weight:bold;">${avg.toFixed(1)}%</span>
      </div>
      <div style="height:6px;background:var(--surface3);border-radius:2px;overflow:hidden;">
        <div style="height:100%;width:${pct.toFixed(1)}%;background:${color};border-radius:2px;transition:width 0.6s;"></div>
      </div>
    </div>
    <div class="metrics-library-row" style="font-size:0.65rem;padding-top:0.35rem;">
      <span>Peak / Low</span>
      <span style="font-family:var(--mono);">
        <span style="color:var(--red);">${max.toFixed(1)}%</span>
        /
        <span style="color:var(--green);">${mn.toFixed(1)}%</span>
      </span>
    </div>
    <div class="metrics-library-row" style="font-size:0.65rem;">
      <span>Samples · Duration</span>
      <span style="font-family:var(--mono);color:var(--text-dim);">${n} @ 1s · ${dur.toFixed(1)}s</span>
    </div>
  `;
}

// When the selected row is cleared (e.g., on refresh) we want the
// global hardware poller to take over again.
let _cpuCardLockedToSelection = false;

function _metricsEncryptBtn() {
  const s = _segmentData[_selectedSegIdx];
  if (s && s.file_path) promptEncryptSegment(s.file_path);
}

function _onSegRowEnter(evt, idx) {
  const s = _segmentData[idx];
  if (s) _showSegTooltip(evt, s);
}

// ── Segment inline playback ────────────────────────────────────
function playSegment(url, path) {
  const activeTab = document.querySelector('.tab-page.active');
  const tabId = activeTab ? activeTab.id : '';

  // HOME tab: play inline in the home preview player
  if (tabId === 'tab-home') {
    const wrap  = document.getElementById('home-preview-wrap');
    const video = document.getElementById('home-preview-video');
    const label = document.getElementById('home-preview-label');
    if (wrap && video) {
      video.src = url;
      video.load();
      video.play().catch(() => {});
      label.textContent = path.split(/[\\/]/).pop() || path;
      wrap.style.display = '';
      wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      return;
    }
  }

  // SEARCH tab: play inline in the search preview player
  if (tabId === 'tab-search') {
    const wrap  = document.getElementById('search-preview-wrap');
    const video = document.getElementById('search-preview-video');
    const label = document.getElementById('search-preview-label');
    if (wrap && video) {
      video.src = url;
      video.load();
      video.play().catch(() => {});
      label.textContent = path.split(/[\\/]/).pop() || path;
      wrap.style.display = '';
      wrap.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      return;
    }
  }

  // METRICS tab default: route through the right-side detail panel.
  // The old #seg-preview floating player below the table was removed
  // 2026-05-03 because it was a duplicate of #metrics-video and caused
  // two videos to play at the same time.
  // Author: Bloodawn (KheivenD).
  const video = document.getElementById('metrics-video');
  const noSel = document.getElementById('metrics-no-selection');
  const detail = document.getElementById('metrics-detail');
  if (video) {
    video.src = url;
    video.load();
    video.play().catch(() => {});
  }
  if (noSel)  noSel.style.display  = 'none';
  if (detail) {
    detail.style.display = '';
    detail.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
  }
}

function closeHomePreview() {
  const wrap  = document.getElementById('home-preview-wrap');
  const video = document.getElementById('home-preview-video');
  if (wrap) wrap.style.display = 'none';
  if (video) { video.src = ''; video.load(); }
}

function closeSearchPreview() {
  const wrap  = document.getElementById('search-preview-wrap');
  const video = document.getElementById('search-preview-video');
  if (wrap) wrap.style.display = 'none';
  if (video) { video.src = ''; video.load(); }
}

// ── Decrypt modal ──────────────────────────────────────────────
let _decryptTargetPath = null;

function promptDecrypt(filePath) {
  _decryptTargetPath = filePath;
  document.getElementById('decrypt-file-label').textContent = filePath;
  document.getElementById('decrypt-password').value = '';
  document.getElementById('decrypt-keyfile').value = '';
  document.getElementById('decrypt-error').style.display = 'none';
  document.getElementById('decrypt-btn').textContent = 'DECRYPT & PLAY';
  document.getElementById('decrypt-btn').disabled = false;
  document.getElementById('decrypt-overlay').classList.add('open');
  setTimeout(() => document.getElementById('decrypt-password').focus(), 50);
}

function closeDecryptModal() {
  document.getElementById('decrypt-overlay').classList.remove('open');
  _decryptTargetPath = null;
}

function _decryptOverlayClick(evt) {
  if (evt.target === document.getElementById('decrypt-overlay')) closeDecryptModal();
}

async function doDecrypt() {
  if (!_decryptTargetPath) return;
  const password = document.getElementById('decrypt-password').value.trim() || null;
  const keyFile  = document.getElementById('decrypt-keyfile').value.trim() || null;

  if (!password && !keyFile) {
    const errEl = document.getElementById('decrypt-error');
    errEl.textContent = 'Enter a password or key file path.';
    errEl.style.display = 'block';
    return;
  }

  const btn = document.getElementById('decrypt-btn');
  btn.textContent = 'DECRYPTING…';
  btn.disabled = true;
  document.getElementById('decrypt-error').style.display = 'none';

  try {
    const res = await fetch('/api/decrypt', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_path: _decryptTargetPath, password, key_file: keyFile }),
    });

    if (!res.ok) {
      const err = await res.json().catch(() => ({ error: res.statusText }));
      const errEl = document.getElementById('decrypt-error');
      errEl.textContent = err.error || 'Decryption failed.';
      errEl.style.display = 'block';
      btn.textContent = 'DECRYPT & PLAY';
      btn.disabled = false;
      return;
    }

    // Stream the decrypted video into a blob URL for inline playback
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    closeDecryptModal();
    playSegment(blobUrl, _decryptTargetPath + ' (decrypted)');

  } catch(e) {
    const errEl = document.getElementById('decrypt-error');
    errEl.textContent = 'Network error: ' + e.message;
    errEl.style.display = 'block';
    btn.textContent = 'DECRYPT & PLAY';
    btn.disabled = false;
  }
}

// ── Browse for video file (native OS dialog, local only) ──────

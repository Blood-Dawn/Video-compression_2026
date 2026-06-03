/*
 * src/gui/static/js/plates.js
 *
 * SVCS dashboard - plates module. Carved verbatim from the former single
 * inline <script> in index.html (TASK 1.5). Loaded as a classic script in
 * original execution order, so behavior is identical; all functions stay
 * global (reachable from inline on* handlers and the other modules).
 * Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - JS split).
 */
function _platePathFromUrl(url) {
  if (!url) return '';
  if (url.startsWith('/api/media?path=')) {
    return decodeURIComponent(url.slice('/api/media?path='.length));
  }
  return url;
}

function readPlatesFromCurrentPreview(which) {
  // Map the calling tab to its <video> element so we can grab the loaded src.
  const videoIds = { home: 'home-preview-video', search: 'search-preview-video', metrics: 'seg-preview' };
  const v = document.getElementById(videoIds[which] || 'home-preview-video');
  if (!v || !v.src) {
    pushNotif('PLATE READER', 'Load a clip first.', 'warning', null, 4000);
    return;
  }
  const path = _platePathFromUrl(v.src);
  if (!path) {
    pushNotif('PLATE READER', 'Could not resolve clip path.', 'error', null, 4000);
    return;
  }
  runPlateReader(path);
}

async function runPlateReader(file_path, options) {
  const opts = options || {};
  _showPlateModal();
  _setPlateStatus('Running AI super-resolution + plate OCR…');
  _renderPlateResults({ candidate_plates: [], best_read: null, frames_examined: 0, frames_total: 0, warnings: [] }, true);

  try {
    const res = await fetch('/api/enhance/plates', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        file_path: file_path,
        sample_every_n_frames: opts.sample_every_n_frames || 5,
        max_frames:            opts.max_frames || 60,
        min_consensus_votes:   opts.min_consensus_votes || 1,
        min_ocr_confidence:    opts.min_ocr_confidence || 0.4,
        device:                opts.device || null,
        ocr_backend:           opts.ocr_backend || 'auto',
      }),
    });
    const data = await res.json();
    if (!res.ok) {
      _setPlateStatus('Error: ' + (data.error || ('HTTP ' + res.status)));
      return;
    }
    _renderPlateResults(data, false);
    if (data.best_read) {
      pushNotif('PLATE READ', 'Best read: ' + data.best_read, 'success', null, 6000);
    } else {
      pushNotif('PLATE READER', 'No high-confidence reads. See the results panel for details.', 'warning', null, 6000);
    }
  } catch (e) {
    _setPlateStatus('Request failed: ' + e.message);
  }
}

function _showPlateModal() {
  const m = document.getElementById('plate-modal');
  if (m) m.style.display = 'flex';
}
function closePlateModal() {
  const m = document.getElementById('plate-modal');
  if (m) m.style.display = 'none';
}
function _setPlateStatus(msg) {
  const el = document.getElementById('plate-status');
  if (el) el.textContent = msg || '';
}

function _verdictColor(v) {
  if (v === 'high')   return 'var(--green)';
  if (v === 'medium') return 'var(--teal)';
  if (v === 'low')    return 'var(--yellow)';
  return 'var(--text-dim)';  // uncertain
}

function _renderPlateResults(data, busy) {
  const body = document.getElementById('plate-modal-body');
  if (!body) return;
  const list = (data && data.candidate_plates) || [];

  let html = '<div style="font-family:var(--mono);font-size:0.65rem;color:var(--text-dim);margin-bottom:0.4rem;">' +
             'OCR backend: <strong style="color:var(--teal);">' + (data.backend || 'unknown') + '</strong>' +
             '  ·  SR: <strong style="color:var(--teal);">' + (data.sr_backend || 'unknown') + '</strong>' +
             '  ·  frames: ' + (data.frames_examined || 0) + (data.frames_total ? (' / ' + data.frames_total) : '') +
             '</div>';

  if (busy) {
    html += '<div class="empty-state" style="padding:1rem 0;">analysing…</div>';
  } else if (!list.length) {
    html += '<div class="empty-state" style="padding:1rem 0;">No plate candidates above the confidence threshold.</div>';
  } else {
    html += '<table class="demo-history-table" style="width:100%;font-family:var(--mono);font-size:0.65rem;">' +
            '<thead><tr><th style="text-align:left;">Plate</th><th>Verdict</th><th>Confidence</th><th>Votes</th><th>Frames</th></tr></thead><tbody>';
    list.forEach(p => {
      const vc = _verdictColor(p.verdict);
      const framesShort = (p.frames || []).slice(0, 6).join(', ') + (p.frames && p.frames.length > 6 ? ' …' : '');
      html += '<tr>' +
              '<td style="font-weight:bold;letter-spacing:1px;color:var(--text);">' + p.text + '</td>' +
              '<td><span style="color:' + vc + ';font-weight:bold;">' + (p.verdict || '').toUpperCase() + '</span></td>' +
              '<td>' + (p.confidence !== undefined ? p.confidence.toFixed(2) : ' - ') + '</td>' +
              '<td>' + (p.votes || 0) + '</td>' +
              '<td style="color:var(--text-dim);">' + framesShort + '</td>' +
              '</tr>';
    });
    html += '</tbody></table>';
  }

  if (data.warnings && data.warnings.length) {
    html += '<div style="margin-top:0.5rem;padding:0.4rem 0.6rem;background:var(--yellow-dim);border-left:2px solid var(--yellow);font-family:var(--mono);font-size:0.6rem;color:var(--text-dim);">';
    html += data.warnings.map(w => '⚠ ' + w).join('<br>');
    html += '</div>';
  }

  // Honest caveat - sponsor flagged hallucination risk on plates at kickoff.
  html += '<div style="margin-top:0.5rem;font-family:var(--mono);font-size:0.55rem;color:var(--text-dim);font-style:italic;">' +
          'Verdict cap: HIGH ≥ 3 frames + OCR ≥ 0.60 · MEDIUM ≥ 2 frames + OCR ≥ 0.50 · ' +
          'low/uncertain reads should be operator-verified, not actioned.' +
          '</div>';

  body.innerHTML = html;

  if (!busy) _setPlateStatus('Done. ' + list.length + ' candidate plate' + (list.length === 1 ? '' : 's') + '.');
}

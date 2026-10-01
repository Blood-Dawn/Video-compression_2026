/*
 * src/gui/static/js/timelapse.js
 *
 * SVCS dashboard - "Make timelapse" button on the segment detail card
 * (2026-10-01 competitive-gap feature). Posts the selected segment's path
 * to /api/timelapse, which speeds the clip up with ffmpeg and writes the
 * result beside the source. Mirrors encryption.js's promptEncryptSegment
 * wiring (files.js passes s.file_path directly rather than a global) so
 * the two buttons behave consistently in the same card.
 *
 * Author: Bloodawn (KheivenD), 2026-10-01.
 */

async function makeTimelapseForSegment(filePath) {
  if (!filePath) return;
  const btn = document.getElementById('metrics-timelapse-btn');

  const speed = window.prompt('Timelapse speed (2-60x faster)?', '8');
  if (speed === null) return;   // cancelled

  if (btn) {
    btn.disabled = true;
    btn.textContent = 'Generating…';
  }
  try {
    const res = await fetch('/api/timelapse', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ path: filePath, speed }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      if (typeof pushNotif === 'function') {
        pushNotif('Timelapse failed', data.error || 'Unknown error', 'error');
      } else {
        window.alert('Timelapse failed: ' + (data.error || 'Unknown error'));
      }
      return;
    }
    if (typeof pushNotif === 'function') {
      pushNotif('Timelapse ready', data.filename, 'ok');
    } else {
      window.alert('Timelapse ready: ' + data.filename);
    }
    // Refresh the file list so the new <stem>_timelapse_Nx file shows up
    // next to its source, same as other routes that write a derived file.
    if (typeof scanVideos === 'function') scanVideos();
    if (typeof loadLibrary === 'function') loadLibrary();
  } catch (e) {
    console.error('timelapse', e);
    if (typeof pushNotif === 'function') {
      pushNotif('Timelapse failed', String(e), 'error');
    }
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = '[FF] Make timelapse';
    }
  }
}

window.makeTimelapseForSegment = makeTimelapseForSegment;

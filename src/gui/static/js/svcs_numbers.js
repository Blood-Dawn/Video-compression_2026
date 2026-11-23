// Browser port of svcs_numbers.py. Keep the two in step: the same cases are checked in both.
// Loaded as a plain script (adds window.SvcsNumbers) or required from Node.
// Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, task 13.3 and 13.4).
(function (root) {
  'use strict';
  var MIB = 1024 * 1024;
  var SLIDER_MIN_S = 10, SLIDER_MAX_S = 1800, LIVE_DEFAULT_S = 600;
  var PRESET_CANDIDATES_S = [30, 60, 120, 300, 600, 900, 1800];
  var LIVE_PRESETS_S = [60, 300, 600, 900, 1800];

  function roundHalfUp(x) { return Math.floor(x + 0.5); }
  function round1(x) { return Math.round(x * 10) / 10; }

  function fmtLength(seconds) {
    seconds = Math.floor(seconds);
    if (seconds < 60) return seconds + ' s';
    var h = Math.floor(seconds / 3600), rem = seconds % 3600;
    var m = Math.floor(rem / 60), s = rem % 60, parts = [];
    if (h) parts.push(h + ' h');
    if (m) parts.push(m + ' min');
    if (s) parts.push(s + ' s');
    return parts.join(' ');
  }

  // pairs: [[sourceBytes, outputBytes], ...] for one job. Sums first, rounds once.
  function summarizeResult(pairs) {
    var src = 0, out = 0;
    pairs.forEach(function (p) {
      if (p[0] < 0 || p[1] < 0) throw new Error('file sizes cannot be negative');
      src += Math.floor(p[0]); out += Math.floor(p[1]);
    });
    if (src === 0) return { verdict: 'unknown', source_bytes: 0, output_bytes: out };
    var beforeMb = round1(src / MIB), afterMb = round1(out / MIB);
    if (out >= src) {
      return { verdict: 'no_saving', source_bytes: src, output_bytes: out, saved_bytes: 0, saved_pct: 0,
               ratio: out ? round1(src / out) : null, before_mb: beforeMb, after_mb: afterMb, saved_mb: 0 };
    }
    var pct = roundHalfUp(100 * (src - out) / src);
    if (out > 0 && pct >= 100) pct = 99;
    return { verdict: 'saved', source_bytes: src, output_bytes: out, saved_bytes: src - out, saved_pct: pct,
             ratio: out ? round1(src / out) : null, before_mb: beforeMb, after_mb: afterMb,
             saved_mb: round1(beforeMb - afterMb) };
  }

  function formatResult(r) {
    if (r.verdict === 'unknown') return { headline: 'Size not available', detail: 'The source file size could not be read.' };
    if (r.verdict === 'no_saving') {
      return { headline: 'No space saved',
               detail: r.before_mb.toFixed(1) + ' MB became ' + r.after_mb.toFixed(1) + ' MB. The original was kept.' };
    }
    var ratio = r.ratio ? ', ' + r.ratio.toFixed(1) + ' times smaller' : '';
    return { headline: 'Saved ' + r.saved_pct + '%',
             detail: r.before_mb.toFixed(1) + ' MB to ' + r.after_mb.toFixed(1) + ' MB, ' + r.saved_mb.toFixed(1) + ' MB freed' + ratio };
  }

  function clipCount(durationS, segmentSeconds) {
    return Math.max(1, Math.ceil(durationS / Math.max(1, segmentSeconds)));
  }

  // Default is the whole video, recommended is half rounded up to 10 s, presets are shorter than the video.
  function planSegments(durationS) {
    if (durationS == null || durationS <= 0) {
      return { kind: 'live', default_seconds: LIVE_DEFAULT_S, recommended_seconds: LIVE_DEFAULT_S, whole_seconds: null,
               presets: LIVE_PRESETS_S.map(function (s) { return { label: fmtLength(s), seconds: s }; }) };
    }
    var whole = Math.ceil(durationS) + 1, rec;
    if (durationS < 2 * SLIDER_MIN_S) rec = whole;
    else rec = Math.min(whole, Math.max(SLIDER_MIN_S, Math.ceil((durationS / 2) / 10) * 10));
    return {
      kind: 'file', default_seconds: whole, recommended_seconds: rec, whole_seconds: whole,
      presets: PRESET_CANDIDATES_S.filter(function (s) { return s < durationS; })
                 .map(function (s) { return { label: fmtLength(s), seconds: s }; }),
      clips_at_recommended: clipCount(durationS, rec),
      fits_slider: rec >= SLIDER_MIN_S && rec <= SLIDER_MAX_S
    };
  }

  var api = { MIB: MIB, summarizeResult: summarizeResult, formatResult: formatResult, planSegments: planSegments,
              clipCount: clipCount, fmtLength: fmtLength };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.SvcsNumbers = api;
})(typeof window !== 'undefined' ? window : this);

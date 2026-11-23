/* Segment length control for the Home page.
 *
 * The default is the whole video as one compressed file. A Recommended line
 * (half the video) and preset buttons sit under it. A live source has no
 * length, so it gets minute presets and a 10 minute default instead.
 *
 * The numbers come from /api/segment-plan, which uses the same algorithm as
 * svcs_numbers.js (src/utils/result_numbers.py on the server).
 *
 * The hidden #segment-seconds input is what startPipeline() reads. The slider
 * stays as a "Custom length" control for anyone who wants an exact value.
 *
 * Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, task 13.4).
 */
(function () {
  'use strict';

  var WHOLE_FALLBACK_S = 86400;   // length unknown: one file for up to a day
  var LIVE_FALLBACK_S = 600;
  var state = { kind: 'default', seconds: null };   // 'default' or 'fixed'
  var plan = null;
  var live = false;
  var ticket = 0;

  function el(id) { return document.getElementById(id); }
  function fmt(s) { return window.SvcsNumbers ? window.SvcsNumbers.fmtLength(s) : s + ' s'; }

  function effectiveSeconds() {
    if (state.kind === 'fixed') return state.seconds;
    if (plan) return plan.default_seconds;
    return live ? LIVE_FALLBACK_S : WHOLE_FALLBACK_S;
  }

  function clipsFor(seconds) {
    if (!plan || plan.kind !== 'file' || !window.SvcsNumbers) return null;
    return window.SvcsNumbers.clipCount(plan.duration_s, seconds);
  }

  function headline(seconds) {
    if (state.kind === 'default' && !live) return 'Whole video';
    return fmt(seconds);
  }

  function button(label, seconds, pressed, onClick) {
    var b = document.createElement('button');
    b.type = 'button';
    b.className = 'btn btn-ghost seg-pbtn' + (pressed ? ' on' : '');
    b.textContent = label;
    b.setAttribute('aria-pressed', pressed ? 'true' : 'false');
    b.addEventListener('click', onClick);
    return b;
  }

  function renderPresets(seconds) {
    var box = el('seg-plan-presets');
    if (!box) return;
    box.innerHTML = '';
    if (!live) {
      box.appendChild(button('Whole video', null, state.kind === 'default',
        function () { state = { kind: 'default', seconds: null }; render(); }));
    }
    var list = plan && plan.presets ? plan.presets : [];
    list.forEach(function (p) {
      var pressed = live
        ? (state.kind === 'default' ? p.seconds === plan.default_seconds : state.seconds === p.seconds)
        : (state.kind === 'fixed' && state.seconds === p.seconds);
      box.appendChild(button(p.label, p.seconds, pressed, function () { setFixed(p.seconds); }));
    });
  }

  function renderRecommended() {
    var row = el('seg-plan-rec');
    if (!row) return;
    var show = plan && plan.kind === 'file';
    row.hidden = !show;
    if (!show) return;
    var whole = plan.recommended_seconds === plan.whole_seconds;
    el('seg-plan-rec-val').textContent = whole ? 'Whole video' : fmt(plan.recommended_seconds);
    el('seg-plan-rec-note').textContent = whole
      ? 'This video is short, so one file is best.'
      : 'Half of this video, ' + plan.clips_at_recommended + ' files.';
    var use = el('seg-plan-use-rec');
    if (use) use.hidden = whole;
  }

  function renderHint(seconds) {
    var hint = el('seg-plan-hint');
    if (!hint) return;
    var clips = clipsFor(seconds);
    if (live) {
      hint.textContent = 'A new compressed file every ' + fmt(seconds) + '.';
    } else if (clips === null) {
      hint.textContent = 'The video length is not known yet, so it will be compressed as one file.';
    } else if (clips === 1) {
      hint.textContent = 'You get 1 compressed file for the whole video.';
    } else {
      hint.textContent = 'The video is split into ' + clips + ' compressed files.';
    }
  }

  function render() {
    var seconds = effectiveSeconds();
    var hidden = el('segment-seconds');
    if (hidden) hidden.value = seconds;
    var label = el('seg-len-val');
    if (label) label.textContent = headline(seconds);
    var slider = el('segment-seconds-slider');
    if (slider) slider.value = Math.min(1800, Math.max(10, seconds));
    renderRecommended();
    renderPresets(seconds);
    renderHint(seconds);
  }

  function setFixed(seconds) {
    var v = parseInt(seconds, 10);
    if (!(v > 0)) return;
    state = { kind: 'fixed', seconds: v };
    if (typeof _segLenUserTouched !== 'undefined') _segLenUserTouched = true;
    render();
  }

  // Ask the server for this source's plan. A failure keeps the whole video
  // default, which is always safe.
  function refresh(source) {
    var src = (source != null ? source : (el('input-source') || {}).value || '').trim();
    live = typeof _isLiveSource === 'function' ? !!_isLiveSource(src) : false;
    var mine = ++ticket;
    var url = '/api/segment-plan' + (live || !src ? '' : '?path=' + encodeURIComponent(src));
    if (live || !src) live = true;
    plan = null;
    render();
    fetch(url)
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (data) {
        if (mine !== ticket) return;
        plan = data && data.kind ? data : null;
        render();
      })
      .catch(function () { /* keep the safe default */ });
  }

  function useRecommended() {
    if (plan && plan.kind === 'file') setFixed(plan.recommended_seconds);
  }

  window.SegPlan = { refresh: refresh, setFixed: setFixed, useRecommended: useRecommended };
})();

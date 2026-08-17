/*
 * src/gui/static/js/push.js
 *
 * Closed-app phone alerts (R6 TRACK C1).
 *
 * The phone app only notifies while its process is alive. This panel points
 * the SERVER at an ntfy topic the operator hosts, so a line crossing or a
 * finished compression reaches the phone even with SVCS fully closed, and it
 * does that without handing anything to a third-party push service.
 *
 * Two deliberate departures from the retention panel next door:
 *   - nothing auto-saves on change, because turning the switch on without a
 *     topic URL is a validation error and silently bouncing it would read as
 *     the checkbox being broken;
 *   - the token field is write-only. The server answers with has_token, never
 *     the secret, so this panel can edit a token it is never given. Leaving
 *     the field blank keeps whatever is already stored.
 *
 * Author: Bloodawn (KheivenD), 2026-08-17 (R6 TRACK C1).
 */
"use strict";

let _pushLoaded = false;

function _pushSay(text, kind) {
  const el = document.getElementById("push-status");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = kind === "error" ? "var(--red)"
                 : kind === "ok" ? "var(--green)" : "var(--text-dim)";
}

function _pushTokenHint(hasToken) {
  const el = document.getElementById("push-token");
  if (!el) return;
  el.placeholder = hasToken
    ? (STRINGS.push ? STRINGS.push.tokenStored : "a token is stored, leave blank to keep it")
    : (STRINGS.push ? STRINGS.push.tokenNone : "optional, for a topic that requires auth");
}

function _pushApply(cfg) {
  if (!cfg) return;
  const en = document.getElementById("push-enabled");
  const url = document.getElementById("push-url");
  const jobs = document.getElementById("push-on-jobs");
  const events = document.getElementById("push-on-events");
  if (en) en.checked = !!cfg.enabled;
  if (url && !_pushLoaded) url.value = cfg.topic_url || "";
  if (jobs) jobs.checked = cfg.on_jobs !== false;
  if (events) events.checked = cfg.on_events !== false;
  _pushTokenHint(!!cfg.has_token);
  _pushLoaded = true;
}

async function pushCfgRefresh() {
  try {
    const data = await (await fetch("/api/push/config")).json();
    _pushApply(data && data.config);
  } catch (e) { /* keep whatever is on screen */ }
}
window.pushCfgRefresh = pushCfgRefresh;

function _pushBody() {
  const body = {
    enabled: !!document.getElementById("push-enabled")?.checked,
    topic_url: (document.getElementById("push-url")?.value || "").trim(),
    on_jobs: !!document.getElementById("push-on-jobs")?.checked,
    on_events: !!document.getElementById("push-on-events")?.checked,
  };
  // Only send the token when the operator actually typed one. Omitting the
  // key is what tells the server to keep the stored secret.
  const tok = (document.getElementById("push-token")?.value || "").trim();
  if (tok) body.token = tok;
  return body;
}

async function pushCfgSave() {
  const btn = document.getElementById("push-save-btn");
  if (btn) { btn.disabled = true; }
  _pushSay("Saving...");
  try {
    const res = await fetch("/api/push/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_pushBody()),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      _pushSay(data.error || "Could not save.", "error");
      _pushApply(data.config);
      return;
    }
    const tokEl = document.getElementById("push-token");
    if (tokEl) tokEl.value = "";
    _pushApply(data.config);
    _pushSay(data.config && data.config.enabled
      ? "Saved. Alerts are on."
      : "Saved. Alerts are off.", "ok");
  } catch (e) {
    _pushSay(String(e), "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}
window.pushCfgSave = pushCfgSave;

async function pushCfgTest() {
  const btn = document.getElementById("push-test-btn");
  const url = (document.getElementById("push-url")?.value || "").trim();
  if (!url) { _pushSay("Enter a topic URL first.", "error"); return; }
  if (btn) { btn.disabled = true; btn.textContent = "Sending..."; }
  _pushSay("Sending a test message...");
  try {
    // The typed URL is tested as-is, before any save, so a bad URL never has
    // to be stored to be diagnosed. A typed token is used for this one send.
    const body = { topic_url: url };
    const tok = (document.getElementById("push-token")?.value || "").trim();
    if (tok) body.token = tok;
    const data = await (await fetch("/api/push/test", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })).json();
    if (data.ok) {
      _pushSay("Test sent. Check your phone.", "ok");
      if (typeof pushNotif === "function")
        pushNotif("Test alert sent", "If your phone is subscribed to this topic it should be buzzing.", "success", null, 5000);
    } else {
      _pushSay("Test failed: " + (data.detail || "unknown reason"), "error");
    }
  } catch (e) {
    _pushSay(String(e), "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Send test"; }
  }
}
window.pushCfgTest = pushCfgTest;

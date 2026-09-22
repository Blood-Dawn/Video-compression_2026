/*
 * src/gui/static/js/webhook.js
 *
 * Outbound webhook settings panel (Week 3 TASK 3.9).
 *
 * Same shape as push.js next door, over /api/webhook/* instead of
 * /api/push/*: a plain JSON POST to whatever URL the operator points it
 * at, optionally HMAC-signed with a secret the server never echoes back.
 *
 *   - nothing auto-saves on change, same reasoning as push.js: flipping the
 *     switch on with no URL is a validation error, not a silent no-op;
 *   - the secret field is write-only. The server answers with has_secret,
 *     never the secret, so this panel can edit a secret it is never given.
 *     Leaving the field blank keeps whatever is already stored.
 *
 * Author: Bloodawn (KheivenD), Week 3 (3.9).
 */
"use strict";

let _webhookLoaded = false;

function _webhookSay(text, kind) {
  const el = document.getElementById("webhook-status");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = kind === "error" ? "var(--red)"
                 : kind === "ok" ? "var(--green)" : "var(--text-dim)";
}

function _webhookSecretHint(hasSecret) {
  const el = document.getElementById("webhook-secret");
  if (!el) return;
  el.placeholder = hasSecret
    ? "a secret is stored, leave blank to keep it"
    : "optional, signs deliveries with X-SVCS-Signature";
}

function _webhookApply(cfg) {
  if (!cfg) return;
  const en = document.getElementById("webhook-enabled");
  const url = document.getElementById("webhook-url");
  const jobs = document.getElementById("webhook-on-jobs");
  const events = document.getElementById("webhook-on-events");
  if (en) en.checked = !!cfg.enabled;
  if (url && !_webhookLoaded) url.value = cfg.url || "";
  if (jobs) jobs.checked = cfg.on_jobs !== false;
  if (events) events.checked = cfg.on_events !== false;
  _webhookSecretHint(!!cfg.has_secret);
  _webhookLoaded = true;
}

async function webhookCfgRefresh() {
  try {
    const data = await (await fetch("/api/webhook/config")).json();
    _webhookApply(data && data.config);
  } catch (e) { /* keep whatever is on screen */ }
}
window.webhookCfgRefresh = webhookCfgRefresh;

function _webhookBody() {
  const body = {
    enabled: !!document.getElementById("webhook-enabled")?.checked,
    url: (document.getElementById("webhook-url")?.value || "").trim(),
    on_jobs: !!document.getElementById("webhook-on-jobs")?.checked,
    on_events: !!document.getElementById("webhook-on-events")?.checked,
  };
  // Only send the secret when the operator actually typed one. Omitting
  // the key is what tells the server to keep the stored secret.
  const secret = (document.getElementById("webhook-secret")?.value || "").trim();
  if (secret) body.secret = secret;
  return body;
}

async function webhookCfgSave() {
  const btn = document.getElementById("webhook-save-btn");
  if (btn) { btn.disabled = true; }
  _webhookSay("Saving...");
  try {
    const res = await fetch("/api/webhook/config", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(_webhookBody()),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      _webhookSay(data.error || "Could not save.", "error");
      _webhookApply(data.config);
      return;
    }
    const secretEl = document.getElementById("webhook-secret");
    if (secretEl) secretEl.value = "";
    _webhookApply(data.config);
    _webhookSay(data.config && data.config.enabled
      ? "Saved. Deliveries are on."
      : "Saved. Deliveries are off.", "ok");
  } catch (e) {
    _webhookSay(String(e), "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}
window.webhookCfgSave = webhookCfgSave;

async function webhookCfgTest() {
  const btn = document.getElementById("webhook-test-btn");
  const url = (document.getElementById("webhook-url")?.value || "").trim();
  if (!url) { _webhookSay("Enter a webhook URL first.", "error"); return; }
  if (btn) { btn.disabled = true; btn.textContent = "Sending..."; }
  _webhookSay("Sending a test delivery...");
  try {
    // The typed URL is tested as-is, before any save, so a bad URL never
    // has to be stored to be diagnosed. A typed secret is used for this
    // one send only.
    const body = { url: url };
    const secret = (document.getElementById("webhook-secret")?.value || "").trim();
    if (secret) body.secret = secret;
    const data = await (await fetch("/api/webhook/test", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })).json();
    if (data.ok) {
      _webhookSay("Test sent: " + (data.detail || "delivered"), "ok");
    } else {
      _webhookSay("Test failed: " + (data.detail || "unknown reason"), "error");
    }
  } catch (e) {
    _webhookSay(String(e), "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Send test"; }
  }
}
window.webhookCfgTest = webhookCfgTest;

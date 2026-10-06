/*
 * src/gui/static/js/webhook.js
 *
 * Event webhook settings (planner 4.10). The sibling of push.js: push tells a
 * HUMAN, this tells another SYSTEM, by POSTing behavior events as JSON to a
 * URL the operator picks.
 *
 * Same two rules as the push panel:
 *   - nothing auto-saves on change, because turning the switch on without a
 *     URL is a validation error and silently bouncing it would read as the
 *     checkbox being broken;
 *   - the signing secret is write-only. The server answers with has_secret,
 *     never the secret itself, and leaving the field blank keeps whatever is
 *     already stored.
 *
 * Author: Victor De Souza Teixeira, 2026-10-06 (planner 4.10).
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
    : "optional, signs each delivery (X-SVCS-Signature)";
}

function _webhookApply(cfg) {
  if (!cfg) return;
  const en = document.getElementById("webhook-enabled");
  const url = document.getElementById("webhook-url");
  if (en) en.checked = !!cfg.enabled;
  if (url && !_webhookLoaded) url.value = cfg.url || "";
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
  };
  // Only send the secret when the operator actually typed one. Omitting the
  // key is what tells the server to keep the stored secret.
  const sec = (document.getElementById("webhook-secret")?.value || "").trim();
  if (sec) body.secret = sec;
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
      // Keep what the operator typed and ticked. Re-applying the stored
      // config here would silently untick "enabled" after a refused URL, so
      // fixing the URL and pressing Save again would save the webhook OFF.
      _webhookSay(data.error || "Could not save.", "error");
      return;
    }
    const secEl = document.getElementById("webhook-secret");
    if (secEl) secEl.value = "";
    _webhookApply(data.config);
    _webhookSay(data.config && data.config.enabled
      ? "Saved. The webhook is on."
      : "Saved. The webhook is off.", "ok");
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
  _webhookSay("Sending a test event...");
  try {
    // The typed URL is tested as-is, before any save. A typed secret signs
    // this one delivery so the receiver's verification can be checked too.
    const body = { url: url };
    const sec = (document.getElementById("webhook-secret")?.value || "").trim();
    if (sec) body.secret = sec;
    const data = await (await fetch("/api/webhook/test", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })).json();
    if (data.ok) {
      _webhookSay("Test delivered (" + (data.detail || "OK") + ").", "ok");
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

/*
 * src/gui/static/js/usage.js
 *
 * SVCS dashboard — opt-in usage-stats consent (M5 TASK 5.2).
 *
 * On first run (no decision recorded) this shows a small, dismissible consent
 * banner. The choice is persisted via /api/usage_stats/consent; a settings
 * toggle (#usage-stats-toggle, if present) lets the user change it later.
 * Usage stats are DEFAULT OFF and collect only anonymous, non-identifying
 * signal — see utils/usage_stats.py. Degrades to a no-op if the DOM hooks
 * aren't present. Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5.2).
 */
"use strict";

async function _setUsageConsent(consent) {
  try {
    const res = await fetch("/api/usage_stats/consent", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ consent: !!consent }),
    });
    return await res.json();
  } catch (e) {
    return null;
  }
}

function _dismissUsageBanner() {
  const b = document.getElementById("usage-consent-banner");
  if (b) b.remove();
}

function _buildUsageBanner() {
  const b = document.createElement("div");
  b.id = "usage-consent-banner";
  b.style.cssText =
    "position:fixed;left:50%;bottom:16px;transform:translateX(-50%);z-index:9999;"
    + "max-width:560px;width:calc(100% - 32px);background:var(--panel,#1c1c22);"
    + "border:1px solid var(--border,#333);border-radius:8px;padding:12px 14px;"
    + "box-shadow:0 8px 24px rgba(0,0,0,.4);font-size:0.72rem;line-height:1.45;";
  b.innerHTML =
    "<div style='margin-bottom:8px;'>Help improve SVCS? Share <b>anonymous</b> "
    + "usage stats (which presets/codecs you use and whether encodes succeed). "
    + "<b>No footage, file names, paths, or personal data</b> — ever. Default is off; "
    + "you can change this any time in settings.</div>"
    + "<div style='display:flex;gap:8px;justify-content:flex-end;'>"
    + "<button id='usage-decline' class='btn btn-ghost'>No thanks</button>"
    + "<button id='usage-accept' class='btn'>Share anonymously</button>"
    + "</div>";
  document.body.appendChild(b);
  document.getElementById("usage-accept").onclick = async () => {
    await _setUsageConsent(true);
    _syncUsageToggle(true);
    _dismissUsageBanner();
    if (typeof pushNotif === "function") pushNotif("Thanks!", "Anonymous usage stats enabled.", "info", null, 3000);
  };
  document.getElementById("usage-decline").onclick = async () => {
    await _setUsageConsent(false);
    _syncUsageToggle(false);
    _dismissUsageBanner();
  };
}

function _syncUsageToggle(enabled) {
  const t = document.getElementById("usage-stats-toggle");
  if (t && t.type === "checkbox") t.checked = !!enabled;
}

async function initUsageConsent() {
  let data;
  try {
    data = await (await fetch("/api/usage_stats")).json();
  } catch (e) {
    return;  // optional feature; never block the dashboard
  }
  _syncUsageToggle(!!data.enabled);

  // Wire the settings toggle if the page has one.
  const t = document.getElementById("usage-stats-toggle");
  if (t) t.addEventListener("change", () => _setUsageConsent(t.checked));

  // First run (no decision yet): show the consent banner.
  if (!data.known) _buildUsageBanner();
}
window.initUsageConsent = initUsageConsent;
window.addEventListener("DOMContentLoaded", initUsageConsent);

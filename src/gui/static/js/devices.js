/*
 * src/gui/static/js/devices.js
 *
 * Paired mobile devices (M0.10 UI).
 *
 * tokens_bp.py has had list/mint/revoke/revoke_all since M0.10, but nothing
 * in this dashboard ever called it - pairing a phone or revoking a lost one
 * required raw curl/PowerShell against /api/auth/tokens. This panel is the
 * missing front end for that existing, already-secure API (password-gated,
 * hash-only storage, no route that can re-reveal a secret).
 *
 * The mint flow shows the returned secret exactly once, in a copyable box,
 * with a loud "this will not be shown again" - mirroring what the API
 * response itself says. Nothing here stores the secret; it only ever passes
 * through the DOM for the operator to copy into the phone.
 *
 * Author: Bloodawn (KheivenD), 2026-09-24 (M0.10 UI - device management page).
 */
"use strict";

function _devicesSay(text, kind) {
  const el = document.getElementById("devices-status");
  if (!el) return;
  el.textContent = text || "";
  el.style.color = kind === "error" ? "var(--red)"
                 : kind === "ok" ? "var(--green)" : "var(--text-dim)";
}

function _devicesFmtTime(iso) {
  if (!iso) return "never";
  return String(iso).replace("T", " ").replace("Z", "").slice(0, 19);
}

function _devicesStatusLabel(tok) {
  if (tok.revoked) return "revoked";
  if (tok.expired) return "expired";
  if (tok.expires_at) return "active";
  return "active (no expiry)";
}

function _devicesRow(tok) {
  const tr = document.createElement("tr");
  tr.style.borderBottom = "1px solid var(--border)";
  const isLive = !tok.revoked && !tok.expired;
  const statusColor = isLive ? "var(--green)" : "var(--text-dim)";

  const tdLabel = document.createElement("td");
  tdLabel.style.padding = "0.3rem 0.4rem";
  tdLabel.textContent = tok.label || "device";
  tr.appendChild(tdLabel);

  const tdCreated = document.createElement("td");
  tdCreated.style.padding = "0.3rem 0.4rem";
  tdCreated.textContent = _devicesFmtTime(tok.created_at);
  tr.appendChild(tdCreated);

  const tdUsed = document.createElement("td");
  tdUsed.style.padding = "0.3rem 0.4rem";
  tdUsed.textContent = _devicesFmtTime(tok.last_used_at);
  tr.appendChild(tdUsed);

  const tdStatus = document.createElement("td");
  tdStatus.style.padding = "0.3rem 0.4rem";
  tdStatus.style.color = statusColor;
  tdStatus.textContent = _devicesStatusLabel(tok);
  tr.appendChild(tdStatus);

  const tdAction = document.createElement("td");
  tdAction.style.padding = "0.3rem 0.4rem";
  if (isLive) {
    const btn = document.createElement("button");
    btn.className = "btn btn-ghost";
    btn.style.fontSize = "0.55rem";
    btn.style.color = "var(--red)";
    btn.textContent = "Revoke";
    btn.onclick = () => devicesRevoke(tok.id, tok.label);
    tdAction.appendChild(btn);
  }
  tr.appendChild(tdAction);

  return tr;
}

async function devicesRefresh() {
  const rowsEl = document.getElementById("devices-rows");
  const emptyEl = document.getElementById("devices-empty");
  const updatedEl = document.getElementById("devices-updated");
  if (!rowsEl) return;
  try {
    const res = await fetch("/api/auth/tokens");
    const data = await res.json();
    if (!res.ok) {
      _devicesSay(data.error || "Could not load paired devices.", "error");
      return;
    }
    const tokens = data.tokens || [];
    rowsEl.innerHTML = "";
    tokens.forEach((t) => rowsEl.appendChild(_devicesRow(t)));
    if (emptyEl) emptyEl.style.display = tokens.length ? "none" : "block";
    if (updatedEl) updatedEl.textContent = "Updated " + new Date().toLocaleTimeString();
    _devicesSay("");
  } catch (e) {
    _devicesSay(String(e), "error");
  }
}
window.devicesRefresh = devicesRefresh;

async function devicesMint() {
  const btn = document.getElementById("devices-mint-btn");
  const resultEl = document.getElementById("devices-mint-result");
  const label = window.prompt(
    "Name this device (e.g. \"Kheiven's Pixel\"). This just helps you tell devices apart later."
  );
  if (label === null) return; // cancelled
  if (btn) { btn.disabled = true; }
  _devicesSay("Minting a token...");
  try {
    const res = await fetch("/api/auth/tokens", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: (label || "").trim() || "device" }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      _devicesSay(data.error || "Could not mint a token.", "error");
      return;
    }
    if (resultEl) {
      resultEl.style.display = "block";
      resultEl.innerHTML = "";
      const warn = document.createElement("div");
      warn.style.color = "var(--amber)";
      warn.style.marginBottom = "0.4rem";
      warn.textContent = "Copy this token now - it will not be shown again:";
      const code = document.createElement("div");
      code.style.userSelect = "all";
      code.style.wordBreak = "break-all";
      code.style.background = "rgba(0,0,0,0.3)";
      code.style.padding = "0.4rem";
      code.style.borderRadius = "3px";
      code.textContent = data.token;
      const hint = document.createElement("div");
      hint.style.marginTop = "0.4rem";
      hint.style.color = "var(--text-dim)";
      hint.textContent = "Enter this, and this server's address, in the phone app's "
        + "MORE → Server Mode screen, then Test Connection → Save & Open.";
      resultEl.appendChild(warn);
      resultEl.appendChild(code);
      resultEl.appendChild(hint);
    }
    _devicesSay("Paired “" + data.label + "”.", "ok");
    devicesRefresh();
  } catch (e) {
    _devicesSay(String(e), "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}
window.devicesMint = devicesMint;

async function devicesRevoke(id, label) {
  if (!window.confirm("Revoke \"" + (label || "this device") + "\"? "
    + "It will drop back to fully local, on-device compression immediately.")) {
    return;
  }
  _devicesSay("Revoking...");
  try {
    const res = await fetch("/api/auth/tokens/" + encodeURIComponent(id), { method: "DELETE" });
    const data = await res.json();
    if (!res.ok || data.error) {
      _devicesSay(data.error || "Could not revoke.", "error");
      return;
    }
    _devicesSay("Revoked.", "ok");
    devicesRefresh();
  } catch (e) {
    _devicesSay(String(e), "error");
  }
}
window.devicesRevoke = devicesRevoke;

async function devicesRevokeAll() {
  if (!window.confirm("Revoke EVERY paired device? Use this if a phone was lost or stolen. "
    + "Each one drops back to fully local compression immediately and will need to be re-paired.")) {
    return;
  }
  _devicesSay("Revoking all devices...");
  try {
    const res = await fetch("/api/auth/tokens/revoke_all", { method: "POST" });
    const data = await res.json();
    if (!res.ok || data.error) {
      _devicesSay(data.error || "Could not revoke.", "error");
      return;
    }
    _devicesSay("Revoked " + data.count + " device(s).", "ok");
    devicesRefresh();
  } catch (e) {
    _devicesSay(String(e), "error");
  }
}
window.devicesRevokeAll = devicesRevokeAll;

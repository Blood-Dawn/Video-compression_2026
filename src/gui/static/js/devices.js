/*
 * src/gui/static/js/devices.js
 *
 * Paired mobile devices (M0.10 UI).
 *
 * Front end for tokens_bp.py's list/mint/revoke/revoke_all API
 * (password-gated, hash-only storage, no route that can re-reveal a secret),
 * so pairing a phone or revoking a lost one needs no raw curl.
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
  const name = document.createElement("div");
  name.textContent = tok.label || "device";
  tdLabel.appendChild(name);
  const ident = [];
  if (tok.device_name && tok.device_name !== tok.label) ident.push(tok.device_name);
  if (tok.mac) ident.push(tok.mac);
  if (ident.length) {
    const sub = document.createElement("div");
    sub.style.color = "var(--text-dim)";
    sub.textContent = ident.join("  |  ");
    tdLabel.appendChild(sub);
  }
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
    const ren = document.createElement("button");
    ren.className = "btn btn-ghost";
    ren.style.fontSize = "0.55rem";
    ren.style.marginRight = "0.3rem";
    ren.textContent = "Rename";
    ren.setAttribute("aria-label", "Rename " + (tok.label || "this device"));
    ren.onclick = () => devicesRename(tok.id, tok.custom_label ? tok.label : "");
    tdAction.appendChild(ren);
    const btn = document.createElement("button");
    btn.className = "btn btn-ghost";
    btn.style.fontSize = "0.55rem";
    btn.style.color = "var(--red)";
    btn.textContent = "Revoke";
    btn.setAttribute("aria-label", "Revoke " + (tok.label || "this device"));
    btn.style.borderColor = "var(--red)";
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

function _devicesCopyRow(title, value) {
  const wrap = document.createElement("div");
  wrap.style.marginBottom = "0.5rem";
  const head = document.createElement("div");
  head.style.color = "var(--text-dim)";
  head.textContent = title;
  const row = document.createElement("div");
  row.style.display = "flex";
  row.style.gap = "0.4rem";
  row.style.alignItems = "center";
  const code = document.createElement("div");
  code.style.userSelect = "all";
  code.style.wordBreak = "break-all";
  code.style.background = "rgba(0,0,0,0.3)";
  code.style.padding = "0.4rem";
  code.style.borderRadius = "3px";
  code.style.flex = "1";
  code.textContent = value;
  const copy = document.createElement("button");
  copy.type = "button";
  copy.className = "btn btn-ghost";
  copy.textContent = "Copy";
  copy.setAttribute("aria-label", "Copy " + title.toLowerCase());
  copy.onclick = async () => {
    try { await navigator.clipboard.writeText(value); copy.textContent = "Copied"; }
    catch (e) { copy.textContent = "Select and copy"; }
    setTimeout(() => { copy.textContent = "Copy"; }, 1800);
  };
  row.appendChild(code);
  row.appendChild(copy);
  wrap.appendChild(head);
  wrap.appendChild(row);
  return wrap;
}

async function devicesMint() {
  const btn = document.getElementById("devices-mint-btn");
  const resultEl = document.getElementById("devices-mint-result");
  if (btn) { btn.disabled = true; }
  _devicesSay("Creating a pairing token...");
  try {
    // No name is asked for here: the phone reports its own name (and the
    // server records its MAC) the first time it connects. Rename it any time.
    const res = await fetch("/api/auth/tokens", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: "" }),
    });
    const data = await res.json();
    if (!res.ok || data.error) {
      _devicesSay(data.error || "Could not create a token.", "error");
      return;
    }
    if (resultEl) {
      resultEl.style.display = "block";
      resultEl.innerHTML = "";
      const warn = document.createElement("div");
      warn.style.color = "var(--amber)";
      warn.style.marginBottom = "0.5rem";
      warn.textContent = "Copy the token now. It will not be shown again.";
      resultEl.appendChild(warn);
      resultEl.appendChild(_devicesCopyRow("Server address", data.server_url || window.location.origin));
      resultEl.appendChild(_devicesCopyRow("Token", data.token));
      const hint = document.createElement("div");
      hint.style.color = "var(--text-dim)";
      hint.textContent = "On the phone: MORE, then Server Mode. Enter the server address and the token, "
        + "tap Test Connection, then Save & Open. The device shows up below with the phone's own name, "
        + "and you can rename it.";
      resultEl.appendChild(hint);
    }
    _devicesSay("Token ready. Waiting for the phone to connect.", "ok");
    devicesRefresh();
  } catch (e) {
    _devicesSay(String(e), "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}
window.devicesMint = devicesMint;

async function devicesRename(id, current) {
  const label = window.prompt("Name this device. Leave it blank to use the phone's own name.", current || "");
  if (label === null) return;
  try {
    const res = await fetch("/api/auth/tokens/" + encodeURIComponent(id), {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ label: label }),
    });
    const data = await res.json();
    if (!res.ok || data.error) { _devicesSay(data.error || "Could not rename.", "error"); return; }
    _devicesSay("Renamed to \u201c" + data.label + "\u201d.", "ok");
    devicesRefresh();
  } catch (e) {
    _devicesSay(String(e), "error");
  }
}
window.devicesRename = devicesRename;

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

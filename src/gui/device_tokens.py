"""
src/gui/device_tokens.py

Per-device access tokens for the dashboard API (M0.10, mobile port).

TASK 4.4 gave the dashboard a single username+password pair enforced as HTTP
Basic. That is workable for one operator at one browser, but it does not survive
contact with phones: a credential typed into a phone is a credential that leaves
the building, and the only way to cut off a lost phone is to rotate the password
for every client at once.

This module adds tokens that can be revoked one at a time.

Design notes, and why:

  * The secret is shown ONCE, at mint time, and only its SHA-256 is persisted.
    A leaked token file therefore does not yield working credentials. There is
    no "show me the token again" path on purpose.
  * Tokens carry a ``svcs_`` prefix so secret scanners and log filters have
    something to match on, and so a human can recognize one in a paste.
  * Verification is constant-time over the hash, and compares BYTES, never str
    (see the auth.py non-ASCII bug: comparing str with hmac.compare_digest
    raises on non-ASCII and turned an attacker-controlled value into a 500).
  * Minting and revoking require the PASSWORD, not a token. A stolen token must
    not be able to mint more tokens or revoke the operator's other devices.
    That check lives in the route layer; this module only stores and verifies.
  * Storage is data_dir()/device_tokens.json, registered in STATE_FILE_NAMES so
    a factory reset revokes every device. It deliberately does NOT live in the
    per-output-folder metadata.db, which travels with the videos and is cleared
    by /api/segments/clear.
  * Nothing here logs token material, in keeping with the house rule.

Author: Bloodawn (KheivenD), 2026-07-18 (M0.10 - device tokens for the mobile client).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from utils.paths import state_file
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils.paths import state_file

# File name under data_dir(). Mirrored in utils.paths.STATE_FILE_NAMES so the
# factory-reset action revokes every device token.
TOKEN_FILE_NAME = "device_tokens.json"

# Prefix on every minted token. Recognizable in a log or a paste, and greppable
# by secret scanners.
TOKEN_PREFIX = "svcs_"

# Bytes of entropy behind each token. 32 bytes = 256 bits, base64url-encoded to
# 43 characters. Far beyond guessing range for an endpoint with rate limiting.
_TOKEN_ENTROPY_BYTES = 32

# Schema version, so a later format change can migrate rather than clobber.
_SCHEMA_VERSION = 1

# Serializes read-modify-write cycles. Flask runs threaded=True, so two
# concurrent mint or revoke calls would otherwise race and lose one of them.
_LOCK = threading.RLock()


def _utc_now_iso() -> str:
    """Timestamp in the same fixed-width UTC form the rest of the app uses."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def token_hash(token: str) -> str:
    """SHA-256 of a token, hex. The only form ever written to disk."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


@dataclass
class DeviceToken:
    """One issued token. Never holds the secret, only its hash."""

    id: str
    label: str
    sha256: str = field(repr=False)
    created_at: str
    last_used_at: Optional[str] = None
    expires_at: Optional[str] = None
    revoked: bool = False

    def is_expired(self, now: Optional[str] = None) -> bool:
        """True if an expiry was set and it has passed."""
        if not self.expires_at:
            return False
        return (now or _utc_now_iso()) >= self.expires_at

    def is_usable(self, now: Optional[str] = None) -> bool:
        return not self.revoked and not self.is_expired(now)

    def to_public(self) -> Dict[str, Any]:
        """The safe-to-return view: everything EXCEPT the hash.

        The hash is withheld so a read-only view of the token list can never be
        used to mount an offline guessing attack against the secrets.
        """
        return {
            "id": self.id,
            "label": self.label,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
            "revoked": self.revoked,
            "expired": self.is_expired(),
        }

    def to_record(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "sha256": self.sha256,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
            "revoked": self.revoked,
        }

    @staticmethod
    def from_record(rec: Dict[str, Any]) -> Optional["DeviceToken"]:
        """Parse one stored record, or None if it is malformed.

        A single corrupt entry must not take down authentication for every other
        device, so this returns None instead of raising and the caller skips it.
        """
        try:
            tid = str(rec["id"])
            sha = str(rec["sha256"])
            if not tid or len(sha) != 64:
                return None
            return DeviceToken(
                id=tid,
                label=str(rec.get("label") or "device"),
                sha256=sha,
                created_at=str(rec.get("created_at") or ""),
                last_used_at=rec.get("last_used_at") or None,
                expires_at=rec.get("expires_at") or None,
                revoked=bool(rec.get("revoked", False)),
            )
        except (KeyError, TypeError, ValueError):
            return None


def token_path() -> Path:
    """Full path to the token store."""
    return state_file(TOKEN_FILE_NAME)


def _read_all() -> List[DeviceToken]:
    """Load every stored token. Returns [] when the store is absent or broken.

    Failing open to "no tokens" is the safe direction: it denies token holders
    rather than admitting them, and Basic auth still works.
    """
    p = token_path()
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError, UnicodeDecodeError):
        return []
    if not isinstance(raw, dict):
        return []
    out: List[DeviceToken] = []
    for rec in raw.get("tokens", []) or []:
        if isinstance(rec, dict):
            parsed = DeviceToken.from_record(rec)
            if parsed is not None:
                out.append(parsed)
    return out


def _write_all(tokens: List[DeviceToken]) -> None:
    """Persist the token list atomically, owner-readable only where supported."""
    p = token_path()
    payload = {
        "version": _SCHEMA_VERSION,
        "tokens": [t.to_record() for t in tokens],
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        # Best effort: no-op on Windows, meaningful on POSIX. The file holds
        # only hashes, but there is no reason to leave it world-readable.
        os.chmod(tmp, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass
    os.replace(tmp, p)


def list_tokens() -> List[DeviceToken]:
    """Every stored token, including revoked and expired ones."""
    with _LOCK:
        return _read_all()


def mint_token(label: str, ttl_days: Optional[int] = None) -> tuple[str, DeviceToken]:
    """Create a token. Returns (secret, record).

    The secret is returned exactly once and never stored. Callers must show it
    to the operator immediately and must not log it.
    """
    clean = (label or "").strip()[:64] or "device"
    secret = TOKEN_PREFIX + secrets.token_urlsafe(_TOKEN_ENTROPY_BYTES)
    expires = None
    if ttl_days is not None and int(ttl_days) > 0:
        expires = datetime.fromtimestamp(
            time.time() + int(ttl_days) * 86400, tz=timezone.utc
        ).strftime("%Y-%m-%d %H:%M:%S")
    rec = DeviceToken(
        id=secrets.token_hex(8),
        label=clean,
        sha256=token_hash(secret),
        created_at=_utc_now_iso(),
        expires_at=expires,
    )
    with _LOCK:
        tokens = _read_all()
        tokens.append(rec)
        _write_all(tokens)
    return secret, rec


def revoke_token(token_id: str) -> bool:
    """Revoke by id. True if a live token was revoked, False if unknown.

    Revocation is a tombstone rather than a delete, so the operator can still
    see that a device existed and when it was last used.
    """
    with _LOCK:
        tokens = _read_all()
        hit = False
        for t in tokens:
            if t.id == token_id and not t.revoked:
                t.revoked = True
                hit = True
        if hit:
            _write_all(tokens)
        return hit


def revoke_all() -> int:
    """Revoke every live token. Returns how many were revoked."""
    with _LOCK:
        tokens = _read_all()
        n = 0
        for t in tokens:
            if not t.revoked:
                t.revoked = True
                n += 1
        if n:
            _write_all(tokens)
        return n


def verify_token(presented: str, touch: bool = True) -> Optional[DeviceToken]:
    """Return the matching usable token, or None.

    Compares the SHA-256 of the presented value against every stored hash in
    constant time. Every candidate is compared even after a match so the loop
    does not leak, via timing, WHICH token matched or how many are stored.
    """
    if not presented or not presented.startswith(TOKEN_PREFIX):
        return None
    presented_hash = token_hash(presented).encode("ascii")
    with _LOCK:
        tokens = _read_all()
        found: Optional[DeviceToken] = None
        for t in tokens:
            if hmac.compare_digest(presented_hash, t.sha256.encode("ascii")):
                if t.is_usable() and found is None:
                    found = t
        if found is not None and touch:
            found.last_used_at = _utc_now_iso()
            _write_all(tokens)
        return found


def any_tokens_configured() -> bool:
    """True if at least one usable token exists."""
    return any(t.is_usable() for t in list_tokens())

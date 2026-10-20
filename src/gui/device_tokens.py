"""
src/gui/device_tokens.py

Per-device access tokens for the dashboard API (M0.10, mobile port).

The dashboard's single Basic username+password cannot be revoked per phone, and
a credential typed into a phone leaves the building. These tokens can be
revoked one at a time.

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
from typing import Any

try:
    from utils.paths import state_file
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils.paths import state_file

# File name under data_dir(); also in utils.paths.STATE_FILE_NAMES so a factory
# reset revokes every device token.
TOKEN_FILE_NAME = "device_tokens.json"

# Prefix on every minted token, for secret scanners and humans.
TOKEN_PREFIX = "svcs_"

# 32 bytes = 256 bits of entropy, base64url-encoded to 43 characters.
_TOKEN_ENTROPY_BYTES = 32

_SCHEMA_VERSION = 1

# Serializes read-modify-write cycles (Flask runs threaded=True).
_LOCK = threading.RLock()

# Parsed token records of the last good read, keyed by (path, mtime_ns, size).
# The Bearer guard verifies a token on every request (each HLS segment fetch),
# and re-reading and re-parsing the file each time was the dominant cost.
# Failed reads are never cached, and _write_all drops it.
_parsed_cache: "tuple[tuple, list] | None" = None


def _utc_now_iso() -> str:
    """Fixed-width UTC timestamp, the form the rest of the app uses."""
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
    last_used_at: str | None = None
    expires_at: str | None = None
    revoked: bool = False
    # Where the server posts a native (UnifiedPush) alert for THIS device, set
    # only by the device through its own token. Anyone holding it can push to
    # the phone, so it is stored here but never returned by to_public().
    push_endpoint: str | None = field(default=None, repr=False)

    def is_expired(self, now: str | None = None) -> bool:
        """True if an expiry was set and it has passed."""
        if not self.expires_at:
            return False
        return (now or _utc_now_iso()) >= self.expires_at

    def is_usable(self, now: str | None = None) -> bool:
        return not self.revoked and not self.is_expired(now)

    def to_public(self) -> dict[str, Any]:
        """The safe-to-return view: everything except the hash and push endpoint."""
        return {
            "id": self.id,
            "label": self.label,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
            "revoked": self.revoked,
            "expired": self.is_expired(),
            "has_push_endpoint": bool(self.push_endpoint),
        }

    def to_record(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "label": self.label,
            "sha256": self.sha256,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
            "revoked": self.revoked,
            "push_endpoint": self.push_endpoint,
        }

    @staticmethod
    def from_record(rec: dict[str, Any]) -> "DeviceToken" | None:
        """Parse one stored record, or None if it is malformed.

        Returns None instead of raising so one corrupt entry cannot take down
        authentication for every other device.
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
                push_endpoint=(str(rec["push_endpoint"])
                               if isinstance(rec.get("push_endpoint"), str)
                               and rec.get("push_endpoint") else None),
            )
        except (KeyError, TypeError, ValueError):
            return None


def token_path() -> Path:
    """Full path to the token store."""
    return state_file(TOKEN_FILE_NAME)


class StoreUnreadable(Exception):
    """The token store exists but could not be read or parsed.

    Distinct from "there are no tokens": callers that are about to WRITE the
    store must refuse, because writing what they managed to read would delete
    everything they did not.
    """


def _read_all() -> list[DeviceToken]:
    """Load every readable token. Returns [] when the store is absent or broken.

    Falling back to "no tokens" denies token holders and Basic auth still
    works. Corrupt records are skipped. Never use this as the base of a
    read-modify-write (writing back deletes what it skipped); use
    _read_all_strict.
    """
    try:
        return _load_store()[0]
    except StoreUnreadable:
        return []


def _load_store() -> "tuple[list[DeviceToken], int]":
    """Load the store. Returns (tokens, number_of_unparseable_records).

    Raises StoreUnreadable when the FILE cannot be read or parsed at all. A
    missing file is a first run, so [] is honest.

    The dropped-record count is returned rather than raised because the two
    callers need opposite things from it: verification must still
    authenticate the readable records, while anything that writes the store
    back must refuse, or it would delete what it could not parse.

    Author: Bloodawn (KheivenD), 2026-07-19 (M3).
    """
    global _parsed_cache
    p = token_path()
    try:
        st = p.stat()
    except FileNotFoundError:
        return [], 0                    # first run: legitimately no tokens
    except OSError as exc:
        raise StoreUnreadable(f"cannot read {p}: {exc}") from exc
    key = (str(p), st.st_mtime_ns, st.st_size)
    cached = _parsed_cache
    if cached is not None and cached[0] == key:
        records = cached[1]
    else:
        try:
            text = p.read_text(encoding="utf-8")
        except FileNotFoundError:
            return [], 0
        except (OSError, UnicodeDecodeError) as exc:
            raise StoreUnreadable(f"cannot read {p}: {exc}") from exc
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as exc:
            raise StoreUnreadable(f"cannot parse {p}: {exc}") from exc
        if not isinstance(raw, dict):
            raise StoreUnreadable(f"{p} is not a JSON object")
        records = raw.get("tokens", []) or []
        _parsed_cache = (key, records)

    out: list[DeviceToken] = []
    dropped = 0
    for rec in records:
        parsed = DeviceToken.from_record(rec) if isinstance(rec, dict) else None
        if parsed is None:
            dropped += 1
        else:
            out.append(parsed)
    return out, dropped


def _read_all_strict() -> list[DeviceToken]:
    """Every token, or raise if rewriting the store would lose anything.

    Read-modify-write callers must use this. With the lenient reader, one
    transient read error (an antivirus or sync-client sharing violation on
    Windows) became a write holding only the new token and silently unpaired
    every other device (tests/test_device_tokens_durability.py).
    """
    tokens, dropped = _load_store()
    if dropped:
        raise StoreUnreadable(
            f"{dropped} unreadable token record(s) in {token_path()}; "
            "refusing to rewrite the store and delete them")
    return tokens


def _write_all(tokens: list[DeviceToken]) -> None:
    """Persist the token list atomically, owner-readable only where supported."""
    global _parsed_cache
    _parsed_cache = None
    p = token_path()
    payload = {
        "version": _SCHEMA_VERSION,
        "tokens": [t.to_record() for t in tokens],
    }
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        # No-op on Windows. The file holds only hashes, but there is no reason
        # to leave it world-readable.
        os.chmod(tmp, 0o600)
    except OSError:  # pragma: no cover - platform dependent
        pass
    os.replace(tmp, p)


def list_tokens() -> list[DeviceToken]:
    """Every stored token, including revoked and expired ones."""
    with _LOCK:
        return _read_all()


def mint_token(label: str, ttl_days: int | None = None) -> tuple[str, DeviceToken]:
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
        # Strict: appending to a partial read would delete the other devices.
        tokens = _read_all_strict()
        tokens.append(rec)
        _write_all(tokens)
    return secret, rec


def revoke_token(token_id: str) -> bool:
    """Revoke by id. True if a live token was revoked, False if unknown.

    Revocation is a tombstone, so the operator still sees the device and when
    it was last used.
    """
    with _LOCK:
        tokens = _read_all_strict()   # read-modify-write; see mint_token
        hit = False
        for t in tokens:
            if t.id == token_id and not t.revoked:
                t.revoked = True
                t.push_endpoint = None   # a revoked device gets no more alerts
                hit = True
        if hit:
            _write_all(tokens)
        return hit


def revoke_all() -> int:
    """Revoke every live token. Returns how many were revoked."""
    with _LOCK:
        tokens = _read_all_strict()   # read-modify-write; see mint_token
        n = 0
        for t in tokens:
            if not t.revoked:
                t.revoked = True
                t.push_endpoint = None
                n += 1
        if n:
            _write_all(tokens)
        return n


def verify_token(presented: str, touch: bool = True) -> DeviceToken | None:
    """Return the matching usable token, or None.

    Compares the SHA-256 of the presented value against every stored hash in
    constant time. Every candidate is compared even after a match so the loop
    does not leak, via timing, WHICH token matched or how many are stored.
    """
    if not presented or not presented.startswith(TOKEN_PREFIX):
        return None
    presented_hash = token_hash(presented).encode("ascii")
    with _LOCK:
        # An unreadable FILE denies. Corrupt records do not deny; they only
        # suppress the touch below, since rewriting the store would delete them.
        try:
            tokens, dropped = _load_store()
        except StoreUnreadable:
            return None
        found: DeviceToken | None = None
        for t in tokens:
            if hmac.compare_digest(presented_hash, t.sha256.encode("ascii")):
                if t.is_usable() and found is None:
                    found = t
        if found is not None and touch and not dropped:
            # Skipped when records were dropped: _write_all would delete them,
            # a far bigger loss than a missing last_used_at. The stamp has
            # one-second resolution and HLS authenticates every segment, so
            # only write when it actually moves.
            now = _utc_now_iso()
            if found.last_used_at != now:
                found.last_used_at = now
                _write_all(tokens)
        return found


def set_push_endpoint(token_id: str, endpoint: str | None) -> bool:
    """Set (or clear, with None) the push endpoint of ONE usable token.

    The caller passes the id of the token that authenticated the request,
    never an id taken from the request body, so one device cannot write
    another's endpoint. URL validation is the route's job. Returns False when
    the token is unknown or no longer usable.
    """
    with _LOCK:
        tokens = _read_all_strict()   # read-modify-write; see mint_token
        for t in tokens:
            if t.id == token_id and t.is_usable():
                t.push_endpoint = endpoint or None
                _write_all(tokens)
                return True
        return False


def get_push_endpoint(token_id: str) -> str | None:
    """The push endpoint of one usable token, or None."""
    for t in list_tokens():
        if t.id == token_id and t.is_usable():
            return t.push_endpoint
    return None


def push_targets() -> list[tuple]:
    """(token_id, endpoint) for every usable token that registered one.

    Revoked and expired devices are never included, even if a stale endpoint
    survived on disk.
    """
    return [(t.id, t.push_endpoint) for t in list_tokens()
            if t.is_usable() and t.push_endpoint]


def any_tokens_configured() -> bool:
    """True if at least one usable token exists."""
    return any(t.is_usable() for t in list_tokens())

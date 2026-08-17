"""
src/utils/integrity.py - tamper-evident output manifests (R5 TASK 5.8).

Every verified compressed output gets a SHA-256 entry appended to a
MANIFEST.sha256.jsonl in its output folder. Entries form a hash chain:
each entry's ``chain`` value commits to the previous entry's chain value,
its own file hash, and its filename, so editing or removing ANY earlier
line breaks verification of every line after it.

Honest scope: this is INTEGRITY (detects that a file or the manifest was
altered after recording), not AUTHENTICITY (it cannot prove who produced
the recording; that would need signing keys). State that plainly anywhere
this feature is surfaced.

Usage:
    from utils.integrity import append_manifest, verify_manifest
    append_manifest(output_dir, output_file)     # after ffprobe verification
    report = verify_manifest(output_dir)         # {"ok": bool, ...}

CLI:
    python -m utils.integrity verify <folder>    # exit 0 ok, 1 problems

Author: Bloodawn (KheivenD), 2026-08-16 (R5 TASK 5.8).
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

MANIFEST_NAME = "MANIFEST.sha256.jsonl"
_GENESIS = "0" * 64
_CHUNK = 1024 * 1024

# Appends from concurrent auto-compress passes must not interleave lines.
_append_lock = threading.Lock()


def file_sha256(path: Path) -> str:
    """Streaming SHA-256 of a file (hex). Raises OSError on unreadable input."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(_CHUNK)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def _chain_value(prev_chain: str, file_hash: str, name: str) -> str:
    """The chain commitment for one entry.

    Commits to the previous chain value, this file's hash, and its name, so
    reordering, editing, or deleting any earlier entry is detectable.
    """
    return hashlib.sha256(
        (prev_chain + file_hash + name).encode("utf-8")
    ).hexdigest()


def _manifest_path(directory: Path) -> Path:
    return Path(directory) / MANIFEST_NAME


def _read_entries(manifest: Path) -> list[dict]:
    entries: list[dict] = []
    try:
        text = manifest.read_text(encoding="utf-8")
    except OSError:
        return entries
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            # A syntactically broken line is itself manifest tampering; keep a
            # marker entry so verify can report the break at this position.
            obj = {"_malformed": True}
        entries.append(obj)
    return entries


def append_manifest(directory: Path, output_file: Path) -> Optional[dict]:
    """Record ``output_file`` in the folder manifest. Returns the entry.

    Best-effort by design: recording integrity metadata must never fail a
    compress that already succeeded, so any OSError returns None and the
    caller just logs it.
    """
    directory = Path(directory)
    output_file = Path(output_file)
    try:
        digest = file_sha256(output_file)
    except OSError:
        return None
    with _append_lock:
        manifest = _manifest_path(directory)
        entries = _read_entries(manifest)
        prev_chain = _GENESIS
        if entries:
            last = entries[-1]
            prev_chain = str(last.get("chain", _GENESIS))
        entry = {
            "file": output_file.name,
            "sha256": digest,
            "bytes": output_file.stat().st_size if output_file.exists() else 0,
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "prev": prev_chain,
            "chain": _chain_value(prev_chain, digest, output_file.name),
        }
        try:
            with open(manifest, "a", encoding="utf-8", newline="\n") as fh:
                fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
        except OSError:
            return None
    return entry


def verify_manifest(directory: Path) -> dict:
    """Re-check every manifest entry against the files on disk.

    Returns a report dict:
      ok               True only if everything below is clean
      entries          number of manifest entries
      bad_files        entries whose current file hash differs (tampered file)
      missing          entries whose file is gone
      chain_broken_at  first entry index (0-based) where the hash chain does
                       not verify (manifest itself edited/reordered), else None
    A folder with no manifest verifies ok with zero entries (nothing recorded,
    nothing to dispute).
    """
    directory = Path(directory)
    manifest = _manifest_path(directory)
    entries = _read_entries(manifest)
    report = {
        "ok": True,
        "entries": len(entries),
        "bad_files": [],
        "missing": [],
        "chain_broken_at": None,
    }
    prev_chain = _GENESIS
    for i, entry in enumerate(entries):
        name = str(entry.get("file", ""))
        recorded_hash = str(entry.get("sha256", ""))
        # Chain check first: it detects manifest edits even when files are fine.
        expected_chain = _chain_value(prev_chain, recorded_hash, name)
        if entry.get("_malformed") or entry.get("chain") != expected_chain:
            if report["chain_broken_at"] is None:
                report["chain_broken_at"] = i
            report["ok"] = False
            # Continue with the entry's own claimed chain so later independent
            # tampering is still surfaced rather than masked by one break.
            prev_chain = str(entry.get("chain", expected_chain))
        else:
            prev_chain = expected_chain
        target = directory / name
        if not name or not target.is_file():
            report["missing"].append(name or f"<entry {i}>")
            report["ok"] = False
            continue
        try:
            actual = file_sha256(target)
        except OSError:
            report["missing"].append(name)
            report["ok"] = False
            continue
        if actual != recorded_hash:
            report["bad_files"].append(name)
            report["ok"] = False
    return report


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entry: ``python -m utils.integrity verify <folder>``."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] != "verify":
        print("usage: python -m utils.integrity verify <folder>")
        return 2
    report = verify_manifest(Path(argv[1]))
    print(json.dumps(report, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

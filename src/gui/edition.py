"""
src/gui/edition.py

Build editions (R4 Phase 4): one codebase, two downloadable builds.

  * "server"  - the FULL dashboard: makes a server. LAN bind (with auth), the
                RTSP server (MediaMTX) + HLS live streaming TOOLS, ONVIF
                discovery, watch-folder automation, retention - everything.
  * "field"   - offline, LOCAL-COMPRESSION-ONLY for field use: force-bound to
                127.0.0.1 (never LAN, so no auth surface), the server-making
                features removed (no RTSP server, no HLS, the TOOLS tab hidden),
                telemetry forced off. Keeps upload / compress / library /
                auto-compress / retention / encrypt / plates / metrics.

Resolution order (first hit wins):
  1. the ``SVCS_EDITION`` environment variable ("server" | "field");
  2. a bundled ``edition.txt`` marker (the PyInstaller spec writes one into the
     frozen bundle, read via ``sys._MEIPASS`` / ``SVCS_BUNDLE_ROOT``);
  3. default "server" (so source runs and existing tests are unchanged).

Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 4 - server/field split).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

EDITION_SERVER = "server"
EDITION_FIELD = "field"
_VALID = {EDITION_SERVER, EDITION_FIELD}


def _read_marker() -> str:
    """Read the bundled edition marker, or "" if none/unreadable."""
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(Path(meipass))
    bundle = os.environ.get("SVCS_BUNDLE_ROOT")
    if bundle:
        roots.append(Path(bundle))
    # Source-tree fallback (repo root: this file is src/gui/edition.py).
    roots.append(Path(__file__).resolve().parents[2])
    for r in roots:
        try:
            txt = (r / "edition.txt").read_text(encoding="utf-8").strip().lower()
            if txt in _VALID:
                return txt
        except (OSError, ValueError):
            continue
    return ""


def get_edition() -> str:
    """Return the active edition: "server" (default) or "field"."""
    env = (os.environ.get("SVCS_EDITION") or "").strip().lower()
    if env in _VALID:
        return env
    marker = _read_marker()
    if marker in _VALID:
        return marker
    return EDITION_SERVER


def is_field(edition: str | None = None) -> bool:
    return (edition or get_edition()) == EDITION_FIELD


def is_server(edition: str | None = None) -> bool:
    return (edition or get_edition()) == EDITION_SERVER


def server_features_enabled(edition: str | None = None) -> bool:
    """True when the server-making surfaces (RTSP server, HLS, TOOLS, LAN bind)
    are available. False in the field build."""
    return not is_field(edition)


def edition_label(edition: str | None = None) -> str:
    """Human-readable build name for banners / the UI."""
    return "Field (offline)" if is_field(edition) else "Server"

"""
src/gui/services/rtsp.py

Local RTSP (MediaMTX) server manager singleton, extracted from gui/app.py
(TASK 1.2).

The /api/rtsp/* routes (still in app.py until TASK 1.3) drive this single
``_rtsp_mgr`` instance: download the MediaMTX binary, start/stop the server,
and push a looping file into it for demo streaming. The manager itself lives
in utils.rtsp_server; this module just owns the process-wide singleton so the
routes and the rest of the GUI share one server handle.

`_ROOT` is computed locally from __file__ (repo root) for the tools/ dir.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — rtsp-singleton extraction).
"""

from pathlib import Path

try:
    from utils.rtsp_server import RtspServerManager
    from utils import paths as _paths
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.utils.rtsp_server import RtspServerManager
    from src.utils import paths as _paths

# Repo root (…/src/gui/services/rtsp.py -> parents[3]); the legacy tools/ dir.
_ROOT = Path(__file__).resolve().parents[3]

# FIX 5: download MediaMTX into a WRITABLE per-user tools dir (works in a
# read-only Program Files install), but still detect an existing binary in the
# legacy repo tools/ dir, the frozen bundle, or on PATH (handled by the manager).
_rtsp_mgr = RtspServerManager(
    tools_dir=_paths.tools_dir(),
    extra_search_dirs=[_ROOT / "tools"],
)

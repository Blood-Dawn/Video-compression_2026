"""
src/gui/services/gui_state_persist.py

Tiny on-disk persistence of the dashboard's last-known output roots,
extracted from gui/app.py (TASK 1.2).

After a server restart the in-memory _status["config"]["output_dir"] and
_demo_state["last_output_root"] are blank, so /api/segments would only walk
<repo>/outputs/. If the user's last pipeline run or demo wrote to OneDrive/SVCS
or another folder, those segments would become invisible even though the files
still exist. We store the last-known roots in a tiny JSON next to the Flask
secret so they survive a restart. No secrets in this file — just paths.

Imports gui.state (the shared status/demo dicts + their locks) and utils.paths.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — state-persist extraction).
"""

import json
import time

try:
    from gui.state import _state_lock, _status, _demo_lock, _demo_state
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.gui.state import _state_lock, _status, _demo_lock, _demo_state

try:
    from utils import paths as _paths
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.utils import paths as _paths

# Author: Bloodawn (KheivenD), 2026-05-14 (installer prep, was 2026-05-04).
_GUI_STATE_FILE = _paths.state_file("gui_state.json")


def _load_gui_state() -> None:
    """Seed _status['config'] and _demo_state['last_output_root'] from disk."""
    try:
        if not _GUI_STATE_FILE.exists():
            return
        data = json.loads(_GUI_STATE_FILE.read_text())
        if not isinstance(data, dict):
            return
        out_dir = data.get("output_dir") or ""
        demo_root = data.get("last_demo_output_root") or ""
        if out_dir:
            with _state_lock:
                # Only seed config.output_dir if nothing real has set it yet.
                cfg = _status.setdefault("config", {})
                cfg.setdefault("output_dir", str(out_dir))
        if demo_root:
            with _demo_lock:
                _demo_state.setdefault("last_output_root", str(demo_root))
    except Exception:  # noqa: BLE001
        pass


def _save_gui_state() -> None:
    """Snapshot the current output_dir + last_demo_output_root to disk."""
    try:
        with _state_lock:
            cfg = _status.get("config", {})
            out_dir = cfg.get("output_dir", "")
        with _demo_lock:
            demo_root = _demo_state.get("last_output_root", "")
        payload = {
            "output_dir": str(out_dir or ""),
            "last_demo_output_root": str(demo_root or ""),
            "saved_at": time.time(),
        }
        _GUI_STATE_FILE.write_text(json.dumps(payload, indent=2))
    except Exception:  # noqa: BLE001
        # Persistence is best effort. Never block a route on it.
        pass

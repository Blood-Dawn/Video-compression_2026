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
    """Seed _status['config'] and _demo_state['last_output_root'] from disk.

    FIX 1: also restores the explicit destination choice - the output_dir,
    the encrypted-output dir, and whether the first-run Setup was completed -
    so the app does not re-prompt every launch and never re-derives a cloud
    default on its own.
    """
    try:
        if not _GUI_STATE_FILE.exists():
            return
        data = json.loads(_GUI_STATE_FILE.read_text())
        if not isinstance(data, dict):
            return
        out_dir = data.get("output_dir") or ""
        enc_dir = data.get("encrypted_dir") or ""
        setup_done = bool(data.get("setup_complete", False))
        demo_root = data.get("last_demo_output_root") or ""
        with _state_lock:
            cfg = _status.setdefault("config", {})
            if out_dir:
                # Only seed config.output_dir if nothing real has set it yet.
                cfg.setdefault("output_dir", str(out_dir))
            if enc_dir:
                cfg.setdefault("encrypted_dir", str(enc_dir))
            _status.setdefault("setup_complete", setup_done)
        if demo_root:
            with _demo_lock:
                _demo_state.setdefault("last_output_root", str(demo_root))
    except Exception:  # noqa: BLE001
        pass


def _save_gui_state() -> None:
    """Snapshot output_dir + encrypted_dir + setup flag + demo root to disk."""
    try:
        with _state_lock:
            cfg = _status.get("config", {})
            out_dir = cfg.get("output_dir", "")
            enc_dir = cfg.get("encrypted_dir", "")
            setup_done = bool(_status.get("setup_complete", False))
        with _demo_lock:
            demo_root = _demo_state.get("last_output_root", "")
        payload = {
            "output_dir": str(out_dir or ""),
            "encrypted_dir": str(enc_dir or ""),
            "setup_complete": setup_done,
            "last_demo_output_root": str(demo_root or ""),
            "saved_at": time.time(),
        }
        _GUI_STATE_FILE.write_text(json.dumps(payload, indent=2))
    except Exception:  # noqa: BLE001
        # Persistence is best effort. Never block a route on it.
        pass


def save_setup_choice(output_dir: str, encrypted_dir: str = "") -> None:
    """Record the user's explicit destination choice and mark Setup complete.

    Stores the chosen output_dir (and optional encrypted_dir) into the live
    config and flips ``setup_complete`` so the first-run Setup page is not shown
    again. Persists immediately.
    """
    out = (output_dir or "").strip()
    enc = (encrypted_dir or "").strip()
    with _state_lock:
        cfg = _status.setdefault("config", {})
        if out:
            cfg["output_dir"] = out
        cfg["encrypted_dir"] = enc
        _status["setup_complete"] = True
    _save_gui_state()


def is_setup_complete() -> bool:
    """True once the user has made an explicit destination choice."""
    with _state_lock:
        return bool(_status.get("setup_complete", False))

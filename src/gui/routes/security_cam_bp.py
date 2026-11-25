"""
src/gui/routes/security_cam_bp.py

Security cam: a paired phone records short clips and uploads them to this
desktop, and the desktop compresses whatever arrives.

The phone never streams video. Each finished clip goes through the existing
chunked, resumable upload (``/api/upload/*``, over the paired network link, not
Bluetooth). When "receiving" is on, the auto-compress daemon watches the upload
folder with the mode chosen here and writes results under ``compressed/``.

  GET  /api/security-cam   settings, receiving state, paired phones, recent clips.
                           Open to a paired phone so it can read its segment length.
  POST /api/security-cam   {enabled?, segment_seconds?, mode?}. Dashboard password
                           only: a phone cannot switch the desktop's recording on.

Recent clips carry real source and output sizes from the shared result
algorithm (utils/result_numbers.py), the same numbers the Home page shows.

Author: Bloodawn (KheivenD), 2026-11-23 (demo branch, task 13.1).
"""

import json
from pathlib import Path

from flask import Blueprint, Response, jsonify, request

try:
    from gui import device_tokens
    from gui.auth import SCHEME_BEARER, current_auth_scheme
    from gui.logging_setup import log
    from gui.routes.files_bp import _upload_dir
    from gui.routes.savings_bp import _output_size, _parse_source_size, _result_block
    from gui.services import autocompress_runner as ac
    from gui.services import security_alerts
    from utils import compressed_index as _cidx
    from utils.paths import state_file
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui import device_tokens
    from src.gui.auth import SCHEME_BEARER, current_auth_scheme
    from src.gui.logging_setup import log
    from src.gui.routes.files_bp import _upload_dir
    from src.gui.routes.savings_bp import _output_size, _parse_source_size, _result_block
    from src.gui.services import autocompress_runner as ac
    from src.gui.services import security_alerts
    from src.utils import compressed_index as _cidx
    from src.utils.paths import state_file

security_cam_bp = Blueprint("security_cam", __name__)

SETTINGS_FILE = "security_cam.json"
SEGMENT_CHOICES = (60, 300, 600, 900, 1800)   # 1, 5, 10, 15, 30 minutes
MODES = ("mode0", "mode1", "mode2", "mode3")
DEFAULTS = {"segment_seconds": 300, "mode": "mode0"}
RECENT_LIMIT = 10


def load_settings() -> dict:
    """Saved settings, with anything missing or invalid replaced by the default."""
    try:
        raw = json.loads(state_file(SETTINGS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = {}
    out = dict(DEFAULTS)
    if raw.get("segment_seconds") in SEGMENT_CHOICES:
        out["segment_seconds"] = raw["segment_seconds"]
    if raw.get("mode") in MODES:
        out["mode"] = raw["mode"]
    return out


def _save_settings(settings: dict) -> None:
    try:
        state_file(SETTINGS_FILE).write_text(json.dumps(settings), encoding="utf-8")
    except OSError as exc:
        log.warning("Security cam settings not saved: %s", exc)


def _same_folder(a: str, b: Path) -> bool:
    try:
        return bool(a) and Path(a).resolve() == b.resolve()
    except OSError:
        return False


def _receiving(folder: Path) -> bool:
    """True when auto compress is running on the phone upload folder."""
    snap = ac.get_status()
    return bool(snap.get("running")) and _same_folder(snap.get("folder", ""), folder)


def _phones() -> list:
    out = []
    for t in device_tokens.list_tokens():
        if t.is_usable():
            pub = t.to_public()
            out.append({"id": pub["id"], "label": pub["label"],
                        "last_seen": pub["last_used_at"]})
    return out


def _clip_row(entry: dict, folder: Path):
    """One recent clip with real sizes, or None if it is not a Security cam clip."""
    source = (entry or {}).get("source") or ""
    if not _same_folder(str(Path(source).parent), folder):
        return None
    try:
        on_disk = Path(entry["output"]).stat().st_size
    except (KeyError, OSError, ValueError):
        return None
    src_bytes = _parse_source_size(entry.get("signature") or "")
    if src_bytes <= 0 or on_disk <= 0:
        return None
    row = {"name": Path(source).name, "when": float(entry.get("when") or 0)}
    row.update(_result_block(src_bytes, _output_size(entry, on_disk)))
    return row


def recent_clips(folder: Path, limit: int = RECENT_LIMIT) -> list:
    try:
        entries = list((_cidx._load().get("entries", {}) or {}).values())
    except Exception:  # noqa: BLE001 - a broken index must not 500 the tab
        entries = []
    rows = [r for r in (_clip_row(e, folder) for e in entries) if r]
    rows.sort(key=lambda r: r["when"], reverse=True)
    return rows[:limit]


def _snapshot() -> dict:
    folder = _upload_dir()
    return {
        **load_settings(),
        "segment_choices": list(SEGMENT_CHOICES),
        "receiving": _receiving(folder),
        "watch_folder": str(folder),
        "phones": _phones(),
        "recent": recent_clips(folder),
        "alerts": security_alerts.recent_alerts(),
    }


@security_cam_bp.route("/api/security-cam", methods=["GET"])
def api_security_cam_get():
    return jsonify(_snapshot())


def _start_receiving(folder: Path, mode: str):
    """Start auto compress on the upload folder. Returns an error string or None."""
    if _receiving(folder):
        return None
    folder.mkdir(parents=True, exist_ok=True)
    started = ac.start_autocompress({
        "folder": str(folder), "output_dir": str(_output_root()), "mode": mode,
        "preset": None, "profile": None, "delete_original": False, "poll_interval": 10,
    })
    if started:
        return None
    return ("Auto compress is already watching another folder. "
            "Turn it off in the Auto compress tab first.")


def _output_root() -> Path:
    try:
        from gui.services.cloud_detection import _default_output_dir
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.services.cloud_detection import _default_output_dir
    return Path(_default_output_dir())


def _apply_settings(body: dict) -> str:
    """Validate and save settings from a POST body. Returns an error or ''."""
    settings = load_settings()
    if "segment_seconds" in body:
        if body["segment_seconds"] not in SEGMENT_CHOICES:
            return "segment_seconds must be 60, 300, 600, 900 or 1800."
        settings["segment_seconds"] = body["segment_seconds"]
    if "mode" in body:
        if body["mode"] not in MODES:
            return "mode must be mode0, mode1, mode2 or mode3."
        settings["mode"] = body["mode"]
    _save_settings(settings)
    return ""


@security_cam_bp.route("/api/security-cam", methods=["POST"])
def api_security_cam_post():
    if current_auth_scheme() == SCHEME_BEARER:
        return Response('{"error": "Changing Security cam needs the dashboard password, '
                        'not a device token."}', 403, {"Content-Type": "application/json"})
    body = request.get_json(silent=True) or {}
    error = _apply_settings(body)
    if error:
        return jsonify({"ok": False, "error": error}), 400
    folder = _upload_dir()
    if body.get("enabled") is True:
        error = _start_receiving(folder, load_settings()["mode"])
        if error:
            return jsonify({"ok": False, "error": error, **_snapshot()}), 409
    elif body.get("enabled") is False and _receiving(folder):
        ac.stop_autocompress()
    return jsonify({"ok": True, **_snapshot()})

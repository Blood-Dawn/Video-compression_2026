"""
src/gui/routes/demo_bp.py

demo routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

import threading
import json
from pathlib import Path
from urllib.parse import quote
from flask import Blueprint, jsonify, request

try:
    from gui.state import (_state_lock, _status, _demo_lock, _demo_state, _hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies, _CLOUD_SUBFOLDER)
    from gui.services.cloud_detection import _default_output_dir, _detect_onedrive_root
    from gui.services.gui_state_persist import _save_gui_state
    from gui.services.demo_runner import _run_demo_thread
    from gui.services import hls_runner as _hls_runner
    from gui.services.hls_runner import _hls_dir_for, _hls_annotator_thread
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_state_lock, _status, _demo_lock, _demo_state, _hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies, _CLOUD_SUBFOLDER)
    from src.gui.services.cloud_detection import _default_output_dir, _detect_onedrive_root
    from src.gui.services.gui_state_persist import _save_gui_state
    from src.gui.services.demo_runner import _run_demo_thread
    from src.gui.services import hls_runner as _hls_runner
    from src.gui.services.hls_runner import _hls_dir_for, _hls_annotator_thread

# Repo root (…/src/gui/routes/<bp>_bp.py -> parents[3]).
_ROOT = Path(__file__).resolve().parents[3]

demo_bp = Blueprint("demo", __name__)

@demo_bp.route("/api/demo", methods=["POST"])
def api_demo():
    """Start a multi-mode demo run in the background.

    POST body (JSON):
        input_path   – path to source video
        output_root  – root directory for demo outputs
        camera_id    – camera identifier
        modes        – list of mode strings, e.g. ["mode0", "mode1", "mode2", "mode3"]
        views        – list of view strings (default ["standard"])
        no_boxes     – bool, suppress ROI box overlays (default false)
        no_tint      – bool, suppress ROI tint overlays (default false)
    """
    with _demo_lock:
        if _demo_state["running"]:
            return jsonify({"error": "Demo already running"}), 409

    data = request.get_json(force=True) or {}

    input_path = data.get("input_path", "").strip()
    output_root = data.get("output_root", "").strip()
    if not output_root:
        # Unified default — same OneDrive-preferred resolution as api_start
        # and api_hls_start. Author: Bloodawn (KheivenD), 2026-05-02 audit.
        output_root = _default_output_dir()
    modes = data.get("modes", ["mode0", "mode1", "mode2", "mode3"])

    if not input_path:
        return jsonify({"error": "input_path is required"}), 400
    if not modes:
        return jsonify({"error": "at least one mode is required"}), 400

    config = {
        "input_path": input_path,
        "output_root": output_root,
        "camera_id": data.get("camera_id", "cam_00"),
        "modes": modes,
        "views": data.get("views", ["standard"]),
        "no_boxes": bool(data.get("no_boxes", False)),
        "no_tint": bool(data.get("no_tint", False)),
    }

    resolved_root = str(Path(output_root).resolve())
    with _demo_lock:
        _demo_state.update(running=True, modes=modes, result=None, error=None, status="queued",
                           last_output_root=resolved_root)

    # Persist the demo output root so /api/segments can still find these
    # files after a server restart.
    _save_gui_state()

    t = threading.Thread(target=_run_demo_thread, args=(config,), daemon=True, name="demo-worker")
    t.start()

    return jsonify({"ok": True, "modes": modes})


@demo_bp.route("/api/demo/status")
def api_demo_status():
    """Return the current state of the background demo run."""
    with _demo_lock:
        return jsonify(dict(_demo_state))


@demo_bp.route("/api/demo/search_debug")
def api_demo_search_debug():
    """Diagnostic: show which roots are searched and what manifests are found."""
    with _state_lock:
        cfg = _status.get("config", {})
    with _demo_lock:
        last_demo_root = _demo_state.get("last_output_root", "")

    roots_info = []
    for label, raw in [
        ("pipeline output_dir", cfg.get("output_dir", "")),
        ("project outputs/", str(_ROOT / "outputs")),
        ("last demo root", last_demo_root),
    ]:
        if not raw:
            continue
        p = Path(raw).resolve()
        roots_info.append({"label": label, "path": str(p), "exists": p.exists()})

    try:
        od_root, od_label = _detect_onedrive_root(prefer_business=True)
        if od_root:
            svcs = (od_root / _CLOUD_SUBFOLDER).resolve()
            roots_info.append({"label": f"OneDrive SVCS ({od_label})", "path": str(svcs), "exists": svcs.exists()})
            roots_info.append({"label": f"OneDrive root ({od_label})", "path": str(od_root.resolve()), "exists": od_root.exists()})
    except Exception as e:
        roots_info.append({"label": "OneDrive detection error", "path": str(e), "exists": False})

    manifests_found = []
    for ri in roots_info:
        if not ri["exists"]:
            continue
        root = Path(ri["path"])
        for pattern in ["demo_comp*/manifest.json", "demo_comp/demos_stitched*/manifest.json"]:
            for mp in root.glob(pattern):
                manifests_found.append({
                    "root": ri["path"],
                    "manifest": str(mp),
                    "exists": mp.exists(),
                    "mtime": mp.stat().st_mtime if mp.exists() else None,
                })

    return jsonify({"roots": roots_info, "manifests": manifests_found})


@demo_bp.route("/api/demo/history")
def api_demo_history():
    """List previous demo runs by scanning for demo_comp*/manifest.json files.

    Returns a list of run objects (newest first), each with:
      ts, modes, split_screen (URL or None), videos {mode: {view: url}}, dir (folder name)
    """
    # Build a de-duplicated list of roots to search for manifests.
    # Priority: pipeline output_dir → project outputs/ → last demo run root → OneDrive SVCS
    with _state_lock:
        cfg = _status.get("config", {})
    with _demo_lock:
        last_demo_root = _demo_state.get("last_output_root", "")

    seen_roots: set[Path] = set()
    search_roots: list[Path] = []

    def _add_root(p: Path) -> None:
        rp = p.resolve()
        if rp not in seen_roots and rp.exists():
            seen_roots.add(rp)
            search_roots.append(rp)

    # 1. Pipeline-configured output dir (set when user configures the pipeline)
    if cfg.get("output_dir"):
        _add_root(Path(cfg["output_dir"]))
    # 2. Project-relative outputs/ folder (safe absolute reference via _ROOT)
    _add_root(_ROOT / "outputs")
    # 3. Last demo run's output root (captured when demo was started)
    if last_demo_root:
        _add_root(Path(last_demo_root))
    # 4. OneDrive SVCS folder
    try:
        od_root, _ = _detect_onedrive_root(prefer_business=True)
        if od_root:
            _add_root(od_root / _CLOUD_SUBFOLDER)
            # Also search OneDrive root directly (catches non-SVCS outputs)
            _add_root(od_root)
    except Exception:
        pass

    manifests: list[tuple[float, Path]] = []
    seen: set[Path] = set()
    for root in search_roots:
        # New-style: <root>/demo_comp_N/manifest.json
        for mp in root.glob("demo_comp*/manifest.json"):
            if mp not in seen:
                seen.add(mp)
                try:
                    manifests.append((mp.stat().st_mtime, mp))
                except OSError:
                    pass
        # Old-style: <root>/demo_comp/demos_stitched_N/manifest.json
        for mp in root.glob("demo_comp/demos_stitched*/manifest.json"):
            if mp not in seen:
                seen.add(mp)
                try:
                    manifests.append((mp.stat().st_mtime, mp))
                except OSError:
                    pass

    manifests.sort(key=lambda x: x[0], reverse=True)  # newest first

    runs = []
    for mtime, mp in manifests:
        try:
            with open(mp, encoding="utf-8") as f:
                manifest = json.load(f)
        except Exception:
            continue

        videos: dict = {}
        for mode, view_map in manifest.get("outputs", {}).items():
            videos[mode] = {}
            for view, file_path in view_map.items():
                p = Path(file_path).resolve()
                videos[mode][view] = f"/api/media?path={quote(str(p))}" if p.exists() else None

        split_screen_url = None
        sd = Path(manifest.get("stitched_dir", ""))
        if sd.exists():
            for c in sd.glob("demo_splitscreen*.mp4"):
                split_screen_url = f"/api/media?path={quote(str(c.resolve()))}"
                break

        runs.append({
            "ts":           mtime,
            "modes":        manifest.get("modes", []),
            "split_screen": split_screen_url,
            "videos":       videos,
            "dir":          mp.parent.name,
        })

    return jsonify(runs)


# ── HLS live streaming (task 4.1) ────────────────────────────────────────────
#
# Architecture:
#   Input → OpenCV VideoCapture → BackgroundSubtractor → ROI boxes + corner
#   overlay drawn on each frame → rawvideo piped to FFmpeg stdin → .m3u8 + .ts
#   → Flask serves /api/hls/<camera_id>/ → hls.js plays in browser
#
# Frames are annotated in Python before encoding so the live stream shows
# the same green ROI bounding boxes as the demo comparison output.

# _hls_lock / _hls_state and the latency deques (_hls_frame_ts_dq /
# _hls_segment_latencies) live in gui.state. The rebindable process/thread
# handles (_hls_process / _hls_thread / _hls_stop_event) and the annotator
# worker now live in gui.services.hls_runner; the handles are forwarded from
# this module (see _FORWARDED_GLOBALS) so the /api/hls/* routes and the test
# suite (which sets gui_module._hls_process = None) share one live value.
try:
    from gui.services import hls_runner as _hls_runner
    from gui.services.hls_runner import _hls_dir_for, _hls_annotator_thread
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.services import hls_runner as _hls_runner
    from src.gui.services.hls_runner import _hls_dir_for, _hls_annotator_thread



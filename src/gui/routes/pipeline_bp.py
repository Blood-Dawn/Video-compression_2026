"""
src/gui/routes/pipeline_bp.py

Pipeline control: status, recent jobs, start and stop.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

import math
import re
import threading
import time
import uuid as _uuid
from pathlib import Path

from flask import Blueprint, jsonify, request

try:
    from gui.state import (_state_lock, _status)
    from gui.logging_setup import log
    from gui.services.path_safety import (_safe_output_dir, is_safe_input_source,
                                          redact_input_source)
    from gui.services.cloud_detection import _default_output_dir
    from gui.services import pipeline_runner as _pipeline_runner
    from gui.services import job_history as _job_history
    from gui.services.pipeline_runner import _run_pipeline_thread
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_state_lock, _status)
    from src.gui.logging_setup import log
    from src.gui.services.path_safety import (_safe_output_dir,
                                              is_safe_input_source,
                                              redact_input_source)
    from src.gui.services.cloud_detection import _default_output_dir
    from src.gui.services import pipeline_runner as _pipeline_runner
    from src.gui.services import job_history as _job_history
    from src.gui.services.pipeline_runner import _run_pipeline_thread

pipeline_bp = Blueprint("pipeline", __name__)

_CAMERA_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
_LIVE_URL_RE = re.compile(r"^(rtsp|rtsps|rtmp|http|https)://", re.I)

# Supported VMAF target band, taken from the search module so the route and the
# searcher cannot drift apart.
try:
    from compression.vmaf_target import TARGET_VMAF_MIN as _TARGET_VMAF_MIN
    from compression.vmaf_target import TARGET_VMAF_MAX as _TARGET_VMAF_MAX
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.compression.vmaf_target import TARGET_VMAF_MIN as _TARGET_VMAF_MIN
    from src.compression.vmaf_target import TARGET_VMAF_MAX as _TARGET_VMAF_MAX


def _clamp_int(value, default: int, lo: int, hi: int) -> int:
    """Coerce ``value`` to an int in [lo, hi], or ``default`` if unparseable.

    Sanitises encoder knobs from the request body so a bad or oversized value
    never reaches the FFmpeg command line.
    """
    try:
        s = str(value).strip()
        if s == "" or value is None:
            return default
        f = float(s)
        # int(float("inf")) raises OverflowError, and nan has no int at all.
        if not math.isfinite(f):
            return default
        return max(lo, min(hi, int(f)))
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp_float_or_none(value, lo: float, hi: float):
    """Coerce ``value`` to a float in [lo, hi], or None when unset/unparseable.

    target_vmaf is optional: None means "keep the fixed CRF", so an absent or
    garbage value (including inf/nan) resolves to None, never a 500.
    """
    try:
        if value is None:
            return None
        s = str(value).strip()
        if s == "":
            return None
        f = float(s)
        if not math.isfinite(f):
            return None
        return max(lo, min(hi, f))
    except (TypeError, ValueError, OverflowError):
        return None


@pipeline_bp.route("/api/status")
def api_status():
    with _state_lock:
        snap = dict(_status)

    elapsed = None
    fps = None
    progress_pct = None
    eta_seconds = None
    if snap["start_time"] and snap["running"]:
        elapsed = round(time.time() - snap["start_time"], 1)
        fc = snap["frame_count"]
        fps = round(fc / elapsed, 1) if elapsed > 0 else 0.0
        total = snap.get("total_frames", 0)
        if total and total > 0:
            progress_pct = round(min(fc / total * 100, 100), 1)
            remaining_frames = max(0, total - fc)
            eta_seconds = round(remaining_frames / fps, 0) if fps and fps > 0 else None

    # input_source can be an RTSP URL carrying the camera's password. The
    # snapshot is a shallow copy, so copy config before redacting or this would
    # scrub the URL the running pipeline needs.
    cfg = snap.get("config")
    if isinstance(cfg, dict) and cfg.get("input_source") is not None:
        cfg = dict(cfg)
        cfg["input_source"] = redact_input_source(cfg["input_source"])
        snap["config"] = cfg

    return jsonify({
        **snap,
        "elapsed_seconds": elapsed,
        "fps": fps,
        "progress_pct": progress_pct,
        "eta_seconds": int(eta_seconds) if eta_seconds is not None else None,
    })


@pipeline_bp.route("/api/jobs/recent")
def api_jobs_recent():
    """Recent finished jobs (manual runs + auto-compress batches), newest first.

    A persistent job record the operator can audit later; also feeds the
    completion-summary modal. ?limit=N caps the list (default 20).
    """
    limit = request.args.get("limit", 20, type=int)
    return jsonify({"jobs": _job_history.recent_jobs(limit=limit)})


@pipeline_bp.route("/api/start", methods=["POST"])
def api_start():
    # _pipeline_thread / _stop_event live in pipeline_runner; assign through
    # that module so the forwarder and /api/stop see them.
    with _state_lock:
        if _status["running"]:
            return jsonify({"error": "Pipeline already running"}), 409

    data = request.get_json(force=True) or {}

    camera_id = str(data.get("camera_id", "cam_00")).strip()
    if not _CAMERA_ID_RE.match(camera_id):
        return jsonify({"error": "camera_id must be 1-64 alphanumeric/dash/underscore chars"}), 400

    # A digit string is a camera index, anything else a path or URL.
    raw_input = str(data.get("input_source", "0")).strip()
    try:
        resolved_input = int(raw_input)
    except ValueError:
        resolved_input = raw_input
        # SEC-013: block file:// and cloud-metadata/link-local SSRF targets
        # (cv2.VideoCapture would otherwise open them).
        _ok, _why = is_safe_input_source(resolved_input)
        if not _ok:
            return jsonify({"error": f"input_source not allowed: {_why}"}), 400

    # Default output dir: the folder chosen in Setup, else a local default;
    # never an implicit cloud folder (see _default_output_dir).
    # Author: Bloodawn (KheivenD), 2026-05-02.
    raw_out = data.get("output_dir", "").strip() or _default_output_dir()
    try:
        output_dir = str(_safe_output_dir(raw_out))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    encrypt_key_file = (data.get("encrypt_key_file") or "").strip() or None
    if encrypt_key_file:
        kf = Path(encrypt_key_file).resolve()
        if not kf.exists():
            return jsonify({"error": f"encrypt_key_file not found: {kf}"}), 400
        if not kf.is_file():
            return jsonify({"error": "encrypt_key_file must be a regular file"}), 400
        encrypt_key_file = str(kf)

    # Reject encrypt=True with no credential: otherwise the encoder writes
    # plaintext while the dashboard's ENCRYPT chip claims it is encrypted.
    encrypt_password = (data.get("encrypt_password") or "").strip()
    if bool(data.get("encrypt", False)) and not encrypt_password and not encrypt_key_file:
        return jsonify({
            "error": "encrypt requires encrypt_password or encrypt_key_file "
                     "(a run would otherwise silently write unencrypted output)"
        }), 400

    # A live camera/stream defaults to 10 min segments, a file to 60 s. Only
    # when the caller omits segment_seconds; an explicit value always wins.
    _is_live_input = isinstance(resolved_input, int) or (
        isinstance(resolved_input, str) and bool(_LIVE_URL_RE.match(resolved_input))
    )
    _default_segment_seconds = 600 if _is_live_input else 60

    config = {
        "input_source": resolved_input,
        "camera_id": camera_id,
        "output_dir": output_dir,
        "segment_seconds": data.get("segment_seconds", _default_segment_seconds),
        "bg_method": data.get("bg_method", "MOG2"),
        "warmup_frames": data.get("warmup_frames", 120),
        "mode": data.get("mode", "mode0"),
        "enhance": bool(data.get("enhance", False)),
        "enhance_model": data.get("enhance_model", "bicubic"),
        "enhance_scale": data.get("enhance_scale", 4),
        "enhance_every_n": int(data.get("enhance_every_n", 5)),
        "enhance_max_roi_px": int(data.get("enhance_max_roi_px", 200)),
        "enhance_device": data.get("enhance_device", "auto"),
        "upscale_output": bool(data.get("upscale_output", False)),
        "encrypt": bool(data.get("encrypt", False)),
        "encrypt_password": data.get("encrypt_password", ""),
        "encrypt_key_file": encrypt_key_file,
        "object_filter": bool(data.get("object_filter", False)),
        "filter_confidence": float(data.get("filter_confidence", 0.30)),
        # Codec: "auto" (default; libx264 for mode0/mode1, libsvtav1 for
        # mode2/mode3 via config.default_codec_for_mode), "libsvtav1",
        # "libaom-av1" (slower reference AV1) or "libx264". H.265/HEVC is not
        # offered (patent licensing). ROIEncoder falls back to libx264 if the
        # chosen encoder is missing from the ffmpeg build.
        # Author: Bloodawn (KheivenD), 2026-05-03.
        "codec": str(data.get("codec", "auto") or "auto").strip(),
        # Foreground CRF. None means the mode default (18 for Mode 0/1/2, 38
        # for Mode 3). Lower = better quality, larger file.
        # Author: Bloodawn (KheivenD), 2026-05-02 (Mode 3 redo).
        "crf": (int(data.get("crf")) if str(data.get("crf", "")).strip() else None),
        # background_crf drives the dual-CRF background stream (None keeps the
        # encoder default); preset names the surveillance preset the config
        # came from (informational).
        "background_crf": (int(data.get("background_crf"))
                           if str(data.get("background_crf", "")).strip() else None),
        "preset": (str(data.get("preset")).strip() or None) if data.get("preset") else None,
        "verbose": bool(data.get("verbose", False)),
        # Storage cap (capped CRF), 0 = uncapped.
        "max_bitrate_kbps": _clamp_int(data.get("max_bitrate_kbps"), 0, 0, 200000),
        # Pre-encode denoiser for night/IR footage: "", "hqdn3d", "atadenoise"
        # (the encoder drops anything else).
        "denoise": (str(data.get("denoise", "")).strip().lower()
                    if data.get("denoise") else ""),
        # Encoder-level ROI (x264/x265 only), opt-in.
        "roi_qp": bool(data.get("roi_qp", False)),
        # Keyframe interval in seconds (long GOP for static cameras); 0 keeps
        # the FFmpeg default.
        "gop_seconds": _clamp_int(data.get("gop_seconds"), 20, 0, 600),
        # VMAF-targeted rate control: None keeps the fixed-CRF path, a value
        # is clamped into the supported band (docs/RESEARCH-VMAF-TARGET.md).
        "target_vmaf": _clamp_float_or_none(
            data.get("target_vmaf"), _TARGET_VMAF_MIN, _TARGET_VMAF_MAX),
    }

    # A job id clients can correlate across /api/status and /api/jobs/recent.
    config["job_id"] = _uuid.uuid4().hex[:12]

    # Claim the single job slot atomically. The early check is only a fast
    # fail: two near-simultaneous POSTs (a phone retrying) can both pass it, so
    # the re-check and the claim happen under one lock.
    # Author: Bloodawn (KheivenD), 2026-08-16 (M4 job registry + TOCTOU).
    new_stop = threading.Event()
    worker = threading.Thread(
        target=_run_pipeline_thread,
        args=(config, new_stop),
        daemon=True,
        name="pipeline-worker",
    )
    with _state_lock:
        if _status["running"] or (
            _pipeline_runner._pipeline_thread is not None
            and _pipeline_runner._pipeline_thread.is_alive()
        ):
            return jsonify({"error": "Pipeline already running"}), 409
        _status["running"] = True          # claim the single job slot
        _status["error"] = None
        _status["job_id"] = config["job_id"]
        _status["last_config"] = config
        _pipeline_runner._stop_event = new_stop
        _pipeline_runner._pipeline_thread = worker
    worker.start()

    return jsonify({"ok": True, "job_id": config["job_id"], "config": config})


@pipeline_bp.route("/api/stop", methods=["POST"])
def api_stop():
    # _stop_event / _active_encoder live in pipeline_runner; read them through
    # that module so the forwarder stays consistent.
    with _state_lock:
        if not _status["running"]:
            return jsonify({"error": "Pipeline not running"}), 409

    if _pipeline_runner._stop_event:
        _pipeline_runner._stop_event.set()
        log.info("Stop signal sent to pipeline.")

    # A thread blocked in finish_segment() waiting for FFmpeg needs the pipe
    # aborted so it can exit.
    enc = _pipeline_runner._active_encoder
    if enc is not None:
        try:
            enc.abort_segment()
            log.info("Active FFmpeg pipe aborted.")
        except Exception as exc:  # noqa: BLE001 - best effort; the stop event is already set
            log.debug("abort_segment failed: %s", exc)

    return jsonify({"ok": True})

"""
src/gui/routes/pipeline_bp.py

pipeline routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

import threading
import time
from pathlib import Path
import re as _re
from flask import Blueprint, jsonify, request, abort

try:
    from gui.state import (_state_lock, _status)
    from gui.logging_setup import log
    from gui.services.path_safety import _safe_output_dir, is_safe_input_source
    from gui.services.cloud_detection import _default_output_dir
    from gui.services import pipeline_runner as _pipeline_runner
    from gui.services import job_history as _job_history
    from gui.services.pipeline_runner import _run_pipeline_thread
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.state import (_state_lock, _status)
    from src.gui.logging_setup import log
    from src.gui.services.path_safety import _safe_output_dir, is_safe_input_source
    from src.gui.services.cloud_detection import _default_output_dir
    from src.gui.services import pipeline_runner as _pipeline_runner
    from src.gui.services import job_history as _job_history
    from src.gui.services.pipeline_runner import _run_pipeline_thread

pipeline_bp = Blueprint("pipeline", __name__)

# R5 TASK 5.1: the supported VMAF target band, sourced from the search module so
# the route and the searcher cannot drift apart.
try:
    from compression.vmaf_target import TARGET_VMAF_MIN as _TARGET_VMAF_MIN
    from compression.vmaf_target import TARGET_VMAF_MAX as _TARGET_VMAF_MAX
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.compression.vmaf_target import TARGET_VMAF_MIN as _TARGET_VMAF_MIN
    from src.compression.vmaf_target import TARGET_VMAF_MAX as _TARGET_VMAF_MAX


def _clamp_int(value, default: int, lo: int, hi: int) -> int:
    """Coerce ``value`` to an int in [lo, hi], or ``default`` if unparseable.

    Used to sanitise the R4 Phase 2 encoder knobs from the request body so a
    bad/oversized value can never reach the FFmpeg command line.
    """
    try:
        s = str(value).strip()
        if s == "" or value is None:
            return default
        f = float(s)
        # Reject inf / nan explicitly: int(float("inf")) raises OverflowError
        # (an ArithmeticError, NOT a ValueError), which would otherwise escape
        # as an unhandled HTTP 500 instead of falling back to the default.
        if f != f or f in (float("inf"), float("-inf")):
            return default
        return max(lo, min(hi, int(f)))
    except (TypeError, ValueError, OverflowError):
        return default


def _clamp_float_or_none(value, lo: float, hi: float):
    """Coerce ``value`` to a float in [lo, hi], or None when unset/unparseable.

    R5 TASK 5.1: target_vmaf is optional - None means "keep the fixed CRF", so an
    absent or garbage value must resolve to None (today's behaviour), never a
    surprise target and never a 500 (inf/nan are rejected like _clamp_int does).
    """
    try:
        if value is None:
            return None
        s = str(value).strip()
        if s == "":
            return None
        f = float(s)
        if f != f or f in (float("inf"), float("-inf")):
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

    R4 Phase 1 (docs/RESEARCH-UIUX.md finding 2): a persistent job record the
    operator can audit after stepping away; also feeds the completion-summary
    modal (finding 3). ?limit=N caps the list (default 20).
    """
    limit = request.args.get("limit", 20, type=int)
    return jsonify({"jobs": _job_history.recent_jobs(limit=limit)})


@pipeline_bp.route("/api/start", methods=["POST"])
def api_start():
    # _pipeline_thread / _stop_event are owned by gui.services.pipeline_runner;
    # assign through the module so the forwarder and /api/stop see the value.
    with _state_lock:
        if _status["running"]:
            return jsonify({"error": "Pipeline already running"}), 409

    data = request.get_json(force=True) or {}

    # ── Validate camera_id (alphanumeric / dash / underscore, max 64 chars) ──
    camera_id = str(data.get("camera_id", "cam_00")).strip()
    if not _re.match(r"^[a-zA-Z0-9_\-]{1,64}$", camera_id):
        return jsonify({"error": "camera_id must be 1-64 alphanumeric/dash/underscore chars"}), 400

    # Resolve input: if digit treat as camera index, else file path
    raw_input = str(data.get("input_source", "0")).strip()
    try:
        resolved_input = int(raw_input)
    except ValueError:
        resolved_input = raw_input
        # SEC-013: block file:// and cloud-metadata/link-local SSRF targets in the
        # input URL (cv2.VideoCapture would otherwise open them). Webcam indices
        # and local paths and real stream URLs pass.
        _ok, _why = is_safe_input_source(resolved_input)
        if not _ok:
            return jsonify({"error": f"input_source not allowed: {_why}"}), 400

    # Default output dir: prefer OneDrive/SVCS so segments land in the cloud
    # folder operators expect. Falls back to <project_root>/outputs/ only when
    # no cloud sync is detected. Was hard-coded to local - fixed 2026-05-02
    # in the audit. Author: Bloodawn (KheivenD).
    raw_out = data.get("output_dir", "").strip() or _default_output_dir()
    try:
        output_dir = str(_safe_output_dir(raw_out))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

    # ── Validate encrypt_key_file if provided ──────────────────────────────
    encrypt_key_file = (data.get("encrypt_key_file") or "").strip() or None
    if encrypt_key_file:
        kf = Path(encrypt_key_file).resolve()
        if not kf.exists():
            return jsonify({"error": f"encrypt_key_file not found: {kf}"}), 400
        if not kf.is_file():
            return jsonify({"error": "encrypt_key_file must be a regular file"}), 400
        encrypt_key_file = str(kf)

    config = {
        "input_source": resolved_input,
        "camera_id": camera_id,
        "output_dir": output_dir,
        "segment_seconds": data.get("segment_seconds", 60),
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
        # Codec selector. Valid values:
        #   "auto"      - DEFAULT (TASK 1.6). Backend picks the per-mode codec:
        #                 H.264 (libx264) for mode0/mode1, AV1 (libsvtav1) for
        #                 mode2/mode3 (config.default_codec_for_mode).
        #   "libsvtav1" - explicit AV1 (SVT-AV1).
        #   "libaom-av1" -  explicit AV1 reference, slower than SVT.
        #   "libx264"   - explicit H.264, always available.
        # H.265/HEVC is intentionally not offered (patent licensing). ROIEncoder
        # auto-falls-back to libx264 if the chosen encoder isn't in the running
        # ffmpeg build. Author: Bloodawn (KheivenD), 2026-05-03, updated
        # 2026-06-02 (per-mode codec default).
        "codec": str(data.get("codec", "auto") or "auto").strip(),
        # Foreground CRF. None means "use the mode default" (18 for
        # Mode 0/1/2, 38 for Mode 3). User can override from the Save To
        # section in the sidebar. Lower = better quality, larger file.
        # Author: Bloodawn (KheivenD), 2026-05-02 (Mode 3 redo).
        "crf": (int(data.get("crf")) if str(data.get("crf", "")).strip() else None),
        # Background CRF + named preset (M3 TASK 3.1). background_crf drives the
        # dual-CRF background stream; preset is the named surveillance preset the
        # config came from (informational / for export). None background_crf
        # keeps the encoder default.
        "background_crf": (int(data.get("background_crf"))
                           if str(data.get("background_crf", "")).strip() else None),
        "preset": (str(data.get("preset")).strip() or None) if data.get("preset") else None,
        # FIX 7: verbose logging toggle (Normal vs Verbose) for the run.
        "verbose": bool(data.get("verbose", False)),
        # ── R4 Phase 2 encoder knobs (docs/RESEARCH-COMPRESSION.md) ──
        # Storage cap (capped CRF), 0 = uncapped. Clamped to a sane range.
        "max_bitrate_kbps": _clamp_int(data.get("max_bitrate_kbps"), 0, 0, 200000),
        # Pre-encode denoiser for night/IR footage: "", "hqdn3d", "atadenoise".
        # Anything else is dropped to "" by the encoder.
        "denoise": (str(data.get("denoise", "")).strip().lower()
                    if data.get("denoise") else ""),
        # Encoder-level ROI (x264/x265 only), opt-in.
        "roi_qp": bool(data.get("roi_qp", False)),
        # Keyframe interval in seconds (long GOP for static cameras). Default
        # 20s; 0 keeps the FFmpeg default. Clamped to a seekable range.
        "gop_seconds": _clamp_int(data.get("gop_seconds"), 20, 0, 600),
        # ── R5 TASK 5.1: VMAF-targeted rate control ──
        # None (absent/blank/garbage) keeps the fixed-CRF path exactly as today.
        # A value clamps into the supported perceptual band before it can reach
        # the search. See docs/RESEARCH-VMAF-TARGET.md.
        "target_vmaf": _clamp_float_or_none(
            data.get("target_vmaf"), _TARGET_VMAF_MIN, _TARGET_VMAF_MAX),
    }

    _pipeline_runner._stop_event = threading.Event()
    _pipeline_runner._pipeline_thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(config, _pipeline_runner._stop_event),
        daemon=True,
        name="pipeline-worker",
    )
    _pipeline_runner._pipeline_thread.start()

    with _state_lock:
        _status["last_config"] = config

    return jsonify({"ok": True, "config": config})


@pipeline_bp.route("/api/stop", methods=["POST"])
def api_stop():
    # _stop_event / _active_encoder are owned by gui.services.pipeline_runner;
    # read them through the module so the forwarder stays consistent.
    with _state_lock:
        if not _status["running"]:
            return jsonify({"error": "Pipeline not running"}), 409

    if _pipeline_runner._stop_event:
        _pipeline_runner._stop_event.set()
        log.info("Stop signal sent to pipeline.")

    # If the pipeline thread is blocked inside finish_segment() waiting for
    # FFmpeg to flush, abort the pipe immediately so the thread can exit.
    enc = _pipeline_runner._active_encoder
    if enc is not None:
        try:
            enc.abort_segment()
            log.info("Active FFmpeg pipe aborted.")
        except Exception:
            pass

    return jsonify({"ok": True})



"""
src/gui/services/pipeline_runner.py

Pipeline background-thread runner and the live frame/segment counters,
extracted from gui/app.py (TASK 1.2 - last and most thread-heavy module).

`_run_pipeline_thread` is the target of the worker thread spawned by
/api/start. It seeds gui.state._status, starts the per-mode CPU sampler,
monkeypatches FrameSource/ROIEncoder to count frames/segments, runs the core
run_pipeline(), and restores the patches on exit. The rebindable handles
(_pipeline_thread / _stop_event / _active_encoder) live here and are forwarded
from gui.app so the /api/start and /api/stop routes (in app.py until TASK 1.3)
and the test suite (which sets gui_module._pipeline_thread = None and
monkeypatches gui_module._run_pipeline_thread) share one live value.

Imports gui.state, gui.logging_setup, the gui_state_persist / cpu_sampler
services (acyclic service->service), and pipeline.pipeline.run_pipeline.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - pipeline-runner extraction).
"""

import subprocess
import threading
import time
from pathlib import Path

try:
    from gui.state import _state_lock, _status
    from gui.logging_setup import log
    from gui.services.gui_state_persist import _save_gui_state
    from gui.services.cpu_sampler import _start_cpu_sampler, _stop_cpu_sampler
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.gui.state import _state_lock, _status
    from src.gui.logging_setup import log
    from src.gui.services.gui_state_persist import _save_gui_state
    from src.gui.services.cpu_sampler import _start_cpu_sampler, _stop_cpu_sampler

try:
    from pipeline.pipeline import run_pipeline
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.pipeline.pipeline import run_pipeline

# Repo root (…/src/gui/services/pipeline_runner.py -> parents[3]); default fallback.
_ROOT = Path(__file__).resolve().parents[3]

# Rebindable handles. Forwarded from gui.app so routes/tests share one value.
_pipeline_thread: threading.Thread | None = None
_stop_event: threading.Event | None = None
_active_encoder = None   # set by _patched_re_init so stop can abort a hung FFmpeg pipe


# ── Frame-count interceptor ───────────────────────────────────────────────────
# FrameSource.read() is wrapped at runtime so the GUI can count decoded frames
# without touching the core pipeline code.

def _patch_frame_source(src_obj):
    """Count successful reads into _status['frame_count'] and publish total_frames.

    total_frames is 0 for live cameras/RTSP; the progress bar shows a spinner.
    """
    total = getattr(src_obj, "total_frames", 0) or 0
    with _state_lock:
        _status["total_frames"] = int(total)

    original_read = src_obj.read

    def _counted_read():
        ret, frame = original_read()
        if ret:
            with _state_lock:
                _status["frame_count"] += 1
        return ret, frame

    src_obj.read = _counted_read
    return src_obj


# ── Segment-count interceptor ─────────────────────────────────────────────────
# ROIEncoder.finish_segment() is the one call every streamed segment goes
# through (encode_segment() is legacy and never called), so wrapping it is what
# makes the dashboard's "segments written" counter honest. The same hook
# publishes encoder.encryption_failures so a failed encryption is visible.

def _patch_encoder(enc_obj):
    original_finish = enc_obj.finish_segment

    def _counted_finish(*args, **kwargs):
        result = original_finish(*args, **kwargs)
        with _state_lock:
            _status["segment_count"] += 1
            _status["encryption_failures"] = getattr(enc_obj, "encryption_failures", 0)
        return result

    enc_obj.finish_segment = _counted_finish
    return enc_obj


# ── Opt-in usage stats (TASK 5.2) ─────────────────────────────────────────────

def _ingestion_path(input_source) -> str:
    """Classify the source into a coarse, non-identifying ingestion category."""
    s = str(input_source).strip().lower()
    if s.startswith("rtsp://"):
        return "rtsp"
    # numeric (webcam index), http(s), or a local path all fall under "file"
    # here - we deliberately don't distinguish further (no path detail leaves).
    return "file"


def _record_encode_stat(config: dict, success: bool, error: BaseException = None) -> None:
    """Record an anonymous encode outcome IF the user opted in (else no-op).

    Only categorical, non-identifying fields leave: preset, mode, codec, the
    success flag, an error *category*, and the ingestion path. usage_stats
    re-validates and scrubs everything; this never raises.
    """
    try:
        try:
            from utils import usage_stats
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.utils import usage_stats
        category = "none"
        if not success:
            name = type(error).__name__.lower() if error is not None else ""
            if "timeout" in name:
                category = "timeout"
            elif any(k in name for k in ("io", "os", "file", "permission")):
                category = "io"
            else:
                category = "encode"
        usage_stats.record_event(
            "encode",
            preset=config.get("preset"),
            mode=config.get("mode", "mode0"),
            codec=config.get("codec") or "auto",
            success=bool(success),
            error_category=category,
            ingestion_path=_ingestion_path(config.get("input_source", "")),
        )
    except Exception:  # noqa: BLE001 - telemetry must never affect the pipeline
        pass


# ── Pipeline thread runner ────────────────────────────────────────────────────

def _run_pipeline_thread(config: dict, stop_event: threading.Event) -> None:
    """Target function for the pipeline background thread."""
    with _state_lock:
        _status["running"] = True
        _status["frame_count"] = 0
        _status["segment_count"] = 0
        _status["total_frames"] = 0
        _status["error"] = None
        _status["start_time"] = time.time()
        _status["config"] = config
        # Cleared here for the same reason as enhancer_backend just below: a
        # stale failure count from a previous encrypted run must never leak
        # into a fresh run, encrypted or not.
        _status["encryption_failures"] = 0
        # Cleared here, filled in by the Enhancer patch below once (and if)
        # this run actually constructs one - stale values from a previous
        # run must never leak into a run that isn't enhancing at all.
        _status["enhancer_backend"] = None

    # Persist the chosen output_dir so the GUI can re-find segments after
    # a server restart.
    _save_gui_state()

    # Samples are labelled with the mode and written next to this run's
    # segments as a per-clip cpu_stats.json.
    _start_cpu_sampler(config.get("mode", "mode0"), output_dir=config.get("output_dir"))

    log.info("━" * 60)
    log.info("GUI PIPELINE START")
    log.info(f"  Input:   {config.get('input_source', '0')}")
    log.info(f"  Mode:    {config.get('mode', 'mode0')}")
    log.info(f"  Output:  {config.get('output_dir', 'outputs/')}")
    log.info("━" * 60)

    _orig_fs_init = None
    _orig_re_init = None
    _orig_enh_init = None
    try:
        # Imported here, not at module top, so the classes can be wrapped.
        try:
            import utils.frame_source as _fs
            import compression.roi_encoder as _re
        except ModuleNotFoundError:
            import src.utils.frame_source as _fs
            import src.compression.roi_encoder as _re

        _orig_fs_init = _fs.FrameSource.__init__
        _orig_re_init = _re.ROIEncoder.__init__

        def _patched_fs_init(self_inner, *a, **kw):
            _orig_fs_init(self_inner, *a, **kw)
            _patch_frame_source(self_inner)

        def _patched_re_init(self_inner, *a, **kw):
            global _active_encoder
            _orig_re_init(self_inner, *a, **kw)
            _patch_encoder(self_inner)
            _active_encoder = self_inner   # expose to stop handler

        _fs.FrameSource.__init__ = _patched_fs_init
        _re.ROIEncoder.__init__ = _patched_re_init

        # Publish the Enhancer's REAL resolved backend ("realesrgan-<device>"
        # or "bicubic"): the requested enhance_model silently falls back to
        # bicubic when Real-ESRGAN isn't installed.
        try:
            import enhancement.enhancer as _enh
        except ModuleNotFoundError:
            import src.enhancement.enhancer as _enh

        _orig_enh_init = _enh.Enhancer.__init__

        def _patched_enh_init(self_inner, *a, **kw):
            _orig_enh_init(self_inner, *a, **kw)
            with _state_lock:
                _status["enhancer_backend"] = self_inner.backend

        _enh.Enhancer.__init__ = _patched_enh_init

        run_pipeline(
            input_source=config.get("input_source", 0),
            camera_id=config.get("camera_id", "cam_00"),
            output_dir=config.get("output_dir", str(_ROOT / "outputs")),
            segment_seconds=int(config.get("segment_seconds", 60)),
            bg_method=config.get("bg_method", "MOG2"),
            mode=config.get("mode", "mode0"),
            demo=False,          # demo metadata not needed from GUI
            show_preview=False,
            warmup_frames=int(config.get("warmup_frames", 120)),
            enhance=config.get("enhance", False),
            enhance_model=config.get("enhance_model", "bicubic"),
            enhance_scale=int(config.get("enhance_scale", 4)),
            enhance_every_n=int(config.get("enhance_every_n", 5)),
            enhance_max_roi_px=int(config.get("enhance_max_roi_px", 200)),
            enhance_device=config.get("enhance_device", "auto"),
            upscale_output=config.get("upscale_output", False),
            encrypt=config.get("encrypt", False),
            encrypt_password=config.get("encrypt_password") or None,
            encrypt_key_file=config.get("encrypt_key_file") or None,
            object_filter=config.get("object_filter", False),
            filter_confidence=float(config.get("filter_confidence", 0.30)),
            stop_event=stop_event,
            # "auto" / None -> run_pipeline picks the per-mode default codec
            # (H.264 for mode0/1, AV1 for mode2/3); explicit values pass through.
            codec=config.get("codec"),
            crf=config.get("crf"),
            background_crf=config.get("background_crf"),
            verbose=bool(config.get("verbose", False)),
            # R4 Phase 2 encoder knobs (docs/RESEARCH-COMPRESSION.md).
            max_bitrate_kbps=int(config.get("max_bitrate_kbps", 0) or 0),
            denoise=config.get("denoise", "") or "",
            roi_qp=bool(config.get("roi_qp", False)),
            gop_seconds=int(config.get("gop_seconds", 20)
                            if config.get("gop_seconds") is not None else 20),
            # R5 TASK 5.1: target perceptual quality instead of a fixed CRF.
            # None keeps today's fixed-CRF behaviour exactly.
            target_vmaf=config.get("target_vmaf"),
        )
        _record_encode_stat(config, success=True)
        # Register file-input outputs in the compressed index so a dashboard or
        # phone compress shows up in the Library's COMPRESSED view, just like
        # auto-compress output. Interrupted runs are skipped, and the helper
        # ffprobe-verifies first, so a broken output is never indexed.
        if not stop_event.is_set():
            _record_compressed_outputs(config)

    except Exception as exc:
        log.error(f"Pipeline error: {exc}", exc_info=True)
        with _state_lock:
            _status["error"] = str(exc)
        _record_encode_stat(config, success=False, error=exc)
    finally:
        # Always restore the patches, even if run_pipeline raised. Each _orig_*
        # is only set after its module imported, so the module name is bound.
        if _orig_fs_init is not None:
            _fs.FrameSource.__init__ = _orig_fs_init
        if _orig_re_init is not None:
            _re.ROIEncoder.__init__ = _orig_re_init
        if _orig_enh_init is not None:
            _enh.Enhancer.__init__ = _orig_enh_init

        with _state_lock:
            _run_error = _status.get("error")
            _run_started = _status.get("start_time")
            _run_frames = _status.get("frame_count", 0)
            _run_segments = _status.get("segment_count", 0)
        # Record BEFORE flipping running=False: the UI shows the completion
        # summary on the running->stopped transition, so the history entry
        # must already be readable when /api/status first reports stopped.
        _record_job_history(config, stop_event, _run_started, _run_error,
                            _run_frames, _run_segments)
        with _state_lock:
            _status["running"] = False
        global _active_encoder
        _active_encoder = None
        _stop_cpu_sampler()
        log.info("Pipeline stopped.")


def _record_compressed_outputs(config: dict) -> None:
    """Pair a completed file-input run's outputs with their source in the
    compressed index, so the Library classifies them as "compressed".

    Only runs for a real source FILE (webcam indices and stream URLs have no
    source file to pair). Each candidate output must be a video written after
    the run started, carry this run's camera_id prefix, and pass an ffprobe
    decode check, the same bar auto-compress applies before it records. The
    index keys on the SOURCE, so a multi-segment run records its newest
    segment; that is the entry the COMPRESSED view needs to show the result.
    Best effort by design: never raises into the pipeline thread.
    Author: Bloodawn (KheivenD), 2026-08-16 (M4 follow-up).
    """
    try:
        raw = config.get("input_source")
        if not isinstance(raw, str) or not raw.strip():
            return
        src = Path(raw)
        if not src.is_file():
            return
        out_dir = Path(config.get("output_dir", "") or "")
        cam = str(config.get("camera_id", "cam_00"))
        if not out_dir.is_dir():
            return
        with _state_lock:
            started = float(_status.get("start_time") or 0.0)
        try:
            from utils import compressed_index as cidx
            from utils.ffmpeg import ffprobe_path
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.utils import compressed_index as cidx
            from src.utils.ffmpeg import ffprobe_path
        vid_exts = {".mp4", ".mkv", ".avi", ".mov", ".webm"}
        candidates = []  # (mtime, path)
        for p in out_dir.glob(f"{cam}_*"):
            if p.suffix.lower() not in vid_exts:
                continue
            try:
                if not p.is_file():
                    continue
                st = p.stat()
            except OSError:
                continue
            if st.st_mtime >= started - 2.0 and st.st_size > 0:
                candidates.append((st.st_mtime, p))
        if not candidates:
            return
        output = max(candidates, key=lambda c: c[0])[1]
        probe = subprocess.run(
            [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output)],
            capture_output=True, text=True, timeout=30,
        )
        if probe.returncode != 0 or "video" not in (probe.stdout or ""):
            log.warning("Not indexing unverified output %s", output.name)
            return
        cidx.record(src, output, mode=config.get("mode"))
        log.info("Compressed index: %s -> %s", src.name, output.name)
    except Exception as exc:  # noqa: BLE001 - best effort
        log.warning("Compressed-index recording skipped: %s", exc)


def _record_job_history(config, stop_event, started, error, frames, segments):
    """Persist this run to the job history (R4 Phase 1). Never raises."""
    try:
        try:
            from gui.services import job_history
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.gui.services import job_history
        src = str(config.get("input_source", "0"))
        label = Path(src).name if ("/" in src or "\\" in src) else f"source {src}"
        # Stop wins over error: aborting mid-flush often surfaces as a broken
        # FFmpeg pipe, and a user-requested STOP must never be reported as a
        # failed job (the exception is still in the log).
        if stop_event is not None and stop_event.is_set():
            status = "stopped"
            error = None
        elif error:
            status = "error"
        else:
            status = "completed"
        job_history.record_job(
            "pipeline",
            label=label,
            started_at=started,
            ended_at=time.time(),
            status=status,
            counts={"frames": int(frames or 0), "segments": int(segments or 0),
                    "mode": config.get("mode", "mode0"),
                    # M4 job registry: lets a client correlate this history
                    # entry with the job_id it got back from /api/start.
                    "job_id": config.get("job_id")},
            error=error,
        )
    except Exception:  # noqa: BLE001 - history must never affect the pipeline
        pass

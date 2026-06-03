"""
src/gui/services/pipeline_runner.py

Pipeline background-thread runner and the live frame/segment counters,
extracted from gui/app.py (TASK 1.2 — last and most thread-heavy module).

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

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — pipeline-runner extraction).
"""

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
# We wrap the FrameSource.read() method at runtime to count decoded frames
# without touching the core pipeline code.

def _patch_frame_source(src_obj):
    """Monkey-patch src.read() to increment _status['frame_count'].
    Also reads total_frames from the source so the progress bar knows the denominator.
    """
    # Push total frame count into status so the progress bar has a denominator.
    # total_frames == 0 for live cameras/RTSP; progress bar shows a spinner instead.
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
# We patch ROIEncoder.encode_segment() to count encoded segments without
# modifying roi_encoder.py.

def _patch_encoder(enc_obj):
    original_encode = enc_obj.encode_segment

    def _counted_encode(*args, **kwargs):
        result = original_encode(*args, **kwargs)
        with _state_lock:
            _status["segment_count"] += 1
        return result

    enc_obj.encode_segment = _counted_encode
    return enc_obj


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

    # Persist the chosen output_dir so the GUI can re-find segments after
    # a server restart. See _save_gui_state() up top.
    _save_gui_state()

    # Start CPU/RAM/battery sampler (labels samples under the active mode
    # AND attributes them to this run's output folder so the per-clip
    # CPU stats land alongside its segments).
    _mode_key = config.get("mode", "mode0")
    _start_cpu_sampler(_mode_key, output_dir=config.get("output_dir"))

    log.info("━" * 60)
    log.info("GUI PIPELINE START")
    log.info(f"  Input:   {config.get('input_source', '0')}")
    log.info(f"  Mode:    {config.get('mode', 'mode0')}")
    log.info(f"  Output:  {config.get('output_dir', 'outputs/')}")
    log.info("━" * 60)

    _orig_fs_init = None
    _orig_re_init = None
    try:
        # Patch FrameSource and ROIEncoder lazily. Import here so we can wrap.
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
            codec=config.get("codec", "libsvtav1"),
            crf=config.get("crf"),
        )

    except Exception as exc:
        log.error(f"Pipeline error: {exc}", exc_info=True)
        with _state_lock:
            _status["error"] = str(exc)
    finally:
        # Always restore monkey patches, even if run_pipeline raised.
        try:
            try:
                import utils.frame_source as _fs
                import compression.roi_encoder as _re
            except ModuleNotFoundError:
                import src.utils.frame_source as _fs
                import src.compression.roi_encoder as _re
            if _orig_fs_init is not None:
                _fs.FrameSource.__init__ = _orig_fs_init
            if _orig_re_init is not None:
                _re.ROIEncoder.__init__ = _orig_re_init
        except Exception:
            pass

        with _state_lock:
            _status["running"] = False
        global _active_encoder
        _active_encoder = None
        _stop_cpu_sampler()
        log.info("Pipeline stopped.")

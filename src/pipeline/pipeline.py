"""
pipeline.py

End-to-end orchestration: read camera feed, run background subtraction,
encode with ROI-aware compression, index metadata.

Designed to run continuously on low-spec hardware (Raspberry Pi, old x86 box).
No GPU required.

Author: Bloodawn (KheivenD)
Enhancement module integration: Victor Teixeira

Usage:
    python pipeline.py --input /dev/video0 --camera-id cam_01 --output outputs/
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test --warmup 150
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test --enhance
    python pipeline.py --input footage/test_clip.mp4 --camera-id cam_test --enhance --enhance-scale 2
"""

import argparse
import logging
from collections import deque
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Optional
import re
import sys
from pathlib import Path

import cv2
import numpy as np

# sys.path must be set before any local imports so this module can be run
# directly (python src/pipeline/pipeline.py) or imported from the project root.
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.db import initialize_database                                    # fix: was 'from src.utils.db'
from utils.frame_source import FrameSource                                  # fix: use FrameSource instead of raw VideoCapture
from utils.metrics import compute_sharpness, estimate_perceptual_resolution
from background_subtraction.background_subtraction import BackgroundSubtractor
from compression.roi_encoder import ROIEncoder
from enhancement.enhancer import Enhancer
from demo.demo_metadata import DemoMetadataWriter
from pipeline.modes import get_mode_decision, validate_mode
from compression.roi_encoder import _MODE_LABELS
from detection.object_filter import (
    ObjectFilter,
    detect_dominant_color,
    detect_scene_type,
    _VEHICLE_CLASSES,
    _PERSON_CLASSES,
)
from config import default_codec_for_mode

import json as _json


def _time_of_day(hour: int) -> str:
    """Map UTC hour to a time-of-day label."""
    if 5 <= hour < 8 or 18 <= hour < 21:
        return "dusk_dawn"
    if 8 <= hour < 18:
        return "day"
    return "night"


def _compute_segment_sharpness(
    frames: list,
    regions_per_frame: list,
) -> tuple:
    """
    Compute average Laplacian sharpness across all detected target ROI crops.

    Only samples frames where at least one detection exists, and only samples
    the ROI crops themselves (not the full frame) so background blur doesn't
    dilute the score.

    Returns:
        (avg_sharpness, sharpness_label). Both are None if no targets detected.
    """
    scores = []
    for frame, regions in zip(frames, regions_per_frame):
        for r in regions:
            x, y, w, h = r.x, r.y, r.w, r.h
            fh, fw = frame.shape[:2]
            x1 = max(0, x); y1 = max(0, y)
            x2 = min(fw, x + w); y2 = min(fh, y + h)
            if x2 > x1 and y2 > y1:
                crop = frame[y1:y2, x1:x2]
                scores.append(compute_sharpness(crop))
    if not scores:
        return None, None
    avg = sum(scores) / len(scores)
    return round(avg, 1), estimate_perceptual_resolution(avg)


def _stop_requested(stop_event) -> bool:
    return (
        stop_event is not None
        and hasattr(stop_event, "is_set")
        and stop_event.is_set()
    )


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)s  %(message)s",
)
log = logging.getLogger(__name__)


def _sanitize_camera_id(camera_id: str) -> str:
    """
    Strip any characters from camera_id that are unsafe in file paths.

    Allows only alphanumeric characters, underscores, and hyphens.
    A camera_id like '../../etc/passwd' becomes '______etc_passwd'.
    This prevents path traversal when camera_id is embedded in output filenames.
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", camera_id)


def run_pipeline(
    input_source,
    camera_id: str = "cam_00",
    output_dir: str = "outputs/",
    segment_seconds: int = 60,
    bg_method: str = "MOG2",
    show_preview: bool = False,
    warmup_frames: int = 120,
    enhance: bool = False,
    enhance_scale: int = 4,
    mode: str = "mode0",
    demo: bool = False,
    enhance_model: str = "bicubic",
    encrypt: bool = False,
    encrypt_password: Optional[str] = None,
    encrypt_key_file: Optional[str] = None,
    mode2_clean_seconds: float = 1.0,
    mode2_background_lag_seconds: float = 1.5,
    enhance_every_n: int = 5,
    enhance_max_roi_px: int = 200,
    enhance_device: str = "auto",
    upscale_output: bool = False,
    object_filter: bool = False,
    filter_confidence: float = 0.30,
    stop_event=None,
    codec: Optional[str] = None,
    crf: int = None,
    background_crf: Optional[int] = None,
    verbose: bool = False,
    max_bitrate_kbps: int = 0,
    denoise: str = "",
    roi_qp: bool = False,
    gop_seconds: int = 20,
    target_vmaf: Optional[float] = None,
):
    """
    Main pipeline loop.

    Reads frames from a camera or video file, runs background subtraction on each
    frame, accumulates frames in memory, then encodes each segment with ROI-aware
    compression (foreground at high quality, background at low quality).

    Uses FrameSource to transparently support both video files and CDnet-style
    image sequence folders. If the source provides a temporal_roi (CDnet), the
    warmup_frames argument is overridden with the scene's recommended warmup count
    so benchmark results are comparable to published CDnet scores.

    WARMUP PERIOD:
    MOG2 and KNN both need time to build an accurate background model. During the
    first `warmup_frames` frames the mask output is essentially noise. The fix:
    feed frames through the subtractor during warmup but do NOT accumulate them
    for encoding. Encoding only begins after warmup is complete.

    INTERMEDIATE FORMAT:
    Frames are buffered in memory as a list of numpy arrays and piped directly to
    FFmpeg via stdin. This avoids the lossy XVID intermediate AVI that was used
    previously, which degraded quality before the final encode step.

    MODES:
    mode0 (default): All post-warmup frames are buffered and encoded. Baseline
                     H.264 dual-CRF ROI encoding on every frame.
    mode1:           Frame gating. Only frames with detected foreground activity
                     are buffered. Segments are formed from active frames only,
                     reducing storage when the scene is mostly static.
    mode2:           Background keyframe plus object patches. Only frames with
                     foreground detections are buffered; the encoded segment is
                     built by compositing each detected bounding box over the
                     latest clean background frame.
    mode3:           Object-only segment output. Only frames with foreground
                     detections are buffered, and pixels outside each detected
                     bounding box are blacked out before MP4 encoding.

    Args:
        input_source: Camera index (int) or video file / CDnet scene path (str).
        camera_id: Identifier for this camera. Used in output filenames and the
                   SQLite metadata index. Sanitized to prevent path traversal.
        output_dir: Directory where compressed output segments are written.
        segment_seconds: How many seconds of footage to accumulate before
                         flushing and encoding one segment.
        bg_method: Which background subtraction algorithm to use.
                   "MOG2" is the recommended default for outdoor static cameras.
        show_preview: Display a live preview window with bounding boxes drawn.
                      Disable this on headless servers.
        warmup_frames: Number of frames to feed through the background model
                       before beginning to encode output. Default 120 frames
                       (approximately 4 seconds at 30fps). Increase to 250-500
                       for scenes with complex dynamic backgrounds (trees, flags).
        demo: Demo mode toggle
        mode: Compression mode. "mode0" encodes all frames; "mode1" gates on
              foreground activity; "mode2" composites foreground bbox patches
              over a clean background; "mode3" encodes foreground bbox pixels
              on a highly-compressible black canvas.
        enhance: When True, apply super-resolution sharpening to foreground ROIs
                 before writing each frame to the segment buffer. Requires
                 Real-ESRGAN weights in models/ (falls back to bicubic if absent).
                 Adds per-frame CPU cost; not recommended for real-time sources.
        enhance_scale: Intermediate upscale factor used by the Enhancer.
                       Default 4 (matches RealESRGAN_x4plus weights).
        encrypt: If True, encrypt each output segment with AES-256-CBC after
                 encoding. Requires `encrypt_password` or `encrypt_key_file`.
                 The plaintext .mp4 is deleted; only the .mp4.enc file is kept.
                 Requires the `cryptography` package.
        encrypt_password: Passphrase for AES key derivation (PBKDF2-HMAC-SHA256,
                          600,000 iterations). Mutually exclusive with
                          encrypt_key_file.
        encrypt_key_file: Path to a file containing a raw 32-byte AES-256 key.
                          Mutually exclusive with encrypt_password.
        mode2_clean_seconds: Number of consecutive skipped/empty seconds
                             required before a frame can refresh the mode2
                             background keyframe. Default 1.0 seconds.
        mode2_background_lag_seconds: When a clean skip ends, pick the clean
                                      background frame from this many seconds
                                      before the end of the skip. Default 1.5.
    """
    validate_mode(mode)

    # Sanitize camera_id to prevent path traversal in output filenames.
    safe_camera_id = _sanitize_camera_id(camera_id)
    if safe_camera_id != camera_id:
        log.warning(f"camera_id sanitized: {camera_id!r} -> {safe_camera_id!r}")
    camera_id = safe_camera_id

    Path(output_dir).mkdir(parents=True, exist_ok=True)

    # Use FrameSource to support both video files and CDnet image sequences.
    src = FrameSource(str(input_source) if not isinstance(input_source, int) else input_source)

    # If the source provides a temporal_roi (CDnet benchmark), use that as the
    # warmup count so results are comparable to published CDnet scores.
    effective_warmup = src.get_warmup_frames(fallback=warmup_frames)

    fps = src.fps
    frame_w = src.width
    frame_h = src.height
    # Total source frames if known (files report it; live streams are 0). Used
    # for the percent-done progress logging (FIX 7).
    total_frames = int(getattr(src, "total_frames", 0) or 0)
    frames_per_segment = max(1, int(fps * segment_seconds))
    mode2_clean_frames = max(1, int(round(fps * mode2_clean_seconds)))
    mode2_background_lag_frames = max(0, int(round(fps * mode2_background_lag_seconds)))
    mode2_post_warmup_guard_frames = max(1, int(round(fps * 1.0)))

    # Single consistent database path: output_dir/metadata.db.
    # Previously pipeline.py called initialize_database() with no args, which
    # defaulted to "metadata.db" in the cwd (a different file than the encoder's
    # "outputs/metadata.db". Now both use the same explicit path.
    db_path = str(Path(output_dir) / "metadata.db")

    log.info(f"Source: {input_source} | {frame_w}x{frame_h} @ {fps:.1f}fps")

    # ── R5 TASKS 5.6/5.7: zone masks + behavior events ───────────────────────
    # Per-camera config is read ONCE at run start (a saved change applies to
    # the next run). Every failure path only disables the feature; it can
    # never take down an encode. Author: Bloodawn (KheivenD), 2026-08-17.
    _zone_cfg = None
    _event_engine = None
    try:
        try:
            from utils.zones_config import (load_camera_config as _load_zcfg,
                                            filter_regions as _zone_filter)
            from utils.track_events import EventEngine as _EventEngine
            from utils.event_log import append_events as _append_events
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.utils.zones_config import (load_camera_config as _load_zcfg,
                                                filter_regions as _zone_filter)
            from src.utils.track_events import EventEngine as _EventEngine
            from src.utils.event_log import append_events as _append_events
        _zone_cfg = _load_zcfg(camera_id)
        if _zone_cfg["lines"] or _zone_cfg["zones"]:
            _event_engine = _EventEngine(
                lines=_zone_cfg["lines"], zones=_zone_cfg["zones"],
                loiter_s=_zone_cfg["loiter_s"],
                class_filter=_zone_cfg["class_filter"])
            log.info("Behavior events armed: %d line(s), %d loiter zone(s).",
                     len(_zone_cfg["lines"]), len(_zone_cfg["zones"]))
        if _zone_cfg["exclude"]:
            log.info("Zone masks active: %d exclude region(s).",
                     len(_zone_cfg["exclude"]))
    except Exception as _zexc:  # noqa: BLE001 - feature must never kill a run
        log.warning("Zones/events config unavailable: %s", _zexc)
        _zone_cfg = None
        _event_engine = None
    log.info(f"Segment length: {segment_seconds}s ({frames_per_segment} frames)")
    log.info(f"Mode: {mode}")
    warmup_secs = (effective_warmup / fps) if fps > 0 else 0.0
    log.info(f"Warmup: {effective_warmup} frames (~{warmup_secs:.1f}s)")
    if total_frames > 0:
        log.info("Source length: %d frames (~%.1fs)", total_frames,
                 (total_frames / fps) if fps > 0 else 0.0)
    if verbose:
        log.info("Verbose logging ON: per-frame progress and per-segment detail.")
    if mode == "mode2":
        log.info(
            "Mode2 clean background guard: %.1fs (%d consecutive frames)",
            mode2_clean_seconds,
            mode2_clean_frames,
        )
        log.info(
            "Mode2 post-warmup background quarantine: 1.0s (%d frames)",
            mode2_post_warmup_guard_frames,
        )
        log.info(
            "Mode2 clean background capture lag: %.1fs (%d frames)",
            mode2_background_lag_seconds,
            mode2_background_lag_frames,
        )

    subtractor = BackgroundSubtractor(method=bg_method)
    # Mode 2/3 do extra per-frame compositing work; ultrafast encoding keeps
    # overall CPU load manageable. Mode 0/1 can afford slightly better compression.
    encode_preset = "ultrafast" if mode in ("mode2", "mode3") else "veryfast"

    # CRF resolution. Modes get progressively more aggressive foreground CRF
    # from mode 0 -> mode 3, so each mode compresses harder than the last:
    #   mode 0 / mode 1: CRF 18 (highest quality baseline / dual-CRF foreground)
    #   mode 2:          CRF 23 (compression-oriented event recording)
    #   mode 3:          CRF 38 (object-only; blacked-out background takes
    #                            near-zero bits, so the ROI pixels get
    #                            compressed hardest)
    # User-supplied `crf` overrides the mode default.
    # Author: Bloodawn (KheivenD), 2026-05-31 (M0 TASK 0.3 - mode2 was wrongly
    # left at CRF 18; restored progressive mode0<mode1<mode2<mode3 compression).
    if crf is not None:
        resolved_crf = int(crf)
    elif mode == "mode3":
        resolved_crf = 38
    elif mode == "mode2":
        resolved_crf = 23
    else:
        resolved_crf = 18

    # Codec resolution (TASK 1.6, codec gate RESOLVED 2026-06-01). When the
    # caller passes no explicit codec (codec is None / "auto"), pick the
    # per-mode default: mode0/mode1 -> H.264 (libx264), mode2/mode3 -> AV1
    # (libsvtav1). An explicit codec always wins. ROIEncoder still auto-falls
    # back to FALLBACK_CODEC if the running FFmpeg lacks the chosen encoder.
    # Author: Bloodawn (KheivenD), 2026-06-02 (per-mode codec).
    if codec is None or str(codec).strip().lower() in ("", "auto"):
        codec = default_codec_for_mode(mode)

    # ── VMAF-targeted rate control (R5 TASK 5.1) ─────────────────────────────
    # Opt-in: when target_vmaf is set and the source is a FILE, sample-encode a
    # few short segments to find the largest CRF (smallest file) that still
    # clears the perceptual target, and use that instead of the fixed CRF. The
    # search never raises and never hangs: any failure (no libvmaf, live source,
    # no convergence) keeps resolved_crf and logs the reason.
    # Design: docs/RESEARCH-VMAF-TARGET.md.
    if target_vmaf is not None and not isinstance(input_source, int):
        try:
            from compression.vmaf_target import find_crf_for_target
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.compression.vmaf_target import find_crf_for_target
        _tv = find_crf_for_target(
            input_source, codec=codec, fixed_crf=resolved_crf,
            target_vmaf=target_vmaf, preset=encode_preset,
        )
        if _tv.used_target:
            log.info("VMAF target %.1f: CRF %d -> %d (measured VMAF %.2f, "
                     "%d probe(s)%s)", _tv.target_vmaf, resolved_crf, _tv.crf,
                     _tv.measured_vmaf if _tv.measured_vmaf is not None else -1.0,
                     _tv.probes, ", cached" if _tv.cached else "")
            resolved_crf = _tv.crf
        else:
            log.info("VMAF target requested but not used (%s); keeping fixed CRF %d.",
                     _tv.fallback_reason, resolved_crf)

    # Background CRF (dual-CRF background stream). None keeps the encoder's own
    # default; a preset (M3 TASK 3.1) or explicit caller can raise it for more
    # background compression. Author: Bloodawn (KheivenD), 2026-06-03.
    _bg_crf = int(background_crf) if background_crf is not None else 40
    encoder = ROIEncoder(
        output_dir=output_dir,
        db_path=db_path,
        preset=encode_preset,
        codec=codec,
        foreground_crf=resolved_crf,
        background_crf=_bg_crf,
        # R4 Phase 2 (docs/RESEARCH-COMPRESSION.md): long-GOP default on,
        # optional capped-CRF / denoise / encoder-level ROI. The GUI and CLI
        # pass these through; defaults leave behaviour unchanged except the
        # (safe, seekable) 20s keyframe interval.
        max_bitrate_kbps=int(max_bitrate_kbps or 0),
        denoise=denoise or "",
        roi_qp=bool(roi_qp),
        gop_seconds=int(gop_seconds if gop_seconds is not None else 20),
    )
    # getattr fallbacks keep this diagnostic line working against lightweight
    # encoder doubles in the tests; the real ROIEncoder always has these.
    log.info("Encoder: codec=%s (resolved %s), fg_crf=%d, bg_crf=%d, gop=%ss, "
             "cap=%skbps, denoise=%s, roi_qp=%s (mode=%s)",
             codec, getattr(encoder, "codec", codec), resolved_crf, _bg_crf,
             getattr(encoder, "gop_seconds", "?"),
             getattr(encoder, "max_bitrate_kbps", 0) or "off",
             getattr(encoder, "denoise", "") or "off",
             getattr(encoder, "roi_qp", False), mode)
    initialize_database(db_path)

    obj_filter: Optional[ObjectFilter] = None
    if object_filter:
        obj_filter = ObjectFilter(confidence=filter_confidence, device="auto")
        if obj_filter.active:
            log.info(
                "ObjectFilter active (YOLOv8-nano, conf=%.2f). "
                "Leaves/shadows/false MOG2 detections will be discarded.",
                filter_confidence,
            )
        else:
            log.warning(
                "ObjectFilter requested but ultralytics not available. "
                "running in pass-through mode (all boxes kept)."
            )

    enhancer: Optional[Enhancer] = None
    _enhance_executor: Optional[ThreadPoolExecutor] = None
    _enhance_future: Optional[Future] = None
    _enhance_frame_counter = 0          # counts post-warmup frames for N-frame sampling
    _last_enhanced_frame = None         # cached result from the last enhancement pass
    if enhance or upscale_output:
        if enhance_model != "bicubic":
            log.info(
                "enhance_model='%s' requested; current pipeline uses Enhancer backend auto-selection.",
                enhance_model,
            )
        _enh_device = None if enhance_device == "auto" else enhance_device
        enhancer = Enhancer(scale=enhance_scale, device=_enh_device)
        # One worker thread. Enhancement is a serial CPU task so more workers
        # would fight over cores and slow everything down further.
        if enhance:
            _enhance_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="enhance")
        log.info(
            "Enhancement enabled (backend=%s, scale=%d, every_n=%d, max_roi=%dpx, upscale_output=%s). "
            "ROIs will be enhanced in a background thread.",
            enhancer.backend, enhance_scale, enhance_every_n, enhance_max_roi_px, upscale_output,
        )

    if encrypt:
        if not encrypt_password and not encrypt_key_file:
            log.warning(
                "encrypt=True but no password or key file provided. "
                "Segments will not be encrypted until one is supplied."
            )
        else:
            _kmode = "key file" if encrypt_key_file else "password"
            log.info("Encryption enabled (AES-256-GCM, %s mode).", _kmode)

    demo_writer: Optional[DemoMetadataWriter] = None
    if demo:
        demo_jsonl = Path(output_dir) / f"{camera_id}_{mode}_demo_frames.jsonl"
        demo_writer = DemoMetadataWriter(demo_jsonl)
        log.info(f"Demo metadata enabled: {demo_jsonl}")

    # ── Streaming state ───────────────────────────────────────────────────────
    # No frame buffer. FFmpeg is opened at segment start and frames are piped
    # one-by-one as they come from the camera. Encoding and decoding run in
    # parallel. No wait-then-burst, no 9GB of RAM copies.
    last_clean_background = None
    clean_frame_streak    = 0
    clean_frame_buffer    = deque(maxlen=max(1, mode2_background_lag_frames + 1))
    post_warmup_frame_count = 0
    source_frame_index    = -1
    frames_in_segment     = 0          # frames written to current open pipe
    target_frames_this_segment = 0
    segment_index         = 0
    segment_start_background = None   # background keyframe for current mode2 segment
    mode_label            = _MODE_LABELS.get(mode, "")
    object_only           = (mode == "mode3")

    # ── Per-segment metadata accumulators ────────────────────────────────────
    _seg_all_classes:   set   = set()   # union of YOLO classes seen this segment
    _seg_colors:        list  = []      # dominant_color strings sampled this segment
    _seg_motion_vecs:   list  = []      # (dx, dy) vectors for scene-type heuristic
    _seg_prev_centroids: list = []      # centroids from previous frame for motion deltas

    def _open_new_segment(first_frame, first_regions):
        """Open FFmpeg pipe for a new segment.  Returns the background frame used."""
        nonlocal segment_start_background, _seg_all_classes, _seg_colors, _seg_motion_vecs, _seg_prev_centroids
        # Reset per-segment accumulators
        _seg_all_classes  = set()
        _seg_colors       = []
        _seg_motion_vecs  = []
        _seg_prev_centroids = []

        has_targets = len(first_regions) > 0
        roi_count   = sum(1 for _ in first_regions)

        # Use real YOLO labels if available, otherwise fall back to unknown
        if obj_filter is not None and hasattr(obj_filter, "last_detected_classes"):
            obj_type = obj_filter.classify_detected_objects()
            for labels in obj_filter.last_detected_classes.values():
                _seg_all_classes |= labels
        else:
            obj_type = "unknown"

        bg = None
        if mode == "mode2":
            raw_bg = (last_clean_background.copy()
                      if last_clean_background is not None
                      else np.zeros_like(first_frame))
            # If output is being upscaled, the background must match the upscaled
            # frame dimensions. last_clean_background is always stored pre-upscale.
            if upscale_output and enhancer is not None and last_clean_background is not None:
                bg = enhancer.upscale_frame(raw_bg)
            else:
                bg = raw_bg
            segment_start_background = bg
        # Pass source path so the encoder can mux audio back in after encoding.
        # Only meaningful for file sources. Camera streams never have audio.
        src_path = str(input_source) if isinstance(input_source, str) else None
        encoder.begin_segment(
            frame_shape=first_frame.shape,
            fps=fps,
            camera_id=camera_id,
            has_targets=has_targets,
            object_type=obj_type,
            source_path=src_path,
            encrypt=encrypt,
            encrypt_password=encrypt_password,
            encrypt_key_file=encrypt_key_file,
        )
        return bg

    def _close_segment(discard: bool = False):
        """Close the current open pipe and save the segment.

        Args:
            discard: If True, kill FFmpeg immediately without waiting for the
                     output file to flush. Used when a stop is requested so the
                     thread can exit without waiting up to 30s for a full segment.
        """
        nonlocal frames_in_segment, target_frames_this_segment, segment_index

        if discard:
            encoder.abort_segment()
            log.info("Segment %d aborted by stop request.", segment_index + 1)
            frames_in_segment = 0
            target_frames_this_segment = 0
            segment_index += 1
            return

        # ── Compute segment-level rich metadata ───────────────────────────────
        # Dominant color: most frequent color label seen across all ROI samples
        from collections import Counter as _Counter
        _dom_color = None
        if _seg_colors:
            _dom_color = _Counter(_seg_colors).most_common(1)[0][0]

        # Scene type via motion vector heuristic
        _fh, _fw = frame.shape[:2] if frame is not None else (0, 0)
        _scene = detect_scene_type(_seg_motion_vecs, target_frames_this_segment, _fh * _fw)

        # Time of day from current UTC hour
        import datetime as _dt
        _tod = _time_of_day(_dt.datetime.utcnow().hour)

        # Per-type counts
        _vcls = _VEHICLE_CLASSES
        _pcls = _PERSON_CLASSES
        _vcount = sum(1 for c in _seg_all_classes if c in _vcls)
        _pcount = sum(1 for c in _seg_all_classes if c in _pcls)

        # object_classes JSON array (sorted for consistent storage)
        _obj_cls_json = _json.dumps(sorted(_seg_all_classes)) if _seg_all_classes else None

        out = encoder.finish_segment(
            object_classes = _obj_cls_json,
            dominant_color = _dom_color,
            scene_type     = _scene,
            time_of_day    = _tod,
            vehicle_count  = _vcount,
            person_count   = _pcount,
        )
        log.info("Saved segment %d: %s [type=%s color=%s scene=%s %s]",
                 segment_index + 1, out["file_path"],
                 encoder._stream_object_type if hasattr(encoder, "_stream_object_type") else "?",
                 _dom_color or "?", _scene, _tod)
        if out.get("sharpness_label"):
            log.info("Target ROI sharpness: %s (score=%.1f)",
                     out["sharpness_label"], out["avg_sharpness"])
        # FIX 7: per-segment detail - detections, output size, a rough ratio vs
        # raw frames, and overall progress. Useful at Normal verbosity too.
        try:
            _seg_bytes = Path(out["file_path"]).stat().st_size
        except OSError:
            _seg_bytes = 0
        _raw_bytes = max(1, frames_in_segment) * max(1, frame_w) * max(1, frame_h) * 3
        _ratio = (_raw_bytes / _seg_bytes) if _seg_bytes else 0.0
        _pct = ((" | %.0f%% of source" % (100.0 * source_frame_index / total_frames))
                if total_frames > 0 else "")
        log.info("  segment %d detail: %d people, %d vehicles | %d frames | "
                 "%.1f KB (~%.1fx vs raw)%s",
                 segment_index + 1, _pcount, _vcount, frames_in_segment,
                 _seg_bytes / 1024.0, _ratio, _pct)
        frames_in_segment = 0
        target_frames_this_segment = 0
        segment_index += 1

    # Track whether we have an open pipe
    segment_open      = False
    current_bg_frame  = None   # background used for the current mode2 segment

    log.info("Pipeline running (streaming encoder, no frame buffer). Press Ctrl+C to stop.")

    try:
        while True:
            if _stop_requested(stop_event):
                log.info("Stop event received. Ending pipeline loop.")
                break

            ret, frame = src.read()
            if not ret:
                log.info("End of source. Closing final segment.")
                break

            source_frame_index += 1

            mask             = subtractor.apply(frame)
            raw_regions      = subtractor.get_foreground_regions(mask)

            # YOLO classification gate: drop leaves/shadows/false detections.
            # Tiny boxes (< min_box_px) are passed through unfiltered by ObjectFilter
            # so real targets that are briefly small don't get silently dropped.
            if obj_filter is not None:
                regions = obj_filter.filter(frame, raw_regions)
                # Accumulate YOLO labels for this segment's metadata
                if segment_open and hasattr(obj_filter, "last_detected_classes"):
                    for labels in obj_filter.last_detected_classes.values():
                        _seg_all_classes |= labels
            else:
                regions = raw_regions

            # R5 TASK 5.6: exclude-zone mask. A region dropped here never
            # becomes foreground at all - no event, no ROI bits - which is
            # the double win the spec names (fewer false alerts AND smaller
            # files, e.g. mask the road and the tree line, watch the door).
            if _zone_cfg and _zone_cfg["exclude"]:
                regions = _zone_filter(regions, _zone_cfg["exclude"],
                                       frame_w, frame_h)

            # R5 TASK 5.7: behavior events on tracked objects (line-crossing,
            # loitering, direction), recorded to <output_dir>/events.jsonl.
            if _event_engine is not None:
                try:
                    _boxes_n = [(r.x / frame_w, r.y / frame_h,
                                 (r.x + r.w) / frame_w, (r.y + r.h) / frame_h)
                                for r in regions]
                    _evts = _event_engine.step(
                        _boxes_n, t=source_frame_index / max(fps, 1.0))
                    if _evts:
                        for _e in _evts:
                            log.info("EVENT %s at %s: track %s (%s) dir=%s",
                                     _e["kind"], _e["geometry_id"],
                                     _e["track_id"], _e.get("label") or "?",
                                     _e.get("direction"))
                        _append_events(output_dir, _evts, camera_id=camera_id)
                except Exception as _eexc:  # noqa: BLE001
                    log.warning("Event engine disabled for this run: %s", _eexc)
                    _event_engine = None

            has_regions = len(regions) > 0

            # ── Per-frame metadata accumulation ──────────────────────────────
            if segment_open and has_regions:
                # Color: sample the dominant color of each detected ROI
                for r in regions:
                    color = detect_dominant_color(frame, r.x, r.y, r.w, r.h)
                    if color != "unknown":
                        _seg_colors.append(color)

                # Motion vectors: compare centroids to previous frame
                curr_centroids = [(r.x + r.w // 2, r.y + r.h // 2) for r in regions]
                if _seg_prev_centroids and curr_centroids:
                    # Match by nearest centroid (simple greedy)
                    for cx, cy in curr_centroids:
                        best_dx, best_dy, best_dist = 0, 0, float("inf")
                        for px, py in _seg_prev_centroids:
                            d = ((cx - px) ** 2 + (cy - py) ** 2) ** 0.5
                            if d < best_dist:
                                best_dist, best_dx, best_dy = d, cx - px, cy - py
                        if best_dist < 80:   # px threshold - ignore teleporting blobs
                            _seg_motion_vecs.append((best_dx, best_dy))
                _seg_prev_centroids = curr_centroids

            # --- WARMUP GATE ---
            if source_frame_index < effective_warmup:
                if source_frame_index + 1 == effective_warmup:
                    log.info(
                        "Warmup complete after %d frames. Encoding started.",
                        effective_warmup,
                    )
                continue
            # --- END WARMUP GATE ---

            post_warmup_frame_count += 1

            # FIX 7: verbose per-N-frames progress to the SSE log + console.
            if verbose and post_warmup_frame_count % 100 == 0:
                if total_frames > 0:
                    _p = 100.0 * source_frame_index / total_frames
                    log.info("Progress: frame %d/%d (%.0f%%), segment %d",
                             source_frame_index, total_frames, _p, segment_index + 1)
                else:
                    log.info("Progress: %d frames processed, segment %d",
                             source_frame_index, segment_index + 1)

            # Optional: enhance foreground ROIs before encoding.
            #
            # Strategy: run enhancement in a background thread every N frames.
            # On non-enhance frames, reuse the last enhanced result so the
            # encode still sees sharpened output without waiting for SR every frame.
            #
            # Within each enhance frame, only process ROIs that are:
            #  - small enough (w and h both ≤ enhance_max_roi_px); huge boxes
            #    cost proportional to area and add little over bicubic at that scale
            #  - large enough (≥ 16px each dimension); tiny chips gain nothing
            #
            # The async pattern: submit this frame to the executor, then
            # immediately use the *previous* completed result for encoding.
            # This hides the SR latency behind decoding the next frames.
            if enhancer is not None and regions:
                _enhance_frame_counter += 1
                is_enhance_frame = (_enhance_frame_counter % enhance_every_n) == 1

                if is_enhance_frame:
                    # Collect the eligible ROIs for this frame
                    eligible = [
                        r for r in regions
                        if 16 <= r.w <= enhance_max_roi_px and 16 <= r.h <= enhance_max_roi_px
                    ]

                    if eligible:
                        # Capture loop-locals for the closure
                        _frame_to_enhance = frame.copy()
                        _regions_to_enhance = eligible
                        _enhancer_ref = enhancer

                        def _do_enhance(f, regs, enh):
                            result = f
                            for r in regs:
                                result = enh.upscale_roi(result, (r.x, r.y, r.w, r.h))
                            return result

                        # Collect previous result before submitting the next
                        if _enhance_future is not None and _enhance_future.done():
                            try:
                                _last_enhanced_frame = _enhance_future.result()
                            except Exception as _e:
                                log.debug("Enhancement error (ignored): %s", _e)

                        _enhance_future = _enhance_executor.submit(
                            _do_enhance, _frame_to_enhance, _regions_to_enhance, _enhancer_ref
                        )

                # Use cached enhanced frame if we have one
                if _last_enhanced_frame is not None and _last_enhanced_frame.shape == frame.shape:
                    frame = _last_enhanced_frame

            mode_decision = get_mode_decision(mode, regions)

            # Track clean-background streak for mode2 keyframe refresh.
            #
            # A frame is only eligible if mode2 would skip it. That means the
            # clean background comes from actual empty gaps between encoded
            # events, including frames that were skipped after optional YOLO
            # filtering. Never learn a clean keyframe during warmup or during
            # the first second after warmup; that window is where the detector
            # is most likely to briefly miss an object already on screen.
            #
            # The actual keyframe is chosen when the skip ends, not while the
            # skip is still happening. This lets us pick a frame from before
            # the detected object re-entered the scene, instead of the final
            # skipped frame that may still contain a missed object.
            if mode == "mode2":
                in_post_warmup_quarantine = (
                    post_warmup_frame_count <= mode2_post_warmup_guard_frames
                )
                if in_post_warmup_quarantine:
                    clean_frame_streak = 0
                    clean_frame_buffer.clear()
                elif mode_decision.buffer_frame:
                    if clean_frame_streak >= mode2_clean_frames and clean_frame_buffer:
                        lag_index = max(
                            0,
                            len(clean_frame_buffer) - mode2_background_lag_frames - 1,
                        )
                        last_clean_background = clean_frame_buffer[lag_index].copy()
                        if segment_open and current_bg_frame is not None:
                            current_bg_frame = last_clean_background.copy()
                    clean_frame_streak = 0
                    clean_frame_buffer.clear()
                else:
                    clean_frame_streak += 1
                    clean_frame_buffer.append(frame.copy())

            if mode_decision.target_detected:
                target_frames_this_segment += 1

            if show_preview:
                vis = subtractor.draw_regions(frame, regions)
                cv2.imshow("Pipeline Preview", vis)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break

            if not mode_decision.buffer_frame:
                # This frame is not included in any segment (mode1/2/3 gate)
                continue

            # Full-frame output upscale - increases the output video resolution.
            # Runs synchronously (bicubic is ~microseconds; Real-ESRGAN if installed).
            # Bounding box coordinates are scaled to match the upscaled frame.
            if enhancer is not None and upscale_output:
                frame = enhancer.upscale_frame(frame)

            # Open a new FFmpeg pipe when we start a fresh segment
            if not segment_open:
                current_bg_frame = _open_new_segment(frame, regions)
                segment_open = True

            # Check stop before writing (avoids writing a frame when we're about to abort)
            if _stop_requested(stop_event):
                log.info("Stop event received mid-segment. Ending pipeline loop.")
                break

            # Write frame directly to the open pipe. No copy into a list.
            boxes = [r.to_tuple() for r in regions]
            if upscale_output and enhance_scale > 1 and boxes:
                s = enhance_scale
                boxes = [(x * s, y * s, w * s, h * s) for x, y, w, h in boxes]
            encoder.write_frame(
                frame=frame,
                boxes=boxes,
                background_frame=current_bg_frame,
                object_only=object_only,
                mode_label=mode_label,
                measure_sharpness=(len(boxes) > 0),
                compress_background=(mode == "mode0"),
            )
            frames_in_segment += 1

            if demo_writer is not None:
                demo_writer.write_record(
                    source_frame_index=source_frame_index,
                    source_time_seconds=(source_frame_index / fps) if fps > 0 else 0.0,
                    mode=mode,
                    segment_index=segment_index,
                    frame_index_within_segment=frames_in_segment - 1,
                    regions=regions,
                )

            # Close and save when segment is full
            if frames_in_segment >= frames_per_segment:
                log.info("Segment %d full (%d frames, %d target frames)",
                         segment_index + 1, frames_in_segment, target_frames_this_segment)
                _close_segment()
                segment_open = False
                current_bg_frame = None

    except KeyboardInterrupt:
        log.info("Interrupted by user.")
    finally:
        stopping = _stop_requested(stop_event)
        # Close any open pipe for the final partial segment
        if segment_open and frames_in_segment > 0:
            if stopping:
                # User hit STOP. Kill FFmpeg immediately, no flush wait.
                log.info("Stop requested: aborting open segment (%d frames).", frames_in_segment)
                _close_segment(discard=True)
            else:
                log.info("Flushing final partial segment (%d frames).", frames_in_segment)
                _close_segment()
        elif segment_open:
            # Pipe open but no frames written. Discard cleanly.
            encoder.abort_segment()

        src.release()
        if obj_filter is not None:
            obj_filter.reset_suppression()
        if show_preview:
            cv2.destroyAllWindows()

        # Shut down the enhancement thread pool. Cancel any pending work.
        # cancel_futures was added in Python 3.9; use try/except for 3.8 compat.
        if _enhance_executor is not None:
            try:
                _enhance_executor.shutdown(wait=False, cancel_futures=True)
            except TypeError:
                _enhance_executor.shutdown(wait=False)

        report = encoder.get_storage_report()
        log.info("Storage report: " + str(report))

        if demo_writer is not None:
            demo_writer.close()



if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Selective compression pipeline")
    parser.add_argument("--input", default=0, help="Camera index or video file path")
    parser.add_argument("--camera-id", default="cam_00")
    parser.add_argument("--output", default="outputs/")
    parser.add_argument("--segment", type=int, default=60, help="Segment duration in seconds")
    parser.add_argument("--method", default="MOG2", choices=["MOG2", "KNN"])
    parser.add_argument(
        "--mode",
        default="mode0",
        choices=["mode0", "mode1", "mode2", "mode3"],
        help=(
            "Pipeline mode: "
            "mode0 = continuous stream, "
            "mode1 = event recording with foreground activity, "
            "mode2 = background keyframe plus bbox patches, "
            "mode3 = object-only bbox pixels on black canvas"
        ),
    )
    parser.add_argument("--demo", action="store_true", help="Write demo JSONL metadata")
    parser.add_argument("--preview", action="store_true")
    parser.add_argument(
        "--warmup",
        type=int,
        default=120,
        help="Warmup frames before encoding starts. Overridden by CDnet temporalROI if available.",
    )
    parser.add_argument(
        "--enhance",
        action="store_true",
        help="Apply super-resolution sharpening to foreground ROIs before encoding.",
    )
    parser.add_argument(
        "--enhance-model",
        default="bicubic",
        help="Enhancement backend label. The current Enhancer auto-selects available backend.",
    )
    parser.add_argument(
        "--enhance-scale",
        type=int,
        default=4,
        choices=[2, 4],
        help="Upscale factor for --enhance.",
    )
    parser.add_argument(
        "--encrypt",
        action="store_true",
        help="Encrypt each output segment with AES-256-GCM. Requires --password or --key-file.",
    )
    parser.add_argument(
        "--mode2-clean-seconds",
        type=float,
        default=2.0,
        help="Consecutive detection-free seconds before mode2 refreshes the clean background.",
    )
    parser.add_argument("--password", default=None, help="Passphrase for AES-256-GCM encryption (PBKDF2).")
    parser.add_argument("--key-file", default=None, help="Path to raw 32-byte AES-256 key file.")
    # ── R4 Phase 2 encoder knobs (docs/RESEARCH-COMPRESSION.md) ──
    parser.add_argument("--codec", default=None,
                        help="Encoder: libx264/libx265/libsvtav1/libaom-av1 or "
                             "h264_nvenc/hevc_nvenc/av1_nvenc (GPU). Unknown/missing -> libx264.")
    parser.add_argument("--crf", type=int, default=None, help="Foreground CRF override (mode default if unset).")
    parser.add_argument("--max-bitrate-kbps", type=int, default=0,
                        help="Storage cap in kbps (capped CRF). 0 = uncapped.")
    parser.add_argument("--gop-seconds", type=int, default=20,
                        help="Keyframe interval in seconds (long GOP for static cameras). 0 = ffmpeg default.")
    parser.add_argument("--denoise", default="", choices=["", "hqdn3d", "atadenoise"],
                        help="Pre-encode denoiser for night/IR footage. Empty = off.")
    parser.add_argument("--roi-qp", action="store_true",
                        help="Encoder-level ROI (x264/x265 only): degrade long-static areas via addroi.")
    parser.add_argument("--target-vmaf", type=float, default=None,
                        help="Target perceptual quality (VMAF 85-97, e.g. 93) instead of a "
                             "fixed CRF. Sample-searches the smallest CRF that clears the "
                             "target; falls back to the fixed CRF if VMAF is unavailable.")
    args = parser.parse_args()

    input_src = args.input
    if input_src != 0:
        input_src = int(input_src) if str(input_src).isdigit() else input_src

    run_pipeline(
        input_source=input_src,
        camera_id=args.camera_id,
        output_dir=args.output,
        segment_seconds=args.segment,
        bg_method=args.method,
        show_preview=args.preview,
        warmup_frames=args.warmup,
        enhance=args.enhance,
        enhance_scale=args.enhance_scale,
        mode=args.mode,
        demo=args.demo,
        enhance_model=args.enhance_model,
        encrypt=args.encrypt,
        encrypt_password=args.password,
        encrypt_key_file=args.key_file,
        mode2_clean_seconds=args.mode2_clean_seconds,
        mode2_background_lag_seconds=args.mode2_background_lag_seconds,
        codec=args.codec,
        crf=args.crf,
        max_bitrate_kbps=args.max_bitrate_kbps,
        gop_seconds=args.gop_seconds,
        denoise=args.denoise,
        roi_qp=args.roi_qp,
        target_vmaf=args.target_vmaf,
    )

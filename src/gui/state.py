"""
src/gui/state.py

Pure in-memory state for the Flask dashboard: the shared locks, the
status/power/demo/HLS dictionaries, the live-log ring buffers, and the small
validator tables. It imports nothing from the rest of the ``gui`` package, so
it is the base layer of the import graph:

    state  <-  logging_setup  <-  services  <-  routes  <-  app

Nothing here starts a thread, opens a file, or touches the network, so every
other module can import these names safely at load time.

Mutation contract: the dictionaries / deques / queues below are mutated
*in place* under their paired lock and are re-exported from ``gui.app`` as
the same object, so writes round-trip automatically. The one scalar that is
*rebound* (``_log_id``) is forwarded from ``gui.app`` via the module
``__getattr__``/``__setattr__`` installed in ``app.py``.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - state extraction).
"""

import collections
import queue
import re
import threading

# ── Shared pipeline state (protected by _state_lock) ─────────────────────────
_state_lock = threading.Lock()

_status: dict = {
    "running": False,
    "start_time": None,
    "config": {},
    "frame_count": 0,
    "segment_count": 0,
    "total_frames": 0,   # 0 = live/unknown, >0 = video file with known length
    "error": None,
    # Resolved SR backend of the current/last run ("realesrgan-<device>" or
    # "bicubic"), so the UI shows what ran, not the requested enhance_model
    # (which may have fallen back).
    "enhancer_backend": None,
    # Segments that were requested encrypted but written as plaintext, taken
    # from the live ROIEncoder because config.encrypt only says what was
    # requested.
    "encryption_failures": 0,
}

# ── Power / hardware metrics ───────────────────────────────────────────────────
# Sampled by a background thread every 2 s while the pipeline is running.
_power_lock = threading.Lock()
_power_state: dict = {
    "cpu_pct":        0.0,   # current process+system CPU %
    "ram_pct":        0.0,   # system RAM %
    "ram_used_mb":    0,
    "ram_total_mb":   0,
    "battery_pct":    None,  # None if no battery / not detectable
    "battery_plugged": None,
    "battery_mins_left": None,
    # Per-mode running averages: {"mode0": {"cpu_sum": 0, "n": 0, "avg": 0.0}, ...}
    "mode_avgs": {},
}

# ── Demo (split-screen) state (protected by _demo_lock) ──────────────────────
_demo_lock = threading.Lock()
_demo_state: dict = {
    "running": False,
    "status": "idle",        # idle | running | done | error
    "modes": [],
    "progress": "",
    "demo_phase": "",        # start | pipeline | render | stitch | done
    "demo_mode": "",         # current mode being processed
    "demo_step": "",         # e.g. "(1/2)"
    "result": None,          # populated on success
    "error": None,
    "last_output_root": "",  # absolute path of most recent demo run output
}

# ── HLS live-stream state (protected by _hls_lock) ───────────────────────────
_hls_lock = threading.Lock()
_hls_state: dict = {
    "running": False,
    "camera_id": None,
    "input_source": None,
    "playlist_url": None,
    "hls_dir": None,
    "error": None,
    "stream_start_time": None,   # epoch float: when FFmpeg process launched
    "ingest_latency_s": None,    # float: seconds from FFmpeg launch to first .ts segment
    # Monotonic time of the latest .ts fetch by any client (None before the
    # first). Drives the idle watchdog: the stream slot is process-wide, so an
    # unwatched stream 409s every later start. Monotonic so a clock change
    # cannot make a live stream look abandoned.
    "last_segment_fetch": None,
    # Rolling end-to-end latency: how long a frame read off RTSP takes to land
    # in a playable .ts chunk. Operators size hardware with it.
    # Author: Bloodawn (KheivenD)
    "latency_avg_s":   None,     # float: rolling avg over last N segments (None until 1+ samples)
    "latency_last_s":  None,     # float: latency of the most recent segment
    "latency_samples": 0,        # int:   how many segments contributed to the average
    "latency_window":  20,       # int:   how many segments are kept in the rolling window
}

# Bounded deques for the latency watcher. `_hls_frame_ts_dq` holds frame-read
# timestamps in arrival order; the watcher pops ~(hls_time * fps) entries per
# new .ts segment and computes the median age. `_hls_segment_latencies` is the
# rolling window behind the API average. The maxlen stops unbounded growth if
# FFmpeg stalls.
# Author: Bloodawn (KheivenD)
_hls_frame_ts_dq: "collections.deque[float]" = collections.deque(maxlen=10000)
_hls_segment_latencies: "collections.deque[float]" = collections.deque(maxlen=20)

# ── Log capture ───────────────────────────────────────────────────────────────
# Live log ring buffers. `_log_id` is the only rebound scalar here (incremented
# under `_log_lock` by the SSE log handler); gui.app forwards it.
_log_queue: queue.Queue = queue.Queue(maxsize=1000)
_log_history: collections.deque = collections.deque(maxlen=300)  # (event_id, line)
_log_id = 0
_log_lock = threading.Lock()

# ── Validators / constants ────────────────────────────────────────────────────
_VALID_MODES   = {"mode0", "mode1", "mode2", "mode3"}
_VALID_BG      = {"MOG2", "KNN", "GMG"}
_VALID_DEVICES = {"auto", "cuda", "mps", "cpu"}
# Every name must map to a real backend in src/enhancement/enhancer.py
# (cv2.dnn_superres or basicsr's RRDBNet), or bicubic would silently run
# under an AI model's label.
_VALID_MODELS  = {"espcn", "fsrcnn", "edsr", "lapsrn", "realesrgan", "realesrnet", "bicubic"}

# Subfolder created inside whichever cloud root (OneDrive / Google Drive) is found.
_CLOUD_SUBFOLDER = "SVCS"

# Filenames allowed by `_safe_filename` (path-safety service).
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")

# Upload extensions accepted by /api/upload: the universal ingest set (standard
# plus vendor/DVR containers, decoded by FrameSource's FFmpeg fallback).
try:
    from utils.video_formats import ALL_INGEST_EXTS as _ALL_INGEST_EXTS
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.utils.video_formats import ALL_INGEST_EXTS as _ALL_INGEST_EXTS
_ALLOWED_EXTENSIONS = set(_ALL_INGEST_EXTS)

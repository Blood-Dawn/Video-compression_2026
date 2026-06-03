"""
src/gui/state.py

Pure in-memory state for the Flask dashboard, extracted from the former
``gui/app.py`` monolith. This module holds *only* data: the shared locks,
the status/power/demo/HLS dictionaries, the live-log ring buffers, and the
small validator / constant tables. It imports nothing from the rest of the
``gui`` package, so it is the base layer of the import graph:

    state  <-  logging_setup  <-  services  <-  routes  <-  app

Nothing here starts a thread, opens a file, or touches the network - that
work stays in ``logging_setup``, the ``services`` layer, and the route
blueprints. Keeping the data flat and side-effect-free is what lets every
other module import these names safely at module load.

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
    # ─── Rolling end-to-end latency (ROADMAP 5.1) ──────────────────────────────
    # Author: Bloodawn (KheivenD)
    # ingest→HLS latency: how long does a frame read off RTSP take to land in
    # a .ts chunk that the browser can play? Cody asked for this explicitly in
    # the April 22 sponsor meeting - operators need it for hardware sizing.
    "latency_avg_s":   None,     # float: rolling avg over last N segments (None until 1+ samples)
    "latency_last_s":  None,     # float: latency of the most recent segment
    "latency_samples": 0,        # int:   how many segments contributed to the average
    "latency_window":  20,       # int:   how many segments are kept in the rolling window
}

# Bounded deques used by the latency watcher (ROADMAP 5.1).
# `_hls_frame_ts_dq` holds frame-read timestamps in arrival order; the watcher
# pops ~(hls_time × fps) entries each time a new .ts segment is detected and
# computes the median age. `_hls_segment_latencies` keeps a rolling window of
# per-segment latencies so the API can report a stable average.
# maxlen on _hls_frame_ts_dq prevents unbounded growth if FFmpeg stalls.
# Author: Bloodawn (KheivenD)
_hls_frame_ts_dq: "collections.deque[float]" = collections.deque(maxlen=10000)
_hls_segment_latencies: "collections.deque[float]" = collections.deque(maxlen=20)

# ── Log capture ───────────────────────────────────────────────────────────────
# Live log ring buffers. `_log_id` is the only *rebound* scalar in this module
# (incremented under `_log_lock` by the SSE log handler in logging_setup); it is
# forwarded from `gui.app` so external `gui.app._log_id` reads/writes round-trip.
_log_queue: queue.Queue = queue.Queue(maxsize=1000)
_log_history: collections.deque = collections.deque(maxlen=300)  # (event_id, line)
_log_id = 0
_log_lock = threading.Lock()

# ── Validators / constants ────────────────────────────────────────────────────
_VALID_MODES   = {"mode0", "mode1", "mode2", "mode3"}
_VALID_BG      = {"MOG2", "KNN", "GMG"}
_VALID_DEVICES = {"auto", "cuda", "mps", "cpu"}
_VALID_MODELS  = {"espcn", "fsrcnn", "edsr", "lapsrn", "realesrnet", "realesrgan", "bicubic"}

# Subfolder created inside whichever cloud root (OneDrive / Google Drive) is found.
_CLOUD_SUBFOLDER = "SVCS"

# Filenames allowed by `_safe_filename` (path-safety service).
_SAFE_FILENAME_RE = re.compile(r"^[a-zA-Z0-9_\-\.]+$")

# Upload extensions accepted by the /api/upload route.
_ALLOWED_EXTENSIONS = {".mp4", ".avi", ".mov", ".mkv", ".h264", ".m4v"}

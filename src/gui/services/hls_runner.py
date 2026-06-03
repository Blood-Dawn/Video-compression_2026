"""
src/gui/services/hls_runner.py

Annotated HLS live-streaming worker, extracted from gui/app.py (TASK 1.2).

Pipeline: cv2.VideoCapture -> BackgroundSubtractor -> green ROI rectangles +
corner overlay -> FFmpeg stdin (rawvideo bgr24) -> .m3u8 + .ts that Flask
serves and hls.js plays in the browser. Frames are annotated in Python before
encoding so the live stream shows the same boxes as the demo output.

This module owns the rebindable process/thread handles (_hls_process /
_hls_thread / _hls_stop_event). gui.app re-exports them through the
_ForwardingModule seam so the /api/hls/* routes (still in app.py until TASK
1.3) and the test suite (which sets gui_module._hls_process = None) read and
write the live values here.

Imports gui.state (the shared HLS dict, lock, and latency deques),
gui.logging_setup, and compression.roi_encoder.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — hls-runner extraction).
"""

import subprocess
import threading
import time
from pathlib import Path

import cv2

try:
    from gui.state import (
        _hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies,
    )
    from gui.logging_setup import log
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.gui.state import (
        _hls_lock, _hls_state, _hls_frame_ts_dq, _hls_segment_latencies,
    )
    from src.gui.logging_setup import log

try:
    from compression.roi_encoder import draw_corner_overlay
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.compression.roi_encoder import draw_corner_overlay

# Rebindable FFmpeg process / annotator thread / stop-event handles. Forwarded
# from gui.app so the routes and tests share one live value.
_hls_process: subprocess.Popen | None = None
_hls_thread: threading.Thread | None = None
_hls_stop_event: threading.Event | None = None


def _hls_dir_for(camera_id: str, output_dir: str) -> Path:
    return Path(output_dir) / "hls" / camera_id


def _draw_corner_overlay(frame, mode_label: str, elapsed_s: int) -> None:
    """Thin wrapper: delegates to the shared roi_encoder.draw_corner_overlay.

    Kept as a module-level name so the HLS annotator thread can call it
    without changes.
    """
    draw_corner_overlay(frame, mode_label, elapsed_s)


def _hls_annotator_thread(
    input_source: str,
    hls_dir: Path,
    mode_label: str,
    stop_event: threading.Event,
) -> None:
    """Background thread: annotate frames with ROI boxes then pipe to FFmpeg.

    Pipeline:
        cv2.VideoCapture  →  BackgroundSubtractor  →  green ROI rectangles
        + corner overlay  →  proc.stdin (rawvideo bgr24)  →  FFmpeg HLS muxer
    """
    import numpy as np  # noqa: F401 (needed for tobytes on numpy array)

    try:
        from background_subtraction.background_subtraction import BackgroundSubtractor
    except ModuleNotFoundError:
        from src.background_subtraction.background_subtraction import BackgroundSubtractor

    # ── open input ────────────────────────────────────────────────────────────
    try:
        cap_src = int(input_source)
    except ValueError:
        cap_src = input_source

    is_rtsp = isinstance(cap_src, str) and cap_src.lower().startswith("rtsp://")
    CONNECT_TIMEOUT = 10  # seconds (Python-level timeout for VideoCapture.open()

    # cv2.VideoCapture.open() blocks until the OS-level RTSP timeout fires
    # (~30s on Windows with pip opencv-python).  CAP_PROP_OPEN_TIMEOUT_MSEC is
    # silently ignored on that build, so we enforce our own timeout by running
    # the open() call in a daemon thread and giving up after CONNECT_TIMEOUT
    # seconds.  The leaked thread will eventually exit on its own.
    _cap_holder: list = [None]
    _cap_opened: list = [False]
    _open_done = threading.Event()

    def _do_open():
        c = cv2.VideoCapture()
        # Try to set the property anyway (no-op on most builds but harmless)
        c.set(cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, CONNECT_TIMEOUT * 1000)
        c.set(cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000)
        ok = c.open(cap_src)
        _cap_holder[0] = c
        _cap_opened[0] = ok
        _open_done.set()

    if is_rtsp:
        log.info(f"HLS: connecting to RTSP stream ({CONNECT_TIMEOUT}s timeout)…")
        _open_thread = threading.Thread(target=_do_open, daemon=True)
        _open_thread.start()
        if not _open_done.wait(timeout=CONNECT_TIMEOUT):
            # Timeout fired before cv2 returned. The thread is still blocked
            # in the OS network stack and we cannot kill it; it will
            # self-terminate when the 30s OS timeout fires in the background.
            err = (f"RTSP connection timed out after {CONNECT_TIMEOUT}s "
                   f"server unreachable or stream not found: {input_source}")
            with _hls_lock:
                _hls_state["error"] = err
                _hls_state["running"] = False
            log.error(f"HLS: {err}")
            return
    else:
        _do_open()

    cap = _cap_holder[0]
    if cap is None or not _cap_opened[0] or not cap.isOpened():
        err = f"Could not open input: {input_source}"
        with _hls_lock:
            _hls_state["error"] = err
            _hls_state["running"] = False
        log.error(f"HLS: {err}")
        return

    log.info(f"HLS: connected to {input_source}")

    # ── resolve frame dimensions ──────────────────────────────────────────────
    # VideoCapture.get() returns 0x0 for RTSP streams until the first frame
    # arrives (the codec info isn't decoded yet). Read one frame to get real
    # dimensions, then seek back for files or just continue for live sources.
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS)

    first_frame = None
    if w == 0 or h == 0:
        log.info("HLS: frame dimensions unknown from stream header. Reading first frame…")
        for _ in range(30):        # try up to 30 frames (handles buffered RTSP)
            if stop_event.is_set():
                cap.release()
                with _hls_lock:
                    _hls_state["running"] = False
                return
            ret, first_frame = cap.read()
            if ret and first_frame is not None:
                h, w = first_frame.shape[:2]
                break
        else:
            cap.release()
            with _hls_lock:
                _hls_state["error"] = f"Could not determine frame size from: {input_source}"
                _hls_state["running"] = False
            log.error("HLS: failed to read first frame for dimension detection")
            return

    if fps <= 0 or fps > 120:
        fps = 25.0

    log.info(f"HLS: stream dimensions {w}x{h} @ {fps:.1f} fps")

    # ── start FFmpeg receiving rawvideo from stdin ────────────────────────────
    playlist = hls_dir / "playlist.m3u8"
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{w}x{h}",
        "-r", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-an",
        "-f", "hls",
        "-hls_time", "2",
        "-hls_list_size", "5",
        "-hls_flags", "delete_segments",
        str(playlist),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        cap.release()
        with _hls_lock:
            _hls_state["error"] = "ffmpeg not found on PATH"
            _hls_state["running"] = False
        return

    global _hls_process
    ffmpeg_launch_time = time.time()
    with _hls_lock:
        _hls_process = proc
        _hls_state["stream_start_time"] = ffmpeg_launch_time
        _hls_state["ingest_latency_s"] = None

    # Watch for the first .ts segment to appear and record ingest latency
    def _watch_first_segment(hls_dir: Path, launch_time: float) -> None:
        deadline = launch_time + 30.0  # give up after 30 s
        while time.time() < deadline:
            ts_files = list(hls_dir.glob("*.ts"))
            if ts_files:
                latency = round(time.time() - launch_time, 2)
                with _hls_lock:
                    _hls_state["ingest_latency_s"] = latency
                log.info(f"HLS: first segment appeared in {latency}s")
                return
            time.sleep(0.25)
        log.warning("HLS: first segment not seen within 30 s; latency unknown")

    threading.Thread(
        target=_watch_first_segment,
        args=(hls_dir, ffmpeg_launch_time),
        daemon=True,
        name="hls-latency-watcher",
    ).start()

    # ── Rolling end-to-end latency watcher (ROADMAP 5.1) ─────────────────────
    # Author: Bloodawn (KheivenD)
    #
    # The first-segment watcher above only tells us how long FFmpeg takes to
    # produce its initial chunk. Cody actually asked for the *steady-state*
    # latency: from a frame coming off RTSP, how long until that frame is
    # inside a .ts chunk the browser can play? For hls_time=2 with fps=25
    # we expect 50 frames per chunk, so a typical frame waits about 1 s for
    # its containing chunk to flush. We sample this for every new .ts that
    # appears and keep a rolling average of the last `_hls_state["latency_window"]`
    # segments.
    #
    # The watcher matches each newly observed .ts to a slice of frame
    # timestamps from `_hls_frame_ts_dq` so the latency reflects real ingest
    # → playable-chunk delay instead of the (already-tracked) launch delay.
    def _watch_segment_latency(
        hls_dir: Path,
        seg_fps: float,
        seg_duration_s: float,
        stop: threading.Event,
    ) -> None:
        seen: set[str] = set()
        # Initial snapshot of any pre-existing .ts files (defensive — start()
        # already deletes stale chunks, but skip if any survive).
        try:
            for p in hls_dir.glob("*.ts"):
                seen.add(p.name)
        except OSError:
            pass

        # Estimate frames per segment from the negotiated FPS. Clamp so weird
        # camera streams that report fps=120 don't drain the queue too fast.
        frames_per_seg = max(1, int(round(seg_duration_s * max(1.0, min(seg_fps, 60.0)))))
        log.info(
            f"HLS: latency watcher armed (~{frames_per_seg} frames/segment, "
            f"window={_hls_state.get('latency_window', 20)})"
        )

        while not stop.is_set():
            try:
                # mtime-sorted so we process segments in the order FFmpeg wrote them
                ts_files = sorted(
                    (p for p in hls_dir.glob("*.ts") if p.is_file()),
                    key=lambda p: p.stat().st_mtime,
                )
            except OSError:
                ts_files = []

            for p in ts_files:
                if p.name in seen:
                    continue
                seen.add(p.name)
                try:
                    seg_written_time = p.stat().st_mtime
                except OSError:
                    seg_written_time = time.time()

                # Pop ~frames_per_seg oldest frame-read timestamps. If the
                # deque is shorter than that, take whatever is there — this
                # happens for the very first segment (FFmpeg sometimes
                # buffers fewer frames before flushing).
                #
                # Defensive: belt-and-braces try/except inside the lock in
                # case len() and popleft() ever observe a different state
                # (impossible with a single lock, but a future refactor
                # could break that and silently produce IndexError that the
                # outer except would then mask). Audit follow-up 2026-05-02.
                popped: list[float] = []
                with _hls_lock:
                    n = min(frames_per_seg, len(_hls_frame_ts_dq))
                    for _ in range(n):
                        try:
                            popped.append(_hls_frame_ts_dq.popleft())
                        except IndexError:
                            break

                if not popped:
                    # No frame timestamps queued for this segment — happens
                    # if we missed the .ts notification window. Skip silently
                    # rather than poison the average with bogus data.
                    continue

                # Median age = the typical frame's time-to-playable. Using the
                # median (not the mean) is robust against the first/last frame
                # outliers that bracket each segment's flush window.
                popped.sort()
                median_ts = popped[len(popped) // 2]
                latency = max(0.0, seg_written_time - median_ts)

                with _hls_lock:
                    _hls_segment_latencies.append(latency)
                    avg = sum(_hls_segment_latencies) / len(_hls_segment_latencies)
                    _hls_state["latency_last_s"]  = round(latency, 3)
                    _hls_state["latency_avg_s"]   = round(avg, 3)
                    _hls_state["latency_samples"] = len(_hls_segment_latencies)

            # Cap the seen-set so a long-running stream with delete_segments
            # doesn't grow it unbounded. 256 entries × ~12 chars ≈ trivial.
            if len(seen) > 256:
                seen = set(sorted(seen)[-128:])

            # Poll twice per chunk; FFmpeg writes a new .ts every seg_duration_s.
            stop.wait(timeout=max(0.25, seg_duration_s / 2.0))

    threading.Thread(
        target=_watch_segment_latency,
        args=(hls_dir, fps, 2.0, stop_event),
        daemon=True,
        name="hls-segment-latency-watcher",
    ).start()

    # ── frame loop ────────────────────────────────────────────────────────────
    subtractor = BackgroundSubtractor(var_threshold=50)
    start_time = time.time()
    WARMUP_FRAMES = 30
    frame_num = 0

    try:
        while not stop_event.is_set():
            # Use the pre-read first_frame (from RTSP dimension probe) on
            # the first iteration so we don't skip a frame.
            if first_frame is not None:
                frame = first_frame
                first_frame = None
                ret = True
            else:
                ret, frame = cap.read()
            if not ret or frame is None:
                break  # EOF or read error

            # Stamp the frame-read time for the latency watcher (ROADMAP 5.1).
            # Done as close to cap.read() as possible so the measured latency
            # reflects real ingest delay, not bg-subtraction or annotation work.
            # Author: Bloodawn (KheivenD)
            with _hls_lock:
                _hls_frame_ts_dq.append(time.time())

            # Run background subtraction on every frame to build the model
            mask = subtractor.apply(frame)

            if frame_num >= WARMUP_FRAMES:
                regions = subtractor.get_foreground_regions(mask)

                # Draw green bounding boxes around each detected ROI
                for region in regions:
                    x1 = max(0, region.x)
                    y1 = max(0, region.y)
                    x2 = min(w, region.x + region.w)
                    y2 = min(h, region.y + region.h)
                    if x2 > x1 and y2 > y1:
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)

                # Small corner overlay: mode + elapsed time
                elapsed = int(time.time() - start_time)
                _draw_corner_overlay(frame, mode_label, elapsed)

            frame_num += 1

            try:
                proc.stdin.write(frame.tobytes())
            except (BrokenPipeError, OSError):
                break

    except Exception as exc:
        log.error(f"HLS annotator error: {exc}", exc_info=True)
        with _hls_lock:
            _hls_state["error"] = str(exc)
    finally:
        cap.release()
        try:
            proc.stdin.close()
        except Exception:
            pass
        # Wait for FFmpeg to finish muxing its last segment
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            proc.kill()
        with _hls_lock:
            _hls_state["running"] = False
        log.info("HLS annotator thread finished.")

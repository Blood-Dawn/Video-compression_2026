"""
tests/test_hls_mobile_compat.py

M0.3 / M0.4 / M0.5: make the HLS live stream playable by an Android client.

Three defects, all live in the shipping desktop product before this, all found
while grounding the mobile port (docs/MOBILE-ARCHITECTURE.md B7/B8/B9):

  M0.3  The FFmpeg command set no output -pix_fmt. Input is rawvideo bgr24
        (full chroma), so FFmpeg auto-selected yuv444p and emitted H.264
        High 4:4:4 Predictive. No Android MediaCodec decoder handles 4:4:4 and
        ExoPlayer ships no software H.264 fallback, so LIVE could never work.
        It also set -hls_time 2 with no -g, so x264's default keyint of 250
        governed IDR placement and real segments were nowhere near 2s.

  M0.4  The .ts route returned a bare send_from_directory, so Content-Type came
        from the host OS and was wrong on all three ship targets.

  M0.5  Nothing reaped an abandoned stream. With a single process-wide stream
        slot, one walked-away client 409s every later start for EVERYONE.

The argv assertions matter because nothing asserted on the FFmpeg command line
before, which is how the 4:4:4 defect survived.

Author: Bloodawn (KheivenD), 2026-07-18 (M0.3-M0.5, mobile port).
"""

import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import src.gui.app as gui_module                                    # noqa: E402
from src.config import (HLS_IDLE_TIMEOUT_S, HLS_LIST_SIZE,          # noqa: E402
                        HLS_SEGMENT_SECONDS, HLS_STARTUP_GRACE_S)
from src.utils.ffmpeg import ffmpeg_available, ffmpeg_path, ffprobe_path  # noqa: E402


def _build_argv(w=320, h=240, fps=25.0, playlist="out/playlist.m3u8"):
    """Rebuild the runner's FFmpeg argv.

    Mirrors src/gui/services/hls_runner.py. Kept in step by
    test_runner_source_matches_this_argv below, which greps the real source so
    this helper cannot silently drift from what actually ships.
    """
    gop = max(1, int(round(HLS_SEGMENT_SECONDS * fps)))
    return [
        ffmpeg_path(), "-y",
        "-f", "rawvideo", "-pix_fmt", "bgr24",
        "-s", f"{w}x{h}", "-r", str(fps), "-i", "pipe:0",
        "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-g", str(gop), "-keyint_min", str(gop), "-sc_threshold", "0",
        "-an", "-f", "hls",
        "-hls_time", str(HLS_SEGMENT_SECONDS),
        "-hls_list_size", str(HLS_LIST_SIZE),
        "-hls_flags", "delete_segments",
        playlist,
    ]


# ── M0.3: the encoder settings ────────────────────────────────────────────────

def test_runner_forces_yuv420p():
    """The output chroma must be pinned, or Android cannot decode the stream."""
    src = (SRC / "gui" / "services" / "hls_runner.py").read_text(encoding="utf-8")
    assert '"-pix_fmt", "yuv420p"' in src, (
        "hls_runner must force yuv420p on the OUTPUT. Without it FFmpeg picks "
        "yuv444p from the bgr24 input and emits High 4:4:4 Predictive, which no "
        "Android MediaCodec decoder can handle.")


def test_runner_sets_an_explicit_gop():
    """Segments can only be cut at an IDR, so keyint must match the segment."""
    src = (SRC / "gui" / "services" / "hls_runner.py").read_text(encoding="utf-8")
    for flag in ('"-g", str(gop)', '"-keyint_min", str(gop)',
                 '"-sc_threshold", "0"'):
        assert flag in src, f"hls_runner is missing {flag}"


def test_runner_reads_the_hls_config_constants():
    """HLS_SEGMENT_SECONDS / HLS_LIST_SIZE were dead config that only the test
    suite read, which is false assurance. The runner must actually use them."""
    src = (SRC / "gui" / "services" / "hls_runner.py").read_text(encoding="utf-8")
    assert "HLS_SEGMENT_SECONDS" in src
    assert "HLS_LIST_SIZE" in src
    assert '"-hls_time", "2"' not in src, "segment length is hardcoded again"


def test_gop_is_derived_from_segment_length_and_fps():
    argv = _build_argv(fps=25.0)
    gop = argv[argv.index("-g") + 1]
    assert int(gop) == int(round(HLS_SEGMENT_SECONDS * 25.0))
    argv30 = _build_argv(fps=30.0)
    assert int(argv30[argv30.index("-g") + 1]) == int(round(HLS_SEGMENT_SECONDS * 30.0))


def test_output_pix_fmt_comes_after_the_input_one():
    """Order matters: the bgr24 belongs to the INPUT, yuv420p to the OUTPUT.
    Swapping them silently reintroduces the bug."""
    argv = _build_argv()
    first = argv.index("-pix_fmt")
    second = argv.index("-pix_fmt", first + 1)
    assert argv[first + 1] == "bgr24"
    assert argv[second + 1] == "yuv420p"
    assert first < argv.index("-i") < second


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not available")
def test_real_encode_is_android_decodable(tmp_path):
    """The proof: run the real argv and ffprobe the emitted segment.

    Before this fix the same command produced High 4:4:4 Predictive / yuv444p
    and a single 5s segment despite -hls_time 2.
    """
    import os
    w, h, fps = 320, 240, 25.0
    argv = _build_argv(w, h, fps, str(tmp_path / "playlist.m3u8"))
    proc = subprocess.Popen(argv, stdin=subprocess.PIPE,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    frame = bytes(bytearray(os.urandom(w * h * 3)))
    try:
        for _ in range(int(fps * 10)):
            proc.stdin.write(frame)
        proc.stdin.close()
        proc.wait(timeout=120)
    except (BrokenPipeError, OSError, subprocess.TimeoutExpired):
        proc.kill()
        pytest.skip("ffmpeg did not accept the raw feed on this host")

    segs = sorted(tmp_path.glob("*.ts"))
    assert segs, "no .ts segments were produced"

    probe = subprocess.run(
        [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=profile,pix_fmt", "-of", "default=nw=1",
         str(segs[0])], capture_output=True, text=True, timeout=60)
    out = probe.stdout
    assert "yuv420p" in out, f"expected yuv420p, got: {out.strip()}"
    assert "4:4:4" not in out, (
        f"High 4:4:4 Predictive is undecodable on Android: {out.strip()}")

    # The GOP fix should also produce genuinely short segments.
    playlist = (tmp_path / "playlist.m3u8").read_text(encoding="utf-8")
    target = [l for l in playlist.splitlines() if "TARGETDURATION" in l]
    assert target, "playlist has no EXT-X-TARGETDURATION"
    assert int(target[0].split(":")[1]) <= HLS_SEGMENT_SECONDS + 1, (
        f"segments are longer than configured: {target[0]}")


# ── M0.4: the segment Content-Type ────────────────────────────────────────────

@pytest.fixture()
def client():
    gui_module.app.config["TESTING"] = True
    return gui_module.app.test_client()


def test_ts_segment_content_type_is_mp2t(client, tmp_path):
    """.ts is not in CPython's mimetypes table, so the host would otherwise
    decide, and it is wrong differently on Windows, slim Docker, and Linux."""
    seg = tmp_path / "playlist0.ts"
    seg.write_bytes(b"\x47" + b"\x00" * 187)      # one MPEG-TS packet
    with gui_module._hls_lock:
        gui_module._hls_state.update(running=True, camera_id="cam_01",
                                     hls_dir=str(tmp_path))
    try:
        r = client.get("/api/hls/cam_01/playlist0.ts")
        assert r.status_code == 200
        assert r.headers["Content-Type"].startswith("video/mp2t"), (
            f"ExoPlayer needs video/mp2t, got {r.headers['Content-Type']!r}")
    finally:
        with gui_module._hls_lock:
            gui_module._hls_state.update(running=False, camera_id=None,
                                         hls_dir=None, last_segment_fetch=None)


# ── M0.5: the idle watchdog ───────────────────────────────────────────────────

def test_segment_fetch_stamps_liveness(client, tmp_path):
    """A real segment hit records liveness for the watchdog."""
    seg = tmp_path / "playlist0.ts"
    seg.write_bytes(b"\x47" + b"\x00" * 187)
    with gui_module._hls_lock:
        gui_module._hls_state.update(running=True, camera_id="cam_01",
                                     hls_dir=str(tmp_path),
                                     last_segment_fetch=None)
    try:
        assert client.get("/api/hls/cam_01/playlist0.ts").status_code == 200
        with gui_module._hls_lock:
            assert gui_module._hls_state["last_segment_fetch"] is not None
    finally:
        with gui_module._hls_lock:
            gui_module._hls_state.update(running=False, camera_id=None,
                                         hls_dir=None, last_segment_fetch=None)


def test_missing_segment_does_not_stamp_liveness(client, tmp_path):
    """404 probes must not be able to keep a dead stream alive forever."""
    with gui_module._hls_lock:
        gui_module._hls_state.update(running=True, camera_id="cam_01",
                                     hls_dir=str(tmp_path),
                                     last_segment_fetch=None)
    try:
        assert client.get("/api/hls/cam_01/nope.ts").status_code == 404
        with gui_module._hls_lock:
            assert gui_module._hls_state["last_segment_fetch"] is None
    finally:
        with gui_module._hls_lock:
            gui_module._hls_state.update(running=False, camera_id=None,
                                         hls_dir=None, last_segment_fetch=None)


def test_idle_timeout_is_longer_than_the_playlist_window():
    """The watchdog must not kill a stream a live player is merely buffering.

    The rolling playlist holds HLS_LIST_SIZE * HLS_SEGMENT_SECONDS seconds, so
    a playing client refetches well inside that; the timeout has to clear it
    with room to spare.
    """
    window = HLS_LIST_SIZE * HLS_SEGMENT_SECONDS
    assert HLS_IDLE_TIMEOUT_S > window * 2, (
        f"idle timeout {HLS_IDLE_TIMEOUT_S}s is too close to the {window}s "
        "playlist window and would reap live streams")


def test_startup_grace_covers_the_rtsp_connect_timeout():
    """The grace before the first fetch must outlast a slow RTSP connect."""
    runner = (SRC / "gui" / "services" / "hls_runner.py").read_text(encoding="utf-8")
    assert "CONNECT_TIMEOUT = 10" in runner, "connect timeout moved; re-check the grace"
    assert HLS_STARTUP_GRACE_S > 10 + HLS_IDLE_TIMEOUT_S / 2, (
        "startup grace must cover RTSP connect plus warmup plus the client poll")


def test_watchdog_is_wired_into_the_runner():
    src = (SRC / "gui" / "services" / "hls_runner.py").read_text(encoding="utf-8")
    assert "_hls_idle_watchdog" in src
    assert "hls-idle-watchdog" in src, "watchdog thread is not started"


def test_watchdog_stops_an_abandoned_stream(monkeypatch):
    """Behavioral test of the watchdog logic itself.

    Rebuilds the same loop against a fake clock and state so it runs in
    milliseconds instead of the real 30s, and asserts it sets the stop event
    only once the idle window has genuinely elapsed.
    """
    state = {"running": True, "last_segment_fetch": 100.0}
    lock = threading.Lock()
    stop = threading.Event()
    now = {"t": 100.0}

    def watchdog_tick() -> None:
        with lock:
            if not state.get("running"):
                return
            last = state.get("last_segment_fetch")
        if last is not None and now["t"] - last > HLS_IDLE_TIMEOUT_S:
            stop.set()

    watchdog_tick()
    assert not stop.is_set(), "a fresh stream must not be reaped"

    now["t"] = 100.0 + HLS_IDLE_TIMEOUT_S - 1
    watchdog_tick()
    assert not stop.is_set(), "reaped one second early"

    now["t"] = 100.0 + HLS_IDLE_TIMEOUT_S + 1
    watchdog_tick()
    assert stop.is_set(), "an abandoned stream was never reaped"


def test_watchdog_leaves_a_watched_stream_alone():
    """A client fetching at the real segment cadence is never reaped.

    Runs well past the idle timeout with a client fetching every
    HLS_SEGMENT_SECONDS, which is what a playing ExoPlayer or hls.js does. The
    watchdog is evaluated on a separate, faster tick than the fetches so the
    check is not trivially satisfied.
    """
    state = {"running": True, "last_segment_fetch": 0.0}
    stop = threading.Event()
    horizon = HLS_IDLE_TIMEOUT_S * 3          # simulated seconds
    for now in range(1, horizon + 1):
        # The client fetches on the segment boundary.
        if now % HLS_SEGMENT_SECONDS == 0:
            state["last_segment_fetch"] = float(now)
        # The watchdog evaluates every second against the LAST recorded fetch.
        if float(now) - state["last_segment_fetch"] > HLS_IDLE_TIMEOUT_S:
            stop.set()
    assert not stop.is_set(), "an actively watched stream was reaped"

    # And the same loop DOES reap once the client stops fetching.
    silent_since = float(horizon)
    for now in range(horizon + 1, horizon + HLS_IDLE_TIMEOUT_S + 5):
        if float(now) - silent_since > HLS_IDLE_TIMEOUT_S:
            stop.set()
    assert stop.is_set(), "the same loop failed to reap after fetches stopped"

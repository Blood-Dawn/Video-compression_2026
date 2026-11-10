"""Pins the helpers taken out of hls_runner._hls_annotator_thread."""

import sys
import threading
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import hls_runner as hr  # noqa: E402


# -- ffmpeg command ----------------------------------------------------------


def test_ffmpeg_command_has_the_flags_mobile_playback_needs(monkeypatch):
    monkeypatch.setattr(hr, "ffmpeg_path", lambda: "FFMPEG")
    cmd = hr._build_hls_ffmpeg_cmd(320, 240, 25.0, 50, Path("out") / "playlist.m3u8")
    assert cmd[0] == "FFMPEG" and cmd[-1] == str(Path("out") / "playlist.m3u8")
    pairs = {cmd[i]: cmd[i + 1] for i in range(1, len(cmd) - 1) if cmd[i].startswith("-")}
    assert pairs["-s"] == "320x240" and pairs["-r"] == "25.0" and pairs["-i"] == "pipe:0"
    assert pairs["-g"] == "50" and pairs["-keyint_min"] == "50" and pairs["-sc_threshold"] == "0"
    assert pairs["-tune"] == "zerolatency" and pairs["-preset"] == "ultrafast"
    assert pairs["-hls_time"] == str(hr.HLS_SEGMENT_SECONDS)
    assert pairs["-hls_list_size"] == str(hr.HLS_LIST_SIZE)
    assert pairs["-hls_flags"] == "delete_segments"
    # Output chroma is forced; input stays bgr24. Android cannot decode 4:4:4.
    assert cmd.count("-pix_fmt") == 2
    assert cmd[cmd.index("-pix_fmt") + 1] == "bgr24"
    assert cmd[len(cmd) - 1 - cmd[::-1].index("-pix_fmt") + 1] == "yuv420p"
    assert "-an" in cmd


# -- frame size probe --------------------------------------------------------


class FakeCap:
    def __init__(self, w=0, h=0, fps=25.0, frames=()):
        self.props = {hr.cv2.CAP_PROP_FRAME_WIDTH: w, hr.cv2.CAP_PROP_FRAME_HEIGHT: h,
                      hr.cv2.CAP_PROP_FPS: fps}
        self.frames = list(frames)
        self.released = False
        self.reads = 0

    def get(self, prop):
        return self.props[prop]

    def read(self):
        self.reads += 1
        return self.frames.pop(0) if self.frames else (False, None)

    def release(self):
        self.released = True


def test_known_size_is_returned_without_reading_a_frame():
    cap = FakeCap(640, 480, 30.0)
    assert hr._probe_frame_size(cap, threading.Event()) == (640, 480, 30.0, None, "ok")
    assert cap.reads == 0 and not cap.released


@pytest.mark.parametrize("fps,expected", [(0, 25.0), (-3, 25.0), (121, 25.0), (120, 120), (1, 1)])
def test_odd_fps_becomes_25(fps, expected):
    assert hr._probe_frame_size(FakeCap(10, 10, fps), threading.Event())[2] == expected


def test_unknown_size_is_learned_from_the_first_frame_and_kept():
    frame = np.zeros((90, 160, 3), dtype=np.uint8)
    cap = FakeCap(0, 0, 25.0, frames=[(False, None), (True, frame)])
    w, h, fps, first, outcome = hr._probe_frame_size(cap, threading.Event())
    assert (w, h, outcome) == (160, 90, "ok") and first is frame and not cap.released


def test_no_frame_in_30_reads_fails_and_releases():
    cap = FakeCap(0, 0)
    *_, first, outcome = hr._probe_frame_size(cap, threading.Event())
    assert outcome == "failed" and first is None and cap.released and cap.reads == 30


def test_a_set_stop_event_stops_the_probe_before_any_read():
    stop = threading.Event()
    stop.set()
    cap = FakeCap(0, 0)
    *_, outcome = hr._probe_frame_size(cap, stop)
    assert outcome == "stopped" and cap.released and cap.reads == 0


# -- capture opening ---------------------------------------------------------


class OpenCap:
    def __init__(self, ok):
        self.ok = ok

    def set(self, *a):
        return True

    def open(self, src):
        self.src = src
        return self.ok

    def isOpened(self):
        return self.ok


def test_open_failure_returns_the_message_not_a_cap(monkeypatch):
    monkeypatch.setattr(hr.cv2, "VideoCapture", lambda: OpenCap(False))
    cap, err = hr._open_capture("nope.mp4")
    assert cap is None and err == "Could not open input: nope.mp4"


def test_open_success_returns_the_cap(monkeypatch):
    made = []
    monkeypatch.setattr(hr.cv2, "VideoCapture", lambda: made.append(OpenCap(True)) or made[-1])
    cap, err = hr._open_capture("clip.mp4")
    assert err is None and cap is made[0] and cap.src == "clip.mp4"


def test_digit_strings_open_as_camera_indexes(monkeypatch):
    made = []
    monkeypatch.setattr(hr.cv2, "VideoCapture", lambda: made.append(OpenCap(True)) or made[-1])
    hr._open_capture("2")
    assert made[0].src == 2

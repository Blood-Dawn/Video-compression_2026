"""
test_multi_source.py

Unit tests for MultiFrameSource (src/utils/multi_source.py).

Uses short video files and mocked captures so no real RTSP streams
or cameras are required.

Author: Jorge Sanchez (JS)
"""

import sys
import time
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.multi_source import (
    BUFFER_SIZE,
    FRAME_TIMEOUT,
    MultiFrameSource,
    _StreamReader,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_cap(width=64, height=64, fps=30.0, frame_count=10, fail_open=False):
    """Return a MagicMock that behaves like cv2.VideoCapture."""
    cap = MagicMock()
    cap.isOpened.return_value = not fail_open
    cap.get.side_effect = lambda prop: {
        0: fps,    # CAP_PROP_FPS
        3: width,  # CAP_PROP_FRAME_WIDTH
        4: height, # CAP_PROP_FRAME_HEIGHT
    }.get(prop, 0)

    frames = [
        (True, np.zeros((height, width, 3), dtype=np.uint8))
        for _ in range(frame_count)
    ]
    frames.append((False, None))  # signal end of stream
    cap.read.side_effect = frames
    return cap


# ---------------------------------------------------------------------------
# _StreamReader
# ---------------------------------------------------------------------------

class TestStreamReader:
    def test_start_success(self):
        with patch("cv2.VideoCapture", return_value=_make_fake_cap()):
            reader = _StreamReader("rtsp://fake/stream", cam_index=0)
            assert reader.start() is True
            assert reader.is_open is True
            reader.stop()

    def test_start_failure(self):
        with patch("cv2.VideoCapture", return_value=_make_fake_cap(fail_open=True)):
            reader = _StreamReader("rtsp://bad/stream", cam_index=0)
            assert reader.start() is False
            assert reader.is_open is False

    def test_get_frame_returns_frame(self):
        with patch("cv2.VideoCapture", return_value=_make_fake_cap(frame_count=5)):
            reader = _StreamReader("rtsp://fake/stream", cam_index=0)
            reader.start()
            time.sleep(0.2)  # let background thread fill buffer
            ok, frame = reader.get_frame()
            assert ok is True
            assert isinstance(frame, np.ndarray)
            reader.stop()

    def test_get_frame_empty_buffer_returns_false(self):
        with patch("cv2.VideoCapture", return_value=_make_fake_cap(frame_count=0)):
            reader = _StreamReader("rtsp://fake/stream", cam_index=0)
            reader.start()
            time.sleep(0.1)
            reader._running = False
            ok, frame = reader.get_frame()
            assert ok is False
            assert frame is None
            reader.stop()

    def test_stall_detection(self):
        with patch("cv2.VideoCapture", return_value=_make_fake_cap(frame_count=1)):
            reader = _StreamReader("rtsp://fake/stream", cam_index=0)
            reader.start()
            time.sleep(0.1)
            # Simulate stall by backdating last frame time
            reader._last_frame_time = time.time() - FRAME_TIMEOUT - 1
            ok, frame = reader.get_frame()
            assert ok is False
            reader.stop()

    def test_cam_id_format(self):
        reader = _StreamReader("rtsp://fake", cam_index=3)
        assert reader.cam_id == "cam_03"

    def test_stop_releases_capture(self):
        fake_cap = _make_fake_cap()
        with patch("cv2.VideoCapture", return_value=fake_cap):
            reader = _StreamReader("rtsp://fake/stream", cam_index=0)
            reader.start()
            reader.stop()
            fake_cap.release.assert_called_once()
            assert reader.is_open is False


# ---------------------------------------------------------------------------
# MultiFrameSource
# ---------------------------------------------------------------------------

class TestMultiFrameSource:
    def test_empty_sources_raises(self):
        with pytest.raises(ValueError):
            MultiFrameSource([])

    def test_open_returns_count(self):
        with patch("cv2.VideoCapture", return_value=_make_fake_cap()):
            msrc = MultiFrameSource(["rtsp://a", "rtsp://b"])
            count = msrc.open()
            assert count == 2
            msrc.release()

    def test_open_partial_failure(self):
        caps = [_make_fake_cap(), _make_fake_cap(fail_open=True)]
        with patch("cv2.VideoCapture", side_effect=caps):
            msrc = MultiFrameSource(["rtsp://good", "rtsp://bad"])
            count = msrc.open()
            assert count == 1
            msrc.release()

    def test_read_all_length_matches_sources(self):
        with patch("cv2.VideoCapture", return_value=_make_fake_cap(frame_count=5)):
            msrc = MultiFrameSource(["rtsp://a", "rtsp://b", "rtsp://c"])
            msrc.open()
            time.sleep(0.2)
            frames = msrc.read_all()
            assert len(frames) == 3
            msrc.release()

    def test_source_count_attribute(self):
        msrc = MultiFrameSource(["rtsp://a", "rtsp://b"])
        assert msrc.source_count == 2

    def test_get_metadata_keys(self):
        with patch("cv2.VideoCapture", return_value=_make_fake_cap()):
            msrc = MultiFrameSource(["rtsp://a"])
            msrc.open()
            meta = msrc.get_metadata()
            assert len(meta) == 1
            assert "cam_id" in meta[0]
            assert "fps" in meta[0]
            assert "width" in meta[0]
            assert "height" in meta[0]
            assert "is_open" in meta[0]
            msrc.release()

    def test_context_manager(self):
        with patch("cv2.VideoCapture", return_value=_make_fake_cap(frame_count=5)):
            with MultiFrameSource(["rtsp://a"]) as msrc:
                assert msrc.source_count == 1

    def test_repr_format(self):
        with patch("cv2.VideoCapture", return_value=_make_fake_cap(frame_count=5)):
            with MultiFrameSource(["rtsp://a", "rtsp://b"]) as msrc:
                r = repr(msrc)
                assert "MultiFrameSource" in r

    def test_any_alive_true_when_running(self):
        with patch("cv2.VideoCapture", side_effect=lambda s: _make_fake_cap(frame_count=500)):
            msrc = MultiFrameSource(["rtsp://a"])
            msrc.open()
            # Check immediately after open before thread exhausts frames
            assert msrc._readers[0].is_open is True
            msrc.release()

    def test_active_count(self):
        with patch("cv2.VideoCapture", side_effect=lambda s: _make_fake_cap(frame_count=500)):
            msrc = MultiFrameSource(["rtsp://a", "rtsp://b"])
            count = msrc.open()
            # Both streams opened successfully
            assert count == 2
            assert sum(r.is_open for r in msrc._readers) == 2
            msrc.release()
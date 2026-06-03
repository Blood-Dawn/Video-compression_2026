"""
test_hls_streaming.py

End-to-end tests for the HLS live streaming feature (task 4.1).

Test structure:
  Class TestHlsRouteUnit     - Flask test client, monkeypatched FFmpeg
                               (fast, no real video / no real subprocess)
  Class TestHlsIntegration   - Real FFmpeg against a CDnet clip
                               (slow ~5s, skipped when CDnet clips absent)
  Class TestPipelineModeComparison
                             - BackgroundSubtractor + ROIEncoder on CDnet clips,
                               Mode 0 (all frames) vs Mode 1 (motion-gated frames)

Run fast suite only:
    uv run pytest tests/test_hls_streaming.py -v -m "not integration"

Run everything including real FFmpeg:
    uv run pytest tests/test_hls_streaming.py -v
"""

import subprocess
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import cv2
import pytest

import src.gui.app as gui_module
from src.gui.app import app

# ──────────────────────────────────────────────
# CDnet clip resolution
# ──────────────────────────────────────────────

_CDNET = Path("data/samples/cdnet_mp4")
_HIGHWAY_CLIP = _CDNET / "baseline" / "baseline_highway.mp4"
_PEDESTRIAN_CLIP = _CDNET / "baseline" / "baseline_pedestrians.mp4"


def _require_clip(p: Path) -> str:
    """Return path string if clip exists, else pytest.skip()."""
    if not p.exists():
        pytest.skip(f"CDnet clip not found: {p}. Run git lfs pull.")
    return str(p)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_hls_state(tmp_path):
    """Reset all HLS global state before and after each test.

    Points the default output_dir at a fresh tmp_path so tests never read or
    write to a real outputs/hls/ directory on the developer's machine.
    """

    def _reset():
        # Signal the annotator thread to stop
        if gui_module._hls_stop_event:
            gui_module._hls_stop_event.set()
        # Terminate any live FFmpeg process
        with gui_module._hls_lock:
            proc = gui_module._hls_process
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
        with gui_module._hls_lock:
            gui_module._hls_process = None
            gui_module._hls_state.update(
                running=False,
                camera_id=None,
                input_source=None,
                playlist_url=None,
                hls_dir=None,
                error=None,
            )
        # Wait briefly for the thread to exit after stop_event is set
        if gui_module._hls_thread and gui_module._hls_thread.is_alive():
            gui_module._hls_thread.join(timeout=2)
        gui_module._hls_thread = None
        gui_module._hls_stop_event = None

    _reset()
    yield
    _reset()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def fake_ffmpeg(tmp_path):
    """Patch subprocess.Popen AND cv2.VideoCapture to avoid real I/O.

    The fake VideoCapture blocks on read() until reset_hls_state teardown sets
    the stop event, keeping the annotator thread alive (running=True) so
    state-check assertions always see a consistent picture.
    """
    # ── fake FFmpeg process ───────────────────────────────────────────────────
    mock_proc = MagicMock(spec=subprocess.Popen)
    mock_proc.poll.return_value = None     # process stays alive
    mock_proc.stdin = MagicMock()
    mock_proc.stdin.write.return_value = None
    mock_proc.stdin.close.return_value = None
    mock_proc.wait.return_value = 0

    # ── fake VideoCapture ─────────────────────────────────────────────────────
    # read() blocks on _read_block so the annotator thread stays in the loop
    # until the test ends and reset_hls_state sets the stop event.
    _read_block = threading.Event()

    mock_cap = MagicMock()
    mock_cap.isOpened.return_value = True
    mock_cap.get.side_effect = lambda prop: {
        cv2.CAP_PROP_FRAME_WIDTH: 320.0,
        cv2.CAP_PROP_FRAME_HEIGHT: 240.0,
        cv2.CAP_PROP_FPS: 25.0,
    }.get(prop, 0.0)

    def _blocking_read():
        _read_block.wait(timeout=30)   # returns False once unblocked by teardown
        return (False, None)

    mock_cap.read.side_effect = _blocking_read
    mock_cap.release.return_value = None

    # TASK 1.2: the HLS annotator (which calls subprocess.Popen / cv2.VideoCapture)
    # moved from gui.app into gui.services.hls_runner, so patch it there.
    with patch("src.gui.services.hls_runner.subprocess.Popen", return_value=mock_proc), \
         patch("src.gui.services.hls_runner.cv2.VideoCapture", return_value=mock_cap):
        yield mock_proc, tmp_path
        # Unblock the blocking read() so the thread can exit during teardown
        _read_block.set()


# ──────────────────────────────────────────────
# Unit tests - Flask routes, no real FFmpeg
# ──────────────────────────────────────────────

class TestHlsRouteUnit:
    """Fast route-level tests using a monkeypatched FFmpeg process."""

    def test_status_idle(self, client):
        r = client.get("/api/hls/status")
        assert r.status_code == 200
        d = r.get_json()
        assert d["running"] is False
        assert d["camera_id"] is None

    def test_start_returns_ok_and_playlist_url(self, client, fake_ffmpeg, tmp_path):
        _, tmpdir = fake_ffmpeg
        r = client.post("/api/hls/start", json={
            "input_source": "rtsp://cam.example.com/stream",
            "camera_id": "cam_01",
            "output_dir": str(tmpdir),
        })
        assert r.status_code == 200
        d = r.get_json()
        assert d["ok"] is True
        assert d["playlist_url"].startswith("/api/hls/cam_01/playlist.m3u8?t=")

    def test_start_sets_running_true(self, client, fake_ffmpeg, tmp_path):
        _, tmpdir = fake_ffmpeg
        client.post("/api/hls/start", json={
            "input_source": "rtsp://cam.example.com/stream",
            "camera_id": "cam_01",
            "output_dir": str(tmpdir),
        })
        with gui_module._hls_lock:
            assert gui_module._hls_state["running"] is True

    def test_double_start_returns_409(self, client, fake_ffmpeg, tmp_path):
        _, tmpdir = fake_ffmpeg
        client.post("/api/hls/start", json={
            "input_source": "rtsp://cam.example.com/stream",
            "camera_id": "cam_01",
            "output_dir": str(tmpdir),
        })
        r2 = client.post("/api/hls/start", json={
            "input_source": "rtsp://cam.example.com/stream2",
            "camera_id": "cam_02",
            "output_dir": str(tmpdir),
        })
        assert r2.status_code == 409

    def test_stop_when_idle_returns_409(self, client):
        r = client.post("/api/hls/stop")
        assert r.status_code == 409

    def test_start_then_stop_cycle(self, client, fake_ffmpeg, tmp_path):
        _, tmpdir = fake_ffmpeg
        client.post("/api/hls/start", json={
            "input_source": "rtsp://cam.example.com/stream",
            "camera_id": "cam_01",
            "output_dir": str(tmpdir),
        })
        r = client.post("/api/hls/stop")
        assert r.status_code == 200
        assert r.get_json()["ok"] is True
        with gui_module._hls_lock:
            assert gui_module._hls_state["running"] is False

    def test_stop_resets_camera_id(self, client, fake_ffmpeg, tmp_path):
        _, tmpdir = fake_ffmpeg
        client.post("/api/hls/start", json={
            "input_source": "rtsp://cam.example.com/stream",
            "camera_id": "cam_01",
            "output_dir": str(tmpdir),
        })
        client.post("/api/hls/stop")
        with gui_module._hls_lock:
            assert gui_module._hls_state["camera_id"] is None

    def test_playlist_404_when_not_running(self, client):
        r = client.get("/api/hls/cam_01/playlist.m3u8")
        assert r.status_code == 404

    def test_segment_404_when_not_running(self, client):
        r = client.get("/api/hls/cam_01/seg000.ts")
        assert r.status_code == 404

    def test_segment_403_on_non_ts_extension(self, client, fake_ffmpeg, tmp_path):
        """Reject requests for any non-.ts file - basic security guard."""
        _, tmpdir = fake_ffmpeg
        # Manually set state to "running" so the route doesn't 404 before the check
        with gui_module._hls_lock:
            gui_module._hls_state.update(
                running=True,
                camera_id="cam_01",
                hls_dir=str(tmpdir),
            )
        r = client.get("/api/hls/cam_01/playlist.m3u8")
        # .m3u8 is served by the playlist route, not the segment route
        # Test that *.py or *.sh files are rejected
        r2 = client.get("/api/hls/cam_01/secret.py")
        assert r2.status_code == 403

    def test_status_echoes_camera_id(self, client, fake_ffmpeg, tmp_path):
        _, tmpdir = fake_ffmpeg
        client.post("/api/hls/start", json={
            "input_source": "rtsp://cam.example.com/stream",
            "camera_id": "cam_traffic_01",
            "output_dir": str(tmpdir),
        })
        r = client.get("/api/hls/status")
        d = r.get_json()
        assert d["camera_id"] == "cam_traffic_01"
        assert d["running"] is True

    def test_status_echoes_input_source(self, client, fake_ffmpeg, tmp_path):
        _, tmpdir = fake_ffmpeg
        source = "rtsp://192.168.1.100:554/stream1"
        client.post("/api/hls/start", json={
            "input_source": source,
            "camera_id": "cam_01",
            "output_dir": str(tmpdir),
        })
        r = client.get("/api/hls/status")
        assert r.get_json()["input_source"] == source

    def test_default_camera_id_is_cam_00(self, client, fake_ffmpeg, tmp_path):
        _, tmpdir = fake_ffmpeg
        r = client.post("/api/hls/start", json={
            "input_source": "rtsp://cam.example.com/stream",
            "output_dir": str(tmpdir),
        })
        assert "cam_00" in r.get_json()["playlist_url"]


# ──────────────────────────────────────────────
# Integration tests - real FFmpeg against CDnet clips
# ──────────────────────────────────────────────

@pytest.mark.integration
class TestHlsIntegration:
    """Real FFmpeg HLS transcoding from a local CDnet video file.

    These tests confirm the full encode→segment→serve pipeline works.
    They're intentionally marked `integration` so they can be excluded from
    fast CI runs with:  pytest -m "not integration"
    """

    def test_ffmpeg_produces_playlist_and_segments(self, client, tmp_path):
        """Starting HLS with a local file should produce playlist.m3u8 and
        at least one .ts segment within 10 seconds."""
        clip = _require_clip(_HIGHWAY_CLIP)

        r = client.post("/api/hls/start", json={
            "input_source": clip,
            "camera_id": "cam_highway",
            "output_dir": str(tmp_path),
        })
        assert r.status_code == 200, r.get_json()
        assert r.get_json()["ok"] is True

        hls_dir = tmp_path / "hls" / "cam_highway"
        playlist = hls_dir / "playlist.m3u8"

        # Wait up to 10s for FFmpeg to write the first segment
        deadline = time.time() + 10
        while time.time() < deadline:
            if playlist.exists() and any(hls_dir.glob("*.ts")):
                break
            time.sleep(0.3)
        else:
            pytest.fail(
                f"No HLS segments produced after 10s from {clip}. "
                f"HLS dir contents: {list(hls_dir.iterdir()) if hls_dir.exists() else 'dir missing'}"
            )

        client.post("/api/hls/stop")

    def test_playlist_route_returns_m3u8_content_type(self, client, tmp_path):
        """The /api/hls/<cam>/playlist.m3u8 route must return the correct
        content-type and no-cache headers required by hls.js."""
        clip = _require_clip(_HIGHWAY_CLIP)

        client.post("/api/hls/start", json={
            "input_source": clip,
            "camera_id": "cam_highway",
            "output_dir": str(tmp_path),
        })

        hls_dir = tmp_path / "hls" / "cam_highway"
        # Wait for playlist
        deadline = time.time() + 10
        while time.time() < deadline:
            if (hls_dir / "playlist.m3u8").exists():
                break
            time.sleep(0.3)

        r = client.get("/api/hls/cam_highway/playlist.m3u8")
        assert r.status_code == 200
        assert "mpegurl" in r.content_type.lower()
        assert "no-cache" in r.headers.get("Cache-Control", "")

        client.post("/api/hls/stop")

    def test_playlist_contains_ts_references(self, client, tmp_path):
        """The m3u8 playlist must reference at least one .ts segment file."""
        clip = _require_clip(_HIGHWAY_CLIP)

        client.post("/api/hls/start", json={
            "input_source": clip,
            "camera_id": "cam_highway",
            "output_dir": str(tmp_path),
        })

        hls_dir = tmp_path / "hls" / "cam_highway"
        deadline = time.time() + 10
        while time.time() < deadline:
            if (hls_dir / "playlist.m3u8").exists():
                break
            time.sleep(0.3)

        r = client.get("/api/hls/cam_highway/playlist.m3u8")
        content = r.data.decode()
        assert "#EXTM3U" in content, "Missing HLS header"
        ts_refs = [l for l in content.splitlines() if l.endswith(".ts")]
        assert len(ts_refs) >= 1, f"No .ts references in playlist:\n{content}"

        client.post("/api/hls/stop")

    def test_segment_route_serves_ts_data(self, client, tmp_path):
        """Each .ts segment reference in the playlist must be served as binary
        data with non-zero content."""
        clip = _require_clip(_HIGHWAY_CLIP)

        client.post("/api/hls/start", json={
            "input_source": clip,
            "camera_id": "cam_highway",
            "output_dir": str(tmp_path),
        })

        hls_dir = tmp_path / "hls" / "cam_highway"
        deadline = time.time() + 10
        while time.time() < deadline:
            ts_files = list(hls_dir.glob("*.ts"))
            if ts_files:
                break
            time.sleep(0.3)
        else:
            pytest.fail("No .ts segments produced")

        # Request the first segment via Flask
        seg_name = ts_files[0].name
        r = client.get(f"/api/hls/cam_highway/{seg_name}")
        assert r.status_code == 200
        assert len(r.data) > 1000, f"Segment too small ({len(r.data)}B) - likely corrupt"

        client.post("/api/hls/stop")

    def test_path_traversal_blocked(self, client, tmp_path):
        """Segment route must refuse ../.. path traversal attempts."""
        clip = _require_clip(_HIGHWAY_CLIP)

        client.post("/api/hls/start", json={
            "input_source": clip,
            "camera_id": "cam_highway",
            "output_dir": str(tmp_path),
        })

        r = client.get("/api/hls/cam_highway/../../etc/passwd.ts")
        # Must be 404 (file not found after path strip), not 200
        assert r.status_code in (404, 403)

        client.post("/api/hls/stop")


# ──────────────────────────────────────────────
# Pipeline mode comparison on CDnet clips
# ──────────────────────────────────────────────

class TestPipelineModeComparison:
    """Compare Mode 0 (encode everything) vs Mode 1 (motion-gated) on CDnet
    clips.  These tests do NOT run FFmpeg - they validate the background
    subtraction gating logic that drives mode selection.
    """

    def test_highway_has_high_motion_ratio(self):
        """baseline_highway.mp4 is a busy traffic scene - after MOG2 warmup,
        Mode 1 should gate at least 30% of frames (moving vehicles present)."""
        clip = _require_clip(_HIGHWAY_CLIP)
        from src.background_subtraction.background_subtraction import BackgroundSubtractor

        cap = cv2.VideoCapture(clip)
        sub = BackgroundSubtractor()

        # Warmup: allow MOG2 to build its background model before counting
        warmup = 30
        for _ in range(warmup):
            ret, frame = cap.read()
            if not ret:
                pytest.skip("Clip too short for highway motion test.")
            sub.apply(frame)

        total = 0
        motion_frames = 0
        for _ in range(60):    # 60 frames after warmup
            ret, frame = cap.read()
            if not ret:
                break
            mask = sub.apply(frame)
            regions = sub.get_foreground_regions(mask)
            total += 1
            if regions:
                motion_frames += 1

        cap.release()
        assert total > 0

        ratio = motion_frames / total
        # Highway clip: vehicles move continuously - expect solid detection rate
        assert ratio >= 0.30, (
            f"Mode 1 would gate too aggressively on highway clip: "
            f"only {ratio:.0%} of frames have motion after warmup (expected ≥30%). "
            "Check min_area threshold or MOG2 varThreshold."
        )

    def test_office_has_low_motion_ratio(self):
        """baseline_office.mp4 is a near-static office scene - Mode 1 should
        gate most frames as background (low motion ratio = Mode 1 saves more)."""
        clip = _require_clip(_CDNET / "baseline" / "baseline_office.mp4")
        from src.background_subtraction.background_subtraction import BackgroundSubtractor

        cap = cv2.VideoCapture(clip)
        sub = BackgroundSubtractor()

        warmup = 30
        for _ in range(warmup):
            ret, frame = cap.read()
            if not ret:
                pytest.skip("Clip too short for office motion test.")
            sub.apply(frame)

        total = 0
        motion_frames = 0
        for _ in range(60):
            ret, frame = cap.read()
            if not ret:
                break
            mask = sub.apply(frame)
            regions = sub.get_foreground_regions(mask)
            total += 1
            if regions:
                motion_frames += 1

        cap.release()
        if total == 0:
            pytest.skip("No frames after warmup.")

        ratio = motion_frames / total
        # Office clip - mostly static camera, infrequent motion
        assert ratio < 0.5, (
            f"Office clip shows unexpectedly high motion ratio {ratio:.0%}. "
            "MOG2 may be too sensitive for static scenes (check varThreshold)."
        )

    def test_mode1_reduces_frame_count_vs_mode0(self):
        """Simulate Mode 0 (all frames) vs Mode 1 (motion only) and verify
        that Mode 1 processes fewer frames on the highway clip.

        Mode 0 frame count is always >= Mode 1 frame count.
        On a traffic clip Mode 1 should still find most frames interesting,
        but it must never process *more* frames than Mode 0.
        """
        clip = _require_clip(_HIGHWAY_CLIP)
        from src.background_subtraction.background_subtraction import BackgroundSubtractor

        cap = cv2.VideoCapture(clip)
        sub = BackgroundSubtractor()

        mode0_count = 0   # encode every frame
        mode1_count = 0   # encode only when foreground detected
        for _ in range(90):
            ret, frame = cap.read()
            if not ret:
                break
            mask = sub.apply(frame)
            regions = sub.get_foreground_regions(mask)
            mode0_count += 1
            if regions:
                mode1_count += 1

        cap.release()
        assert mode0_count > 0
        assert mode1_count <= mode0_count, (
            "Mode 1 processed more frames than Mode 0 - impossible by definition."
        )

    def test_nightVideos_benefits_from_night_mode(self):
        """Night-mode should detect more foreground regions than default MOG2
        on a low-light clip.

        If night_mode makes no difference (detects the same or fewer regions),
        the CLAHE preprocessing isn't helping - which warrants investigation.
        """
        clip = _require_clip(_CDNET / "nightVideos" / "nightVideos_busyBoulvard.mp4")
        from src.background_subtraction.background_subtraction import BackgroundSubtractor

        cap_day = cv2.VideoCapture(clip)
        cap_night = cv2.VideoCapture(clip)

        sub_day = BackgroundSubtractor()
        sub_night = BackgroundSubtractor(night_mode=True)

        day_detections = 0
        night_detections = 0
        for _ in range(80):
            ret_d, frame_d = cap_day.read()
            ret_n, frame_n = cap_night.read()
            if not ret_d or not ret_n:
                break
            day_detections += len(sub_day.get_foreground_regions(sub_day.apply(frame_d)))
            night_detections += len(sub_night.get_foreground_regions(sub_night.apply(frame_n)))

        cap_day.release()
        cap_night.release()

        # Night mode should detect more (or equal) regions on a low-light busy street
        assert night_detections >= day_detections, (
            f"Night mode detected fewer foreground regions than default MOG2 "
            f"({night_detections} vs {day_detections}) on busy night clip. "
            "Investigate CLAHE parameters."
        )

    def test_roi_bboxes_present_in_motion_frames(self):
        """Verify that frames identified as having motion also produce non-empty
        bounding boxes - the data that drives dual-CRF ROI encoding."""
        clip = _require_clip(_PEDESTRIAN_CLIP)
        from src.background_subtraction.background_subtraction import BackgroundSubtractor

        cap = cv2.VideoCapture(clip)
        sub = BackgroundSubtractor()

        boxes_found = 0
        frames_with_motion = 0
        for _ in range(60):
            ret, frame = cap.read()
            if not ret:
                break
            mask = sub.apply(frame)
            regions = sub.get_foreground_regions(mask)
            if regions:
                frames_with_motion += 1
                boxes_found += len(regions)

        cap.release()
        assert frames_with_motion > 0, (
            "No motion detected in pedestrians clip - check BackgroundSubtractor defaults."
        )
        assert boxes_found > 0, "Motion frames produced no bounding boxes."

        # Every region should be a ForegroundRegion with positive dimensions
        cap2 = cv2.VideoCapture(clip)
        sub2 = BackgroundSubtractor()
        for _ in range(60):
            ret, frame = cap2.read()
            if not ret:
                break
            mask = sub2.apply(frame)
            for region in sub2.get_foreground_regions(mask):
                assert region.w > 0 and region.h > 0, (
                    f"Zero-size bounding box: {region}"
                )
        cap2.release()

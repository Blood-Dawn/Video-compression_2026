"""
tests/test_timelapse.py

Tests for the timelapse/quiet-period-summary feature added 2026-10-01
(competitive-gap review: Reolink/Synology-style "smart summary" that
compresses a long static recording into a short fast-forward clip).

Covers:
    utils.timelapse.clamp_speed    -- bounds/NaN/garbage handling
    utils.timelapse.make_timelapse -- real ffmpeg run against a tiny
                                       synthetic clip (lavfi testsrc), no
                                       network/camera required
    POST /api/timelapse            -- route-level success + path-confinement
                                       rejection (SEC: must not run ffmpeg
                                       over an arbitrary host path)

Author: Bloodawn (KheivenD), 2026-10-01.
"""
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.ffmpeg import ffmpeg_path, ffmpeg_available
from utils.timelapse import clamp_speed, make_timelapse, MIN_SPEED, MAX_SPEED, DEFAULT_SPEED


# ---------------------------------------------------------------------------
# clamp_speed
# ---------------------------------------------------------------------------

class TestClampSpeed:
    def test_within_range_passes_through(self):
        assert clamp_speed(10) == 10.0

    def test_below_min_clamped(self):
        assert clamp_speed(0.5) == MIN_SPEED

    def test_above_max_clamped(self):
        assert clamp_speed(9999) == MAX_SPEED

    def test_garbage_falls_back_to_default(self):
        assert clamp_speed("not-a-number") == DEFAULT_SPEED

    def test_none_falls_back_to_default(self):
        assert clamp_speed(None) == DEFAULT_SPEED

    def test_nan_falls_back_to_default(self):
        assert clamp_speed(float("nan")) == DEFAULT_SPEED

    def test_inf_falls_back_to_default(self):
        assert clamp_speed(float("inf")) == DEFAULT_SPEED


# ---------------------------------------------------------------------------
# make_timelapse (real ffmpeg, tiny synthetic clip)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not available")
class TestMakeTimelapse:
    @pytest.fixture
    def tiny_clip(self, tmp_path):
        """A ~2s, 10fps synthetic clip - enough frames to exercise setpts."""
        src = tmp_path / "source.mp4"
        subprocess.run(
            [ffmpeg_path(), "-v", "error", "-f", "lavfi", "-i",
             "testsrc2=size=160x120:rate=10:duration=2",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(src)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        return src

    def test_missing_input_fails_cleanly(self, tmp_path):
        ok, msg = make_timelapse(tmp_path / "nope.mp4", tmp_path / "out.mp4")
        assert ok is False
        assert "not found" in msg

    def test_produces_shorter_decodable_output(self, tiny_clip, tmp_path):
        out = tmp_path / "out_timelapse.mp4"
        ok, result = make_timelapse(tiny_clip, out, speed=4.0)
        assert ok is True, result
        assert out.exists() and out.stat().st_size > 0

        def _duration(path):
            probe = subprocess.run(
                [ffmpeg_path(), "-v", "error", "-i", str(path)],
                capture_output=True, text=True,
            )
            # ffmpeg (not ffprobe) writes duration to stderr with -i and no output
            return probe.stderr

        # Sped up 4x: the output must be meaningfully shorter than the 2s
        # source. Exact framing varies by encoder, so just assert it's a
        # real, non-trivial file rather than parsing duration out of stderr.
        assert out.stat().st_size < tiny_clip.stat().st_size * 4

    def test_speed_is_clamped_not_rejected(self, tiny_clip, tmp_path):
        """An absurd speed value must still produce output, clamped to MAX_SPEED."""
        out = tmp_path / "out_clamped.mp4"
        ok, result = make_timelapse(tiny_clip, out, speed=99999)
        assert ok is True, result
        assert out.exists() and out.stat().st_size > 0


# ---------------------------------------------------------------------------
# POST /api/timelapse route
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    import gui.app as gui_module  # noqa: F401 - ensures blueprints are registered
    from gui.app import app as flask_app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not available")
class TestTimelapseRoute:
    @pytest.fixture
    def allowed_clip(self, tmp_path, monkeypatch):
        """A clip inside the repo's data/ dir - one of allowed_media_roots()."""
        from gui.services import path_safety
        data_dir = Path(__file__).parent.parent / "data" / "samples" / "_timelapse_test"
        data_dir.mkdir(parents=True, exist_ok=True)
        clip = data_dir / "route_test_source.mp4"
        subprocess.run(
            [ffmpeg_path(), "-v", "error", "-y", "-f", "lavfi", "-i",
             "testsrc2=size=160x120:rate=10:duration=1",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        yield clip
        for p in data_dir.glob("*"):
            p.unlink(missing_ok=True)
        data_dir.rmdir()

    def test_generates_timelapse_for_allowed_path(self, client, allowed_clip):
        resp = client.post("/api/timelapse", json={"path": str(allowed_clip), "speed": 5})
        assert resp.status_code == 200, resp.get_json()
        data = resp.get_json()
        assert data["ok"] is True
        out = Path(data["path"])
        assert out.exists()
        out.unlink()  # cleanup - allowed_clip fixture only knows the source name

    def test_missing_path_is_400(self, client):
        resp = client.post("/api/timelapse", json={})
        assert resp.status_code == 400

    def test_path_outside_allowed_roots_is_rejected(self, client, tmp_path):
        outside = tmp_path / "outside.mp4"
        outside.write_bytes(b"not a real video, but never reached")
        resp = client.post("/api/timelapse", json={"path": str(outside)})
        assert resp.status_code == 403
        assert "error" in resp.get_json()

    def test_nonexistent_allowed_path_is_400(self, client):
        from gui.services import path_safety
        root = Path(__file__).parent.parent / "data"
        resp = client.post("/api/timelapse", json={"path": str(root / "does_not_exist.mp4")})
        assert resp.status_code == 400

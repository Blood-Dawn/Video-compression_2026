"""
tests/test_encoder_r4.py

R4 Phase 2 (docs/RESEARCH-COMPRESSION.md): encoder upgrades.

Most tests assert the exact FFmpeg output arguments / filter chains that
ROIEncoder builds, with NO real encode (fast, deterministic, cross-platform):
  * long GOP default (finding 2), capped CRF (finding 3),
  * NVENC codec mapping + CRF translation (finding 4),
  * denoise filter chain (finding 5),
  * encoder-level addroi ROI gated to x264/x265 and to >=2 observed segments,
    with the activity grid learning motion cells (finding 1),
  * unknown-codec fallback to libx264.
A couple of guarded real-encode smokes run only when the capability is present
(NVENC on this GPU, libvmaf in the bundled ffmpeg).

Author: Bloodawn (KheivenD), 2026-07-04 (R4 Phase 2 - encoder).
"""

import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compression.roi_encoder import ROIEncoder, _ffmpeg_has_encoder  # noqa: E402
from utils import metrics  # noqa: E402
from utils.ffmpeg import ffmpeg_path, ffprobe_path  # noqa: E402


def _enc(tmp_path, **kw):
    return ROIEncoder(output_dir=str(tmp_path / "out"),
                      db_path=str(tmp_path / "meta.db"), **kw)


# ── long GOP (finding 2) ──────────────────────────────────────────────────────

def test_long_gop_default_x264(tmp_path):
    kw = _enc(tmp_path, codec="libx264").build_kwargs_at(25.0)
    assert kw["g"] == 500          # 20s * 25fps
    assert kw["vcodec"] == "libx264"


def test_gop_seconds_zero_omits_g(tmp_path):
    kw = _enc(tmp_path, codec="libx264", gop_seconds=0).build_kwargs_at(30.0)
    assert "g" not in kw


def test_long_gop_svtav1_uses_keyint_param(tmp_path):
    e = _enc(tmp_path, codec="libsvtav1")
    if e.codec != "libsvtav1":
        pytest.skip("libsvtav1 not in this ffmpeg build")
    kw = e.build_kwargs_at(30.0)
    assert "keyint=600" in kw["svtav1-params"]


# ── capped CRF (finding 3) ────────────────────────────────────────────────────

def test_capped_crf_x264_sets_vbv(tmp_path):
    kw = _enc(tmp_path, codec="libx264", max_bitrate_kbps=4000).build_kwargs_at(30.0)
    assert kw["maxrate"] == "4000k"
    assert kw["bufsize"] == "8000k"


def test_capped_crf_svtav1_uses_mbr(tmp_path):
    e = _enc(tmp_path, codec="libsvtav1", max_bitrate_kbps=3000)
    if e.codec != "libsvtav1":
        pytest.skip("libsvtav1 not in this ffmpeg build")
    kw = e.build_kwargs_at(30.0)
    assert "mbr=3000" in kw["svtav1-params"]


def test_uncapped_by_default(tmp_path):
    kw = _enc(tmp_path, codec="libx264").build_kwargs_at(30.0)
    assert "maxrate" not in kw and "bufsize" not in kw


# ── NVENC (finding 4) ─────────────────────────────────────────────────────────

def test_nvenc_arg_shape_and_crf_translation(tmp_path):
    # av1_nvenc CQ uses the AV1 0-63 scale, so fg 18 -> 23 like software AV1.
    e = _enc(tmp_path, codec="av1_nvenc", foreground_crf=18, background_crf=40,
             preset="ultrafast")
    if e.codec != "av1_nvenc":
        pytest.skip("av1_nvenc not in this ffmpeg build")
    kw = e.build_kwargs_at(30.0)
    assert kw["vcodec"] == "av1_nvenc"
    assert kw["rc"] == "vbr" and kw["b:v"] == "0"
    assert kw["cq"] == 23                 # 18 + 5 AV1 translation
    assert kw["preset"] == "p1"           # ultrafast -> p1
    assert e.foreground_crf == 23 and e.background_crf == 45


def test_h264_nvenc_no_crf_translation(tmp_path):
    e = _enc(tmp_path, codec="h264_nvenc", foreground_crf=18)
    if e.codec != "h264_nvenc":
        pytest.skip("h264_nvenc not in this ffmpeg build")
    assert e.foreground_crf == 18          # H.264 scale, no +5
    assert e.build_kwargs_at(30.0)["cq"] == 18


# ── denoise (finding 5) ───────────────────────────────────────────────────────

def test_denoise_in_vf(tmp_path):
    e = _enc(tmp_path, codec="libx264", denoise="hqdn3d")
    assert e._build_vf(640, 360) == "hqdn3d"


def test_bad_denoise_disabled(tmp_path):
    e = _enc(tmp_path, codec="libx264", denoise="rm -rf")
    assert e.denoise == ""
    assert e._build_vf(640, 360) is None


# ── encoder-level ROI (finding 1) ─────────────────────────────────────────────

def test_roi_off_by_default(tmp_path):
    e = _enc(tmp_path, codec="libx264")
    e._roi_segments_seen = 5
    e._activity_grid[:] = 0.0
    assert e._build_roi_filters(640, 360) == []


def test_roi_needs_two_observed_segments(tmp_path):
    e = _enc(tmp_path, codec="libx264", roi_qp=True)
    e._activity_grid[0, 0] = 3.0          # some activity observed
    e._roi_segments_seen = 1
    assert e._build_roi_filters(640, 360) == []


def test_roi_degrades_static_cells_only(tmp_path):
    e = _enc(tmp_path, codec="libx264", roi_qp=True,
             foreground_crf=18, background_crf=40)
    # Motion only in the center column of the grid; everything else static.
    e._activity_grid[:] = 0.0
    e._activity_grid[:, 8] = 5.0
    e._roi_segments_seen = 3
    filters = e._build_roi_filters(1600, 900)
    assert filters, "static cells should produce addroi filters"
    assert all(f.startswith("addroi=") and "qoffset=" in f for f in filters)
    # The active column (x around 800) is never the start of a degraded run.
    assert not any("x=800:" in f for f in filters)


def test_roi_not_emitted_for_av1(tmp_path):
    # addroi side data is not consumed by libsvtav1/libaom (verified).
    e = _enc(tmp_path, codec="libsvtav1", roi_qp=True)
    if e.codec != "libsvtav1":
        pytest.skip("libsvtav1 not in this ffmpeg build")
    e._activity_grid[:] = 0.0
    e._roi_segments_seen = 5
    assert e._build_roi_filters(640, 360) == []


def test_activity_grid_learns_motion_cells(tmp_path):
    e = _enc(tmp_path, codec="libx264", roi_qp=True)
    e._activity_grid[:] = 0.0
    # A box in the top-left quadrant of a 1600x900 frame.
    e._note_roi_activity([(0, 0, 200, 100)], 1600, 900)
    assert e._activity_grid[0, 0] > 0.0
    assert e._activity_grid[8, 15] == 0.0   # bottom-right untouched


def test_grid_ages_on_segment_open(tmp_path):
    e = _enc(tmp_path, codec="libx264", roi_qp=True)
    e._activity_grid[0, 0] = 4.0
    e._on_segment_opened()
    assert e._activity_grid[0, 0] == 2.0    # halved (decay)
    assert e._roi_segments_seen == 1


# ── fallback ──────────────────────────────────────────────────────────────────

def test_unknown_codec_falls_back(tmp_path):
    assert _enc(tmp_path, codec="h265_pied_piper").codec == "libx264"


# ── guarded real-encode smokes ────────────────────────────────────────────────

def _write_frames(e, n=8, shape=(180, 320, 3)):
    e.begin_segment(shape, fps=10.0, camera_id="cam_smoke", has_targets=False)
    for i in range(n):
        f = np.full(shape, i * 10 % 255, dtype=np.uint8)
        e.write_frame(f)
    return e.finish_segment()


def test_real_encode_denoise_x264(tmp_path):
    e = _enc(tmp_path, codec="libx264", denoise="hqdn3d", gop_seconds=1)
    out = _write_frames(e)
    p = Path(out["file_path"])
    assert p.is_file() and p.stat().st_size > 0


@pytest.mark.skipif(not _ffmpeg_has_encoder("h264_nvenc"),
                    reason="h264_nvenc not available on this machine")
def test_real_encode_nvenc(tmp_path):
    e = _enc(tmp_path, codec="h264_nvenc")
    out = _write_frames(e)
    p = Path(out["file_path"])
    assert p.is_file() and p.stat().st_size > 0
    # ffprobe: the stream really is h264.
    proc = subprocess.run(
        [ffprobe_path(), "-v", "error",
         "-select_streams", "v:0", "-show_entries", "stream=codec_name",
         "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, timeout=30)
    assert "h264" in (proc.stdout or "")


def _has_libvmaf():
    try:
        out = subprocess.check_output(
            [ffmpeg_path(), "-hide_banner", "-filters"],
            stderr=subprocess.DEVNULL, timeout=5).decode(errors="replace")
        return "libvmaf" in out
    except Exception:
        return False


@pytest.mark.skipif(not _has_libvmaf(), reason="libvmaf not in this ffmpeg build")
def test_compute_vmaf_scores(tmp_path):
    ff = ffmpeg_path()
    ref = tmp_path / "ref.mp4"
    dist = tmp_path / "dist.mp4"
    for path, crf in ((ref, "10"), (dist, "34")):
        subprocess.run(
            [ff, "-hide_banner", "-f", "lavfi", "-i",
             "testsrc2=duration=0.6:size=320x180:rate=10",
             "-c:v", "libx264", "-crf", crf, "-y", str(path)],
            capture_output=True, timeout=60)
    score = metrics.compute_vmaf(str(ref), str(dist))
    assert score is not None
    assert 0.0 <= score <= 100.0


def test_compute_vmaf_missing_file_returns_none(tmp_path):
    assert metrics.compute_vmaf(str(tmp_path / "nope.mp4"),
                                str(tmp_path / "nope2.mp4")) is None

"""
tests/test_static_scene.py

R5 TASK 5.2: static-scene measurement for fixed cameras.

TASK 5.2 set out to add a "background reference" mode that, once the camera
measured static, quantized background regions much harder than the R4 ROI does.
That half of the task was built, measured, and REMOVED: the size/VMAF data
refutes it (see docs/BLOCKERS.md, and the saturation test at the bottom of this
file, which pins the measurement so nobody re-adds the knob by intuition).

What survives, and what this file covers, is the piece that is real and that
TASK 5.3 needs: measuring whether the camera is ACTUALLY static, derived from
the foreground signal the pipeline already produces (no second detector, per
5.3's "do not double-count motion" risk note).

Covered here:
  * the static score and its gate: localized motion is static; whole-frame
    motion (shake / exposure hunting) is not; a cold start is never static;
  * the score recovers when a shaky camera settles;
  * R4 ROI parity: measuring staticity changed no encoder output;
  * foreground cells are never degraded (the subject keeps its quality);
  * the RD saturation that killed the harder-QP idea, as a real encode.

Author: Bloodawn (KheivenD), 2026-07-16 (R5 TASK 5.2).
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compression.roi_encoder import (             # noqa: E402
    ROIEncoder,
    _STATIC_SCENE_MAX_ACTIVE_FRAC, _STATIC_SCENE_MIN_FRAMES,
    _ROI_GRID_W, _ROI_GRID_H,
)
from utils.ffmpeg import ffmpeg_available, ffmpeg_path   # noqa: E402
from utils.metrics import compute_vmaf                   # noqa: E402


def _enc(tmp_path, **kw):
    return ROIEncoder(output_dir=str(tmp_path / "out"),
                      db_path=str(tmp_path / "meta.db"), **kw)


def _feed(enc, boxes, frames, w=1600, h=900):
    """Drive the activity/static signal for N frames with the given boxes."""
    for _ in range(frames):
        enc._note_roi_activity(boxes, w, h)


# ── the static score and its gate ─────────────────────────────────────────────

def test_cold_start_is_never_static(tmp_path):
    """Before enough evidence the scene is NOT trusted as static, so a caller
    can never act on one lucky empty frame."""
    e = _enc(tmp_path, codec="libx264", roi_qp=True)
    assert not e.scene_is_static()
    _feed(e, [], _STATIC_SCENE_MIN_FRAMES - 1)       # still short of the floor
    assert not e.scene_is_static()


def test_localized_motion_scores_static(tmp_path):
    """A fixed camera with a walker lights a handful of 144 cells: static."""
    e = _enc(tmp_path, codec="libx264", roi_qp=True)
    _feed(e, [(100, 100, 120, 200)], 200)            # one small box
    assert e.background_motion_score < _STATIC_SCENE_MAX_ACTIVE_FRAC
    assert e.scene_is_static()


def test_empty_frames_score_static(tmp_path):
    e = _enc(tmp_path, codec="libx264", roi_qp=True)
    _feed(e, [], 200)                                # nothing moving at all
    assert e.background_motion_score == pytest.approx(0.0, abs=0.05)
    assert e.scene_is_static()


def test_whole_frame_motion_is_not_static(tmp_path):
    """Camera shake / auto-exposure lights the whole grid, so the static
    assumption must fail."""
    e = _enc(tmp_path, codec="libx264", roi_qp=True)
    _feed(e, [(0, 0, 1600, 900)], 200)               # foreground everywhere
    assert e.background_motion_score > _STATIC_SCENE_MAX_ACTIVE_FRAC
    assert not e.scene_is_static()


def test_score_recovers_when_shake_stops(tmp_path):
    """The score is an EMA, so a camera that settles becomes static again."""
    e = _enc(tmp_path, codec="libx264", roi_qp=True)
    _feed(e, [(0, 0, 1600, 900)], 100)
    assert not e.scene_is_static()
    _feed(e, [], 300)                                # settles
    assert e.scene_is_static()


def test_score_is_tracked_without_roi_qp(tmp_path):
    """The signal is a measurement, not an ROI feature: TASK 5.3 consumes it on
    codecs that have no addroi support at all."""
    e = _enc(tmp_path, codec="libsvtav1", roi_qp=False)
    _feed(e, [], 200)
    assert e.scene_is_static()


# ── R4 ROI parity ─────────────────────────────────────────────────────────────

def test_measuring_staticity_did_not_change_the_r4_qoffset(tmp_path):
    """Whatever the scene measures, the encoder output is the R4 formula. 5.2
    deliberately ships no QP change; this pins that."""
    static = _enc(tmp_path, codec="libx264", roi_qp=True,
                  foreground_crf=18, background_crf=40)
    shaky = _enc(tmp_path, codec="libx264", roi_qp=True,
                 foreground_crf=18, background_crf=40)
    _feed(static, [], 200)
    _feed(shaky, [(0, 0, 1600, 900)], 200)
    expected = max(0.05, min(0.6, (40 - 18) / 51.0))
    assert static._background_qoffset() == pytest.approx(expected)
    assert shaky._background_qoffset() == pytest.approx(expected)


def test_background_qoffset_cap_stays_at_the_measured_knee(tmp_path):
    """Regression guard. R5 TASK 5.2 tried raising this cap to 0.80 and the
    measurements refuted it: size is flat above ~0.30 while VMAF collapses
    (docs/BLOCKERS.md). Raising it again needs NEW measurement, not intuition.
    """
    e = _enc(tmp_path, codec="libx264", roi_qp=True,
             foreground_crf=0, background_crf=51)     # ask for the extreme
    assert e._background_qoffset() == pytest.approx(0.6)


# ── the subject keeps its quality ─────────────────────────────────────────────

def test_active_cells_are_never_in_the_degraded_set(tmp_path):
    """No addroi rect may cover a cell with recent foreground activity."""
    e = _enc(tmp_path, codec="libx264", roi_qp=True,
             foreground_crf=18, background_crf=40)
    e._roi_segments_seen = 3
    e._activity_grid[:] = 0.0
    e._activity_grid[4, 8] = 5.0                     # the subject lives here
    _feed(e, [], _STATIC_SCENE_MIN_FRAMES + 5)
    filters = e._build_roi_filters(1600, 900)
    assert filters, "a static background should still produce addroi rects"
    cx = (8 + 0.5) * 1600 / _ROI_GRID_W
    cy = (4 + 0.5) * 900 / _ROI_GRID_H
    for f in filters:
        m = re.match(r"addroi=x=(\d+):y=(\d+):w=(\d+):h=(\d+)", f)
        assert m
        x, y, w, h = map(int, m.groups())
        covered = (x <= cx <= x + w) and (y <= cy <= y + h)
        assert not covered, f"degrade rect {f} covers the ACTIVE (subject) cell"


# ── the measurement that killed the harder-QP idea ────────────────────────────

def _noisy_static_clip(path: Path, ffmpeg: str) -> bool:
    """A realistic static camera: one fixed TEXTURED frame plus per-frame sensor
    noise, with a small box sliding across it.

    Both properties matter. Without texture and noise the background costs ~0
    bits at any quantizer, so a QP sweep would measure nothing but encoder jitter
    and the test would prove the wrong thing.
    """
    bg = path.parent / "_bg_still.png"
    r = subprocess.run(
        [ffmpeg, "-v", "error", "-f", "lavfi", "-i", "testsrc=s=640x360:r=1:d=1",
         "-frames:v", "1", str(bg), "-y"], capture_output=True, timeout=120)
    if r.returncode != 0 or not bg.is_file():
        return False
    r = subprocess.run(
        [ffmpeg, "-v", "error",
         "-loop", "1", "-t", "4", "-r", "15", "-i", str(bg),
         "-f", "lavfi", "-i", "color=c=white:s=48x48:r=15:d=4",
         "-filter_complex",
         "[0:v]noise=alls=12:allf=t+u[n];[n][1:v]overlay=x=40*t:y=150",
         "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p",
         str(path), "-y"], capture_output=True, timeout=180)
    return r.returncode == 0 and path.is_file() and path.stat().st_size > 0


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not available")
def test_background_qp_beyond_the_cap_buys_no_bytes(tmp_path):
    """The evidence behind dropping 5.2's harder-QP mode, kept executable.

    Pushing background qoffset past the R4 cap costs real VMAF and returns
    essentially no bytes. If a future encoder or codec ever changes that, this
    test fails and the mode is worth revisiting with fresh numbers.
    """
    src = tmp_path / "noisy_static.mp4"
    if not _noisy_static_clip(src, ffmpeg_path()):
        pytest.skip("could not synthesize the noisy static test clip")

    rows = [y for y in range(0, 360, 40) if not (120 <= y < 200)]

    def encode(qoffset: float):
        out = tmp_path / f"q{qoffset}.mp4"
        vf = ",".join(f"addroi=x=0:y={y}:w=640:h=40:qoffset={qoffset}" for y in rows)
        subprocess.run(
            [ffmpeg_path(), "-v", "error", "-i", str(src), "-vf", vf,
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
             "-g", "30", "-pix_fmt", "yuv420p", str(out), "-y"],
            capture_output=True, timeout=300)
        assert out.is_file() and out.stat().st_size > 0
        return out.stat().st_size, compute_vmaf(str(src), str(out))

    size_at_cap, vmaf_at_cap = encode(0.60)          # the R4 cap
    size_beyond, vmaf_beyond = encode(0.80)          # what 5.2 proposed

    # Essentially no bytes are returned past the cap (well under a tenth of the
    # file), which is why the knob is not worth its quality cost.
    saved_frac = (size_at_cap - size_beyond) / size_at_cap
    assert saved_frac < 0.10, (
        f"pushing qoffset 0.60 -> 0.80 saved {saved_frac:.1%}; the R5 TASK 5.2 "
        f"harder-QP mode was dropped because this was ~0. Re-read "
        f"docs/BLOCKERS.md and re-measure before acting on this.")

    if vmaf_at_cap is not None and vmaf_beyond is not None:
        # ...and it is paid for in visible quality.
        assert vmaf_beyond < vmaf_at_cap, (
            "expected quality to degrade past the cap; if it did not, the "
            "saturation measurement in docs/BLOCKERS.md needs revisiting")

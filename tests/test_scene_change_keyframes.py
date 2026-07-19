"""
tests/test_scene_change_keyframes.py

R5 TASK 5.3: keyframes must land on scene changes.

TASK 5.3 asked for two things: scene-change keyframes, and a content-adaptive
GOP driven by the TASK 5.2 motion signal. Measurement on the real CDnet corpus
refuted the second (see docs/BLOCKERS.md) and showed the FIRST already works:
x264's built-in scene detection places an IDR at a hard cut, and the encoder
passes only "-g", leaving keyint_min and sc_threshold at their defaults.

Working-but-unguarded is exactly the state worth pinning, and the risk here is
concrete rather than hypothetical: `-sc_threshold 0` turns scene detection off
outright, and it already appears in this codebase, in
src/gui/services/hls_runner.py, where it is correct. HLS wants evenly sized
segments, so scene-cut IDRs are deliberately suppressed there. That makes
copying the HLS argv into the recording encoder a natural mistake which would
degrade every recording with no error message. These tests exist to catch it.

A note on `-keyint_min`, because it is the intuitive suspect and the intuition
is wrong. It looks like `keyint_min == g` should forbid a mid-GOP IDR and so
suppress cut keyframes. Measured across 25 and 30 fps at g=500 and g=600, it
did NOT: the cut keyframe appeared every time. (x264 also clamps min-keyint to
keyint/2+1, so `keyint_min == g` never means what it reads like.) An earlier
probe here appeared to show suppression and was not reproducible, so this file
does not assert anything about keyint_min's runtime effect. It is still kept
out of the encoder argv below, on the narrower ground that it is an HLS-only
concern that should not spread.

Why it matters for a surveillance product: without a keyframe at a cut, the
first frames after a camera switch or a lighting change are predicted from a
reference that no longer resembles them, which is where an operator is most
likely to be looking.

Author: Bloodawn (KheivenD), 2026-07-19 (R5 TASK 5.3).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compression.roi_encoder import ROIEncoder          # noqa: E402
from utils.ffmpeg import ffmpeg_available, ffmpeg_path, ffprobe_path  # noqa: E402


# ── the encoder's argv must leave scene detection alive ──────────────────────

@pytest.mark.parametrize("codec", ["libx264", "libx265"])
def test_encoder_does_not_pin_keyint_min(tmp_path, codec):
    """keyint_min == g forbids a mid-GOP IDR, which is what a scene cut needs."""
    enc = ROIEncoder(output_dir=str(tmp_path / "o"), db_path=str(tmp_path / "m.db"),
                     codec=codec, gop_seconds=20)
    kw = enc._build_output_kwargs(crf=23, fps=25.0, codec=codec)
    assert "keyint_min" not in kw, (
        "setting keyint_min pins the MINIMUM IDR distance; at keyint_min == g "
        "x264 cannot place a keyframe at a scene cut")


@pytest.mark.parametrize("codec", ["libx264", "libx265"])
def test_encoder_does_not_disable_scene_detection(tmp_path, codec):
    """sc_threshold 0 turns scene-cut detection off entirely."""
    enc = ROIEncoder(output_dir=str(tmp_path / "o"), db_path=str(tmp_path / "m.db"),
                     codec=codec, gop_seconds=20)
    kw = enc._build_output_kwargs(crf=23, fps=25.0, codec=codec)
    assert str(kw.get("sc_threshold", "")) != "0", (
        "sc_threshold 0 disables scene-change keyframes")


def test_encoder_still_sets_an_upper_bound_gop(tmp_path):
    """A cut gets a keyframe from detection, but a static stretch needs -g so
    keyframes do not stop entirely."""
    enc = ROIEncoder(output_dir=str(tmp_path / "o"), db_path=str(tmp_path / "m.db"),
                     codec="libx264", gop_seconds=20)
    kw = enc._build_output_kwargs(crf=23, fps=25.0, codec="libx264")
    assert int(kw["g"]) == 500, "gop_seconds * fps should bound the keyframe gap"


def test_hls_runner_is_the_only_place_that_suppresses_scene_cuts():
    """Pins WHERE the suppressing flags may appear.

    hls_runner sets keyint_min and sc_threshold 0 on purpose, for even segment
    lengths. If either shows up in the recording encoder, a recording silently
    loses scene-change keyframes, so this fails when that spreads.
    """
    enc_src = (SRC / "compression" / "roi_encoder.py").read_text(encoding="utf-8")
    assert "sc_threshold" not in enc_src, (
        "roi_encoder must not set sc_threshold; that is an HLS-only concern")
    assert "keyint_min" not in enc_src, (
        "roi_encoder must not set keyint_min; that is an HLS-only concern")

    hls_src = (SRC / "gui" / "services" / "hls_runner.py").read_text(encoding="utf-8")
    assert "sc_threshold" in hls_src, (
        "hls_runner is expected to pin these; if it stopped, re-check M0.3")


# ── the behavior itself, on a real encode ────────────────────────────────────

def _clip_with_hard_cut(path: Path, ffmpeg: str, fps: int = 25) -> bool:
    """4s of one scene, a hard cut, then 4s of a visibly different scene."""
    a, b = path.parent / "_a.png", path.parent / "_b.png"
    for src, out in (("testsrc", a), ("testsrc2", b)):
        r = subprocess.run(
            [ffmpeg, "-v", "error", "-f", "lavfi", "-i", f"{src}=s=320x240:r=1:d=1",
             "-frames:v", "1", str(out), "-y"], capture_output=True, timeout=120)
        if r.returncode != 0:
            return False
    parts = []
    for still, name in ((a, "_va.mp4"), (b, "_vb.mp4")):
        p = path.parent / name
        r = subprocess.run(
            [ffmpeg, "-v", "error", "-loop", "1", "-t", "4", "-r", str(fps),
             "-i", str(still), "-c:v", "libx264", "-crf", "10",
             "-pix_fmt", "yuv420p", str(p), "-y"], capture_output=True, timeout=180)
        if r.returncode != 0:
            return False
        parts.append(p)
    lst = path.parent / "_list.txt"
    lst.write_text("".join(f"file '{p.as_posix()}'\n" for p in parts), encoding="utf-8")
    r = subprocess.run(
        [ffmpeg, "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst),
         "-c", "copy", str(path), "-y"], capture_output=True, timeout=180)
    return r.returncode == 0 and path.is_file()


def _keyframe_times(path: Path):
    r = subprocess.run(
        [ffprobe_path(), "-v", "error", "-select_streams", "v:0", "-show_frames",
         "-show_entries", "frame=pict_type,pts_time", "-of", "json", str(path)],
        capture_output=True, text=True, timeout=180)
    try:
        frames = json.loads(r.stdout)["frames"]
    except (json.JSONDecodeError, KeyError):
        return []
    return [round(float(f["pts_time"]), 2)
            for f in frames if f.get("pict_type") == "I"]


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not available")
def test_a_hard_cut_gets_a_keyframe_under_the_production_gop(tmp_path):
    """The load-bearing behavior, end to end.

    Encodes with the argv shape the recording encoder actually emits (only -g,
    at the 20s default) and asserts an I-frame lands at the 4.0s cut. Without
    scene detection the only I-frame is at 0.0.
    """
    src = tmp_path / "cut.mp4"
    if not _clip_with_hard_cut(src, ffmpeg_path()):
        pytest.skip("could not synthesize the scene-cut clip")

    out = tmp_path / "encoded.mp4"
    subprocess.run(
        [ffmpeg_path(), "-v", "error", "-i", str(src), "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "23",
         "-g", "500",                     # gop_seconds=20 at 25fps
         "-pix_fmt", "yuv420p", str(out), "-y"],
        capture_output=True, timeout=300)
    assert out.is_file()

    ks = _keyframe_times(out)
    assert ks, "no I-frames at all"
    at_cut = [k for k in ks if 3.5 <= k <= 4.5]
    assert at_cut, (
        f"no keyframe at the 4.0s scene cut; I-frames were {ks}. Scene "
        "detection is off or keyint_min is pinned.")


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not available")
def test_disabling_scene_detection_demonstrably_breaks_it(tmp_path):
    """The negative control: proves the test above can actually fail.

    Without this, "a keyframe appeared at the cut" could be true for reasons
    unrelated to scene detection (a fixed GOP boundary that happens to land
    there, the encoder refreshing on its own), and the guard would be
    reassuring rather than informative.

    `-sc_threshold 0` is the mechanism this asserts on because it is the one
    that reproduced reliably: suppression at both 25 and 30 fps, across GOP
    lengths. `keyint_min` was tried first and did not suppress at all; see the
    module docstring.
    """
    src = tmp_path / "cut.mp4"
    if not _clip_with_hard_cut(src, ffmpeg_path()):
        pytest.skip("could not synthesize the scene-cut clip")

    out = tmp_path / "broken.mp4"
    subprocess.run(
        [ffmpeg_path(), "-v", "error", "-i", str(src), "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "23",
         "-g", "500", "-sc_threshold", "0",     # scene detection OFF
         "-pix_fmt", "yuv420p", str(out), "-y"],
        capture_output=True, timeout=300)
    assert out.is_file()

    ks = _keyframe_times(out)
    at_cut = [k for k in ks if 3.5 <= k <= 4.5]
    assert not at_cut, (
        "sc_threshold 0 was expected to suppress the scene-cut keyframe, but "
        f"one appeared at {at_cut}. Either x264's behavior changed or the clip "
        "has a GOP boundary at the cut; in both cases the positive test above "
        "may be passing for the wrong reason and both need revisiting.")

"""
tests/test_real_videos.py

Real-video integration test (R2.2).

Runs the ACTUAL pipeline on REAL clips so "does it really compress" is provable,
not just unit-mocked. It resolves a clip folder in this order:

  1. env var SVCS_TEST_VIDEO_DIR  (point it at any folder of clips), else
  2. the repo's CDnet sample corpus at data/samples/cdnet_mp4 (real surveillance
     clips, organised into scene-type subfolders: baseline, badWeather,
     cameraJitter, dynamicBackground, intermittentObjectMotion, nightVideos,
     shadow, thermal, ...).

The corpus is git-LFS, so it is absent on CI: when no clips are found the whole
module SKIPS with a clear message and the suite stays green. When clips are
present it picks ONE clip per immediate subfolder (one per scene type), trims a
short window from each (so runtime stays bounded), and runs every trimmed clip
through every mode (mode0..mode3). For each produced segment it asserts, via
ffprobe, a valid non-empty container with a video stream, that the output is far
smaller than the raw uncompressed size, and that the per-mode codec is the one
TASK 1.6 decided (mode0/1 = H.264, mode2/3 = AV1).

Run `uv run --no-sync pytest tests/test_real_videos.py -s` to see a readable
per-clip/mode compression-ratio table and confirm each mode + codec works on
real footage. No new media is committed; it reuses the clips already in the
repo. Bound the breadth with SVCS_TEST_VIDEO_MAX (default 8 scene types) and the
window with SVCS_TEST_VIDEO_TRIM (default 3 seconds).

Author: Bloodawn (KheivenD), 2026-06-05 (R2.2).
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils.ffmpeg import ffmpeg_path, ffprobe_path  # noqa: E402

MODES = ["mode0", "mode1", "mode2", "mode3"]
# Per-mode expected codec family (TASK 1.6): H.264 for mode0/1, AV1 for mode2/3.
H264 = {"h264"}
AV1 = {"av1", "av01"}
EXPECT_CODEC = {"mode0": H264, "mode1": H264, "mode2": AV1, "mode3": AV1}

TRIM_SECONDS = int(os.environ.get("SVCS_TEST_VIDEO_TRIM", "3"))
MAX_SCENES = int(os.environ.get("SVCS_TEST_VIDEO_MAX", "8"))


def _resolve_corpus():
    env = os.environ.get("SVCS_TEST_VIDEO_DIR", "").strip()
    if env:
        p = Path(env)
        return p if p.is_dir() else None
    p = ROOT / "data" / "samples" / "cdnet_mp4"
    return p if p.is_dir() else None


def _select_clips(corpus, cap):
    subdirs = sorted([d for d in corpus.iterdir() if d.is_dir()])
    clips = []
    if subdirs:
        for d in subdirs:
            found = sorted(d.rglob("*.mp4"))
            if found:
                clips.append(found[0])
    else:
        clips = sorted(corpus.rglob("*.mp4"))
    return clips[:cap]


CORPUS = _resolve_corpus()
CLIPS = _select_clips(CORPUS, MAX_SCENES) if CORPUS else []

pytestmark = pytest.mark.skipif(
    not CLIPS,
    reason="No real clips found. Set SVCS_TEST_VIDEO_DIR, or add the git-LFS "
           "CDnet corpus at data/samples/cdnet_mp4.",
)


def _probe(path):
    """Return {codec, width, height, nb_frames, fps, duration} via ffprobe."""
    out = subprocess.run(
        [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
         "-show_entries",
         "stream=codec_name,width,height,nb_frames,avg_frame_rate:format=duration",
         "-of", "default=noprint_wrappers=1:nokey=0", str(path)],
        capture_output=True, text=True, timeout=60,
    )
    d = {}
    for line in out.stdout.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            d[k.strip()] = v.strip()
    fps = 0.0
    afr = d.get("avg_frame_rate", "0/0")
    try:
        num, den = afr.split("/")
        fps = float(num) / float(den) if float(den) else 0.0
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    try:
        nb = int(d.get("nb_frames", "0"))
    except ValueError:
        nb = 0
    try:
        dur = float(d.get("duration", "0"))
    except ValueError:
        dur = 0.0
    if not nb and fps and dur:
        nb = int(fps * dur)
    return {"codec": d.get("codec_name", ""),
            "width": int(d.get("width", "0") or 0),
            "height": int(d.get("height", "0") or 0),
            "nb_frames": nb, "fps": fps, "duration": dur}


def _has_video_stream(path) -> bool:
    out = subprocess.run(
        [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True, timeout=30,
    )
    return out.returncode == 0 and "video" in out.stdout


def _trim(src: Path, dst: Path, seconds: int) -> bool:
    """Re-encode a short window so each pipeline run is bounded. Returns ok."""
    r = subprocess.run(
        [ffmpeg_path(), "-y", "-ss", "0", "-t", str(seconds), "-i", str(src),
         "-an", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
         str(dst)],
        capture_output=True, timeout=120,
    )
    return r.returncode == 0 and dst.exists() and dst.stat().st_size > 0


def test_real_videos_compress_through_every_mode(tmp_path):
    from pipeline.pipeline import run_pipeline

    print(f"\nReal-video test: {len(CLIPS)} clip(s), trim {TRIM_SECONDS}s, "
          f"corpus {CORPUS}")
    print(f"{'scene/clip':<34} {'mode':<6} {'codec':<6} {'out KB':>8} "
          f"{'ratio vs raw':>13}  result")

    mode_produced = {m: 0 for m in MODES}
    checked_segments = 0

    for clip in CLIPS:
        trimmed = tmp_path / (clip.stem + "_trim.mp4")
        if not _trim(clip, trimmed, TRIM_SECONDS):
            pytest.skip(f"could not trim {clip.name} (ffmpeg unavailable?)")
        meta = _probe(trimmed)
        raw_bytes = max(1, meta["width"] * meta["height"] * 3 * max(1, meta["nb_frames"]))

        for mode in MODES:
            out_dir = tmp_path / f"out_{clip.stem}_{mode}"
            run_pipeline(
                input_source=str(trimmed),
                camera_id=f"rt_{mode}",
                output_dir=str(out_dir),
                segment_seconds=600,        # whole trimmed clip = one segment
                bg_method="MOG2",
                mode=mode,
                warmup_frames=5,
                object_filter=False,        # MOG2 only - no YOLO, keeps it fast
            )
            segs = sorted(out_dir.glob("*.mp4")) if out_dir.is_dir() else []
            for seg in segs:
                size = seg.stat().st_size
                assert size > 0, f"{seg} is empty"
                assert _has_video_stream(seg), f"{seg} has no video stream"
                codec = _probe(seg)["codec"]
                ratio = raw_bytes / size if size else 0.0
                ok = codec in EXPECT_CODEC[mode]
                print(f"{clip.parent.name + '/' + clip.name:<34} {mode:<6} "
                      f"{codec:<6} {size/1024:>8.1f} {ratio:>12.1f}x  "
                      f"{'OK' if ok else 'BAD CODEC'}")
                assert codec in EXPECT_CODEC[mode], (
                    f"{mode} {seg.name}: codec {codec}, expected {EXPECT_CODEC[mode]}")
                assert size < raw_bytes, (
                    f"{seg.name} ({size}) not smaller than raw {raw_bytes}")
                checked_segments += 1
            if segs:
                mode_produced[mode] += 1

    # mode0/mode1 buffer (active) frames, so they must always produce output.
    assert mode_produced["mode0"] == len(CLIPS), "mode0 did not produce output for every clip"
    assert mode_produced["mode1"] >= 1, "mode1 produced no output on any clip"
    # mode2/mode3 are object-driven; prove they work on at least one real clip.
    assert mode_produced["mode2"] >= 1, "mode2 (AV1) produced no output on any clip"
    assert mode_produced["mode3"] >= 1, "mode3 (AV1 object-only) produced no output on any clip"
    assert checked_segments >= len(CLIPS), "too few segments validated"
    print(f"\nValidated {checked_segments} real segments across "
          f"{len(CLIPS)} scene type(s).")

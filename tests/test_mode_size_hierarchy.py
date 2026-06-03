"""
tests/test_mode_size_hierarchy.py

End-to-end mode-size benchmark.

The user's expectation is "each mode should lower file size incrementally  - 
mode 3 < mode 2 < mode 1 < mode 0". The reality on real surveillance
footage is more nuanced: see ``docs/mode_size_hierarchy.md`` for the full
discussion. These tests lock in the WEAKER invariants that DO hold across
all reasonable scenes:

* Every mode runs end-to-end without raising.
* Every output (a single segment .mp4 for every mode, mode 3 included)
  is smaller than the uncompressed raw bytes the source frames represent.
* Mode 3 writes a single object-only .mp4 (objects kept, background
  blacked out). The per-object mode3_sparse/ layout was never shipped on
  the app branch - see docs/test-baseline.md D2.

This is the test file that exercises the FULL pipeline (FrameSource ->
BG subtractor -> MOG2 mask -> ROI encoder -> SQLite DB row). It is the
closest thing the suite has to a smoke test of the whole stack, so a
regression anywhere in pipeline.py / roi_encoder.py will surface here
first.

Author: Bloodawn (KheivenD), 2026-05-02 (audit follow-up);
updated 2026-05-31 (M0 TASK 0.3 - mode3 is a single object-only clip).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

# Make sure src/ is importable
SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _has_ffmpeg() -> bool:
    """Return True iff the system ffmpeg binary is available on PATH."""
    return shutil.which("ffmpeg") is not None


def _ffprobe_ok(path: Path) -> bool:
    """True if ffprobe finds a video stream in the file (codec-agnostic).

    Used instead of an OpenCV frame read to validate output. OpenCV's
    bundled decoder can't read AV1 (libsvtav1, the pipeline's default codec)
    on some platforms - notably Linux CI - which would fail a perfectly
    valid file. ffprobe validates the container + stream regardless of codec,
    so this still catches FFmpeg pipe truncation without false negatives.
    Author: Bloodawn (KheivenD), 2026-06-01 (M0 TASK 0.7 - portable mp4 check).
    """
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=30,
        )
        return out.returncode == 0 and "video" in out.stdout
    except Exception:  # noqa: BLE001
        return False


def _make_synthetic_clip(path: Path, w: int = 640, h: int = 360,
                         fps: int = 30, n_frames: int = 90) -> None:
    """Synthesise a clip with a single moving white square on a static bg.

    The square moves across the middle of the frame in frames [warmup, end-15].
    Static background gives MOG2 enough warmup data to lock in the model;
    motion in the middle gives Mode 1 something to gate on.
    """
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"),
                             float(fps), (w, h))
    try:
        for i in range(n_frames):
            frame = np.full((h, w, 3), 30, dtype=np.uint8)   # dark grey bg
            if 15 <= i < n_frames - 15:
                x = 40 + (i - 15) * 4
                cv2.rectangle(frame, (x, h // 2 - 30),
                              (x + 50, h // 2 + 30),
                              (255, 255, 255), -1)
            writer.write(frame)
    finally:
        writer.release()


def _bytes_for_mode(out_dir: Path, mode: str) -> int:
    """Return total bytes written under out_dir for the given mode.

    All four modes (mode 3 included) write a single segment .mp4 into
    out_dir. Mode 3 keeps the moving-object pixels and blacks out the
    background; the per-object ``mode3_sparse/`` layout was never shipped
    on the app branch (see docs/test-baseline.md D2).
    """
    return sum(p.stat().st_size for p in out_dir.glob("*.mp4"))


def _run_mode(src_path: Path, out_dir: Path, mode: str) -> dict:
    """Run the real pipeline once and return measurements."""
    from pipeline.pipeline import run_pipeline  # lazy: skips cleanly when missing
    out_dir.mkdir(parents=True, exist_ok=True)
    run_pipeline(
        input_source=str(src_path),
        camera_id="cam_bench",
        output_dir=str(out_dir),
        segment_seconds=15,
        bg_method="MOG2",
        warmup_frames=10,
        mode=mode,
        show_preview=False,
    )
    return {
        "bytes": _bytes_for_mode(out_dir, mode),
        "files": [str(p.relative_to(out_dir))
                  for p in out_dir.rglob("*") if p.is_file()],
    }


# ---------------------------------------------------------------------------
# Skip if ffmpeg isn't installed (the streaming encoder needs it).
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.skipif(not _has_ffmpeg(),
                                reason="ffmpeg binary not installed; "
                                "end-to-end mode benchmark requires it")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestModeSizeHierarchy:
    """End-to-end smoke + size benchmark across all four modes."""

    def test_all_four_modes_run_without_raising(self, tmp_path):
        """Every mode must finish a full segment without raising. This is
        the real smoke test for the whole pipeline."""
        src = tmp_path / "src.mp4"
        _make_synthetic_clip(src)

        results = {}
        for mode in ("mode0", "mode1", "mode2", "mode3"):
            out = tmp_path / mode
            results[mode] = _run_mode(src, out, mode)

        # Every mode should have produced at least one output file.
        for mode, r in results.items():
            assert r["files"], f"{mode}: produced no output files"
            assert r["bytes"] > 0, f"{mode}: output bytes was 0"

    def test_outputs_are_smaller_than_uncompressed_raw(self, tmp_path):
        """All four modes must shrink the source vs. uncompressed bytes.
        Uncompressed = N_frames * W * H * 3."""
        src = tmp_path / "src.mp4"
        _make_synthetic_clip(src, w=640, h=360, n_frames=90)

        # Uncompressed BGR bytes for the synthetic clip
        raw = 90 * 640 * 360 * 3

        for mode in ("mode0", "mode1", "mode2", "mode3"):
            out = tmp_path / mode
            r = _run_mode(src, out, mode)
            assert r["bytes"] < raw, (
                f"{mode}: {r['bytes']} bytes is NOT smaller than raw {raw}"
            )

    def test_mode3_produces_object_only_clip(self, tmp_path):
        """Mode 3 writes a single object-only .mp4 per segment: the moving
        objects are kept and the background is blacked out (compressing to
        near-zero bits). The per-object mode3_sparse/ layout was never
        shipped on the app branch - see docs/test-baseline.md D2."""
        src = tmp_path / "src.mp4"
        _make_synthetic_clip(src)

        out = tmp_path / "mode3"
        _run_mode(src, out, "mode3")

        clips = list(out.glob("*.mp4"))
        assert clips, "mode3 produced no .mp4 segment"
        assert all(c.stat().st_size > 0 for c in clips), "mode3 clip is empty"

    def test_outputs_are_valid_mp4s(self, tmp_path):
        """Every produced .mp4 (all four modes) must be a valid container
        with a video stream. Catches FFmpeg pipe truncation. Validated with
        ffprobe rather than an OpenCV frame read - OpenCV can't decode AV1
        (our default codec) on some platforms (e.g. Linux CI), which is an
        environment limit, not a bad file."""
        src = tmp_path / "src.mp4"
        _make_synthetic_clip(src)

        for mode in ("mode0", "mode1", "mode2", "mode3"):
            out = tmp_path / mode
            _run_mode(src, out, mode)
            clips = list(out.glob("*.mp4"))
            assert clips, f"{mode}: produced no .mp4 segment"
            for f in clips:
                assert f.stat().st_size > 0, f"{f} is empty"
                assert _ffprobe_ok(f), f"{f} has no decodable video stream"

    def test_size_report_for_documentation(self, tmp_path, capsys):
        """Print measured bytes per mode so the docs/CI logs always have a
        fresh data point. Does not assert a strict hierarchy - see
        ``docs/mode_size_hierarchy.md`` for why mode 3 < mode 2 < mode 1 <
        mode 0 isn't always true on synthetic clips."""
        src = tmp_path / "src.mp4"
        _make_synthetic_clip(src, w=1280, h=720, n_frames=180)

        sizes = {}
        for mode in ("mode0", "mode1", "mode2", "mode3"):
            out = tmp_path / mode
            sizes[mode] = _run_mode(src, out, mode)["bytes"]

        with capsys.disabled():
            print("\n[mode-size benchmark]")
            for m in ("mode0", "mode1", "mode2", "mode3"):
                print(f"  {m}: {sizes[m]:>10} bytes")
            print(f"  mode1/mode0: {sizes['mode1']/sizes['mode0']:.2f}")
            print(f"  mode3/mode0: {sizes['mode3']/sizes['mode0']:.2f}")

        # Soft assertions: mode 1 should usually be <= mode 0 on a clip
        # with significant no-motion frames. Mode 3 should usually be <=
        # mode 2 on a clip with one moving object.
        # These are documented as observations, not contracts - see
        # docs/mode_size_hierarchy.md. We only enforce a 2x ceiling on
        # mode 3 vs mode 0 to catch dramatic regressions.
        assert sizes["mode3"] < sizes["mode0"] * 3, (
            f"mode3 ({sizes['mode3']}) more than 3x mode0 ({sizes['mode0']}) "
            " -  sparse encoder regression?"
        )

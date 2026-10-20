"""
Behavior pins for the compdet performance pass (src/compression, src/detection).

Each test compares an optimized hot-path routine against a straightforward
reference version of what the code did before, so a later edit that changes
the output (not just the speed) fails here.

Author: Bloodawn (KheivenD), 2026-10-13 (perf and readability pass).
"""

from types import SimpleNamespace

import cv2
import numpy as np
import pytest

from compression import roi_encoder as roi_mod
from compression.roi_encoder import ROIEncoder, draw_corner_overlay
from detection.object_filter import ObjectFilter, detect_dominant_color
from detection.onnx_backend import YoloOnnxDetector

RNG = np.random.default_rng(1234)


def _reference_overlay(frame, mode_label, elapsed_s):
    """The original full-frame blend: copy, black rectangle, addWeighted."""
    mins, secs = divmod(elapsed_s, 60)
    lines = [mode_label, f"{mins:02d}:{secs:02d}"]
    font, scale, thick, line_h, pad = cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1, 18, 6
    sizes = [cv2.getTextSize(ln, font, scale, thick)[0] for ln in lines]
    bx2 = 8 + max(sz[0] for sz in sizes) + 2 * pad
    by2 = 8 + len(lines) * line_h + 2 * pad
    overlay = frame.copy()
    cv2.rectangle(overlay, (8, 8), (bx2, by2), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, dst=frame)
    y = 8 + pad + line_h - 4
    for ln in lines:
        cv2.putText(frame, ln, (8 + pad, y), font, scale, (255, 255, 255), thick, cv2.LINE_AA)
        y += line_h


@pytest.mark.parametrize("shape", [(360, 640, 3), (1080, 1920, 3), (30, 40, 3), (5, 5, 3), (64, 64)])
def test_corner_overlay_matches_full_frame_blend(shape):
    frame = RNG.integers(0, 256, size=shape, dtype=np.uint8)
    expected, actual = frame.copy(), frame.copy()
    _reference_overlay(expected, "MODE 2 - PATCHES", 754)
    draw_corner_overlay(actual, "MODE 2 - PATCHES", 754)
    assert np.array_equal(expected, actual)


@pytest.fixture
def encoder(tmp_path):
    return ROIEncoder(output_dir=str(tmp_path / "out"), db_path=str(tmp_path / "m.db"),
                      codec="libx264")


@pytest.mark.parametrize("mode", ["plain", "object_only", "background", "compress_bg"])
def test_render_frame_leaves_input_untouched_and_draws_overlay(encoder, mode):
    frame = RNG.integers(0, 256, size=(120, 160, 3), dtype=np.uint8)
    original = frame.copy()
    background = RNG.integers(0, 256, size=frame.shape, dtype=np.uint8)
    boxes = [(10, 20, 30, 40), (150, 100, 40, 40), (-5, -5, 12, 12)]
    out = encoder._render_frame(
        frame, boxes,
        object_only=(mode == "object_only"),
        background_frame=background if mode == "background" else None,
        compress_background=(mode == "compress_bg"),
        draw_boxes=True, mode_label="MODE 0 - 24/7", elapsed_s=3,
    )
    assert np.array_equal(frame, original)
    assert out is not frame
    if mode == "plain":
        expected = frame.copy()
        for bx, by, bw, bh in boxes:
            x1, y1 = max(0, bx), max(0, by)
            x2, y2 = min(160, bx + bw), min(120, by + bh)
            cv2.rectangle(expected, (x1, y1), (x2, y2), (0, 255, 0), 2)
        _reference_overlay(expected, "MODE 0 - 24/7", 3)
        assert np.array_equal(out, expected)


def test_encode_segment_releases_retention_guard_when_ffmpeg_fails(encoder, monkeypatch):
    if roi_mod._active_outputs is None:
        pytest.skip("active_outputs registry not importable")

    class _FailedProc:
        stdin = SimpleNamespace(write=lambda data: None, close=lambda: None)

        def wait(self, timeout=None):
            return 1

    monkeypatch.setattr(roi_mod, "_ffmpeg_pipe_process", lambda args: _FailedProc())
    before = roi_mod._active_outputs.snapshot()
    frames = [np.zeros((16, 16, 3), dtype=np.uint8)] * 3
    with pytest.raises(RuntimeError, match="exit code 1"):
        encoder.encode_segment(frames, camera_id="cam_guard")
    assert roi_mod._active_outputs.snapshot() == before


def test_stream_pipe_receives_exact_frame_bytes(encoder):
    written = []
    encoder._stream_process = SimpleNamespace(stdin=SimpleNamespace(write=written.append))
    encoder._stream_fps = 30.0
    frame = RNG.integers(0, 256, size=(48, 64, 3), dtype=np.uint8)
    view = RNG.integers(0, 256, size=(48, 128, 3), dtype=np.uint8)[:, ::2]  # non-contiguous
    for f in (frame, view):
        encoder.write_frame(f, boxes=[], mode_label="", measure_sharpness=False)
    assert [bytes(memoryview(w)) for w in written] == [frame.tobytes(), view.tobytes()]
    encoder._stream_process = None


def _reference_dominant_color(frame, x, y, w, h):
    fh, fw = frame.shape[:2]
    cx, cy = x + w // 2, y + h // 2
    cw, ch = max(4, w // 2), max(4, h // 2)
    x1, y1 = max(0, cx - cw // 2), max(0, cy - ch // 2)
    x2, y2 = min(fw, cx + cw // 2), min(fh, cy + ch // 2)
    if x2 <= x1 or y2 <= y1:
        return "unknown"
    hsv = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2HSV)
    hue, sat, val = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    white = int(np.sum((sat < 40) & (val > 200)))
    black = int(np.sum(val < 50))
    gray = int(np.sum((sat < 50) & (val >= 50) & (val <= 200)))
    if white + black + gray > hue.size * 0.55:
        if white >= black and white >= gray:
            return "white"
        return "black" if black >= gray else "gray"
    if not np.any(sat >= 50):
        return "gray"
    hist, _ = np.histogram(hue[sat >= 50], bins=180, range=(0, 180))
    ranges = [("red", [(0, 10), (160, 179)]), ("orange", [(10, 22)]), ("yellow", [(22, 38)]),
              ("green", [(38, 82)]), ("cyan", [(82, 100)]), ("blue", [(100, 130)]),
              ("purple", [(130, 160)])]
    best, best_score = "unknown", 0
    for label, spans in ranges:
        score = sum(int(hist[lo:hi].sum()) for lo, hi in spans)
        if score > best_score:
            best, best_score = label, score
    return best


def test_dominant_color_matches_histogram_reference():
    frames = [RNG.integers(0, 256, size=(120, 160, 3), dtype=np.uint8) for _ in range(3)]
    for bgr in [(0, 0, 255), (0, 255, 255), (255, 0, 0), (255, 255, 255), (0, 0, 0), (90, 90, 90)]:
        frames.append(np.full((120, 160, 3), bgr, dtype=np.uint8))
    for frame in frames:
        for _ in range(60):
            box = tuple(int(v) for v in RNG.integers(-10, 150, size=4))
            assert detect_dominant_color(frame, *box) == _reference_dominant_color(frame, *box)


def test_suppression_lookup_matches_full_resolution_mask():
    filt = ObjectFilter(device="cpu", backend="onnx", suppress_after=2)
    filt._init_suppression((100, 70, 3))
    filt._suppress_grid[:] = RNG.integers(0, 4, size=filt._suppress_grid.shape)
    filt._suppressed_cells = filt._suppress_grid >= filt.suppress_after

    cell = filt._grid_cell
    mask = np.zeros((100, 70), dtype=bool)
    rows, cols = filt._suppress_grid.shape
    for r in range(rows):
        for c in range(cols):
            mask[r * cell:(r + 1) * cell, c * cell:(c + 1) * cell] = (
                filt._suppress_grid[r, c] >= filt.suppress_after)

    for x, y, w, h in RNG.integers(-20, 120, size=(300, 4)):
        cx = max(0, min(69, x + w // 2))
        cy = max(0, min(99, y + h // 2))
        assert filt._is_suppressed(int(x), int(y), int(w), int(h)) == bool(mask[cy, cx])


def test_suppression_counters_saturate_and_ignore_degenerate_boxes():
    filt = ObjectFilter(device="cpu", backend="onnx")
    filt._init_suppression((64, 64, 3))
    filt._suppress_grid[0, 0] = 32767
    filt._increment_suppression(0, 0, 40, 10)
    assert filt._suppress_grid[0, 0] == 32767 and filt._suppress_grid[0, 1] == 1
    before = filt._suppress_grid.copy()
    filt._increment_suppression(-50, -50, 10, 10)   # entirely off-frame
    filt._reset_suppression(0, 0, 0, 0)            # zero-size box at the origin
    assert np.array_equal(filt._suppress_grid, before)


def test_onnx_blob_matches_astype_divide_transpose():
    det = YoloOnnxDetector(model_path="does-not-exist.onnx", imgsz=64)
    seen = {}

    def _run(_outputs, feeds):
        seen["blob"] = feeds["images"]
        return [np.zeros((1, 84, 0), dtype=np.float32)]

    det._session = SimpleNamespace(run=_run)
    det._input_name = "images"
    det._available = True
    image = RNG.integers(0, 256, size=(40, 64, 3), dtype=np.uint8)
    det.infer(image)

    canvas, _, _ = det._letterbox(image)
    expected = np.ascontiguousarray(
        np.transpose(canvas[:, :, ::-1].astype(np.float32) / 255.0, (2, 0, 1))[None, ...])
    assert seen["blob"].dtype == np.float32
    assert seen["blob"].flags["C_CONTIGUOUS"]
    assert np.array_equal(seen["blob"], expected)

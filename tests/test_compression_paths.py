"""
tests/test_compression_paths.py

Every way of compressing (Start, Auto-compress, Demo) must give the same
picture, and mode 2 must never degrade to mode 3. Found on 2026-11-25:

  * Mode 2 used a black background until the scene had a fully quiet gap. A
    swaying branch meant no gap ever came, so mode 2 looked exactly like mode 3.
  * Only the demo renderer drew boxes; Start and Auto-compress never did, and
    YOLO (person / vehicle labels for search) was off unless ticked.

Author: Bloodawn (KheivenD), 2026-11-25.
"""
import numpy as np
import cv2

from compression.roi_encoder import draw_corner_overlay, draw_labeled_boxes, _box_color
from pipeline import pipeline as P


def test_background_plate_ignores_moving_pixels():
    plate = None
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    bg = np.full((40, 40, 3), 100, np.uint8)
    for i in range(200):
        frame = bg.copy()
        mask = np.zeros((40, 40), np.uint8)
        x = (i * 3) % 30
        frame[10:20, x:x + 8] = 250          # something always moving
        mask[10:20, x:x + 8] = 255
        plate = P._update_background_plate(plate, frame, mask, kernel, alpha=0.1)
    out = cv2.convertScaleAbs(plate)
    # The plate converges on the empty scene, not on the moving object.
    assert abs(int(out[15, 5, 0]) - 100) <= 5
    assert out.max() < 150


def test_overlay_draws_class_label_with_its_own_color():
    img = np.zeros((540, 960, 3), np.uint8)
    draw_labeled_boxes(img, [(100, 100, 80, 160)], ["person"])
    assert tuple(int(v) for v in img[100, 140]) == _box_color("person")   # top edge
    assert _box_color("car") != _box_color("person") != _box_color("")


def test_corner_overlay_uses_the_given_time_text():
    a = np.zeros((540, 960, 3), np.uint8)
    b = np.zeros((540, 960, 3), np.uint8)
    draw_corner_overlay(a, "MODE 2 - SMART", 5, "00:01:05")
    draw_corner_overlay(b, "MODE 2 - SMART", 5)
    assert not np.array_equal(a, b)


def test_auto_yolo_respects_the_opt_out(monkeypatch):
    monkeypatch.setenv("SVCS_NO_AUTO_YOLO", "1")
    assert P._yolo_model_available() is False


def test_every_entry_point_passes_the_same_overlay_switch():
    from pathlib import Path
    src = Path(P.__file__).resolve().parents[1]
    runner = (src / "gui" / "services" / "pipeline_runner.py").read_text(encoding="utf-8")
    auto = (src / "gui" / "services" / "autocompress_runner.py").read_text(encoding="utf-8")
    demo = (src / "demo" / "run_demo.py").read_text(encoding="utf-8")
    assert 'overlays=bool(config.get("overlays", True))' in runner
    assert "overlays=_overlays" in auto
    assert "overlays=False" in demo            # the demo renderer draws its own
    assert 'object_filter=config.get("object_filter", True)' in runner

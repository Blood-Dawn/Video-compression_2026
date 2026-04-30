import json
from pathlib import Path

import cv2
import numpy as np

from src.demo.demo import (
    load_sparse_mode3_metadata,
    make_metrics_card,
    render_sparse_mode3_frame,
    render_view,
)


def test_standard_view_can_draw_boxes_without_tint():
    frame = np.full((40, 40, 3), 100, dtype=np.uint8)
    rendered = render_view(
        frame,
        [[10, 10, 12, 12]],
        view="standard",
        draw_boxes=True,
        draw_tint=False,
    )

    assert rendered[10, 10].tolist() == [0, 255, 0]
    assert rendered[15, 15].tolist() == [100, 100, 100]


def test_standard_view_can_apply_tint_without_boxes():
    frame = np.full((40, 40, 3), 100, dtype=np.uint8)
    rendered = render_view(
        frame,
        [[10, 10, 12, 12]],
        view="standard",
        draw_boxes=False,
        draw_tint=True,
    )

    assert rendered[15, 15].tolist() == [100, 100, 100]
    assert rendered[5, 5].tolist() != [100, 100, 100]
    assert rendered[10, 10].tolist() != [0, 255, 0]


def test_standard_view_tint_keeps_roi_pixels_and_draws_box_last():
    frame = np.full((40, 40, 3), 100, dtype=np.uint8)
    rendered = render_view(
        frame,
        [[10, 10, 12, 12]],
        view="standard",
        draw_boxes=True,
        draw_tint=True,
    )

    assert rendered[5, 5].tolist() != [100, 100, 100]
    assert rendered[15, 15].tolist() == [100, 100, 100]
    assert rendered[10, 10].tolist() == [0, 255, 0]


def test_standard_view_without_boxes_or_tint_returns_original_frame():
    frame = np.full((40, 40, 3), 100, dtype=np.uint8)
    rendered = render_view(
        frame,
        [[10, 10, 12, 12]],
        view="standard",
        draw_boxes=False,
        draw_tint=False,
    )

    assert np.array_equal(rendered, frame)


def test_roi_tint_view_honors_no_tint_but_keeps_boxes():
    frame = np.full((40, 40, 3), 100, dtype=np.uint8)
    rendered = render_view(
        frame,
        [[10, 10, 12, 12]],
        view="roi_tint",
        draw_boxes=True,
        draw_tint=False,
    )

    assert rendered[10, 10].tolist() == [0, 255, 0]
    assert rendered[15, 15].tolist() == [100, 100, 100]


def test_make_metrics_card_creates_requested_frames():
    frames = make_metrics_card(
        320,
        240,
        mode="mode2",
        metrics={
            "compression_ratio": 5.0,
            "space_saved_pct": 80.0,
            "original_mb": 10.0,
            "compressed_mb": 2.0,
            "cpu": {
                "cpu_percent": 45.0,
                "cpu_seconds": 1.2,
                "wall_seconds": 2.6,
            },
            "latency_ms": None,
        },
        frame_count=3,
    )

    assert len(frames) == 3
    assert frames[0].shape == (240, 320, 3)
    assert np.count_nonzero(frames[0]) > 0


def test_make_metrics_card_handles_storage_increase():
    frames = make_metrics_card(
        320,
        240,
        mode="mode2",
        metrics={
            "compression_ratio": 0.98,
            "space_saved_pct": -1.7,
            "original_mb": 15.9,
            "compressed_mb": 16.1,
            "cpu": {"cpu_core_equivalent": 7.1, "cpu_seconds": 119.7, "wall_seconds": 16.8},
            "latency_ms": None,
        },
        frame_count=1,
    )

    assert len(frames) == 1
    assert frames[0].shape == (240, 320, 3)


def test_sparse_mode3_frame_reconstructs_bbox_crop_without_mask(tmp_path):
    artifact_dir = tmp_path / "seg"
    crop_dir = artifact_dir / "crops"
    crop_dir.mkdir(parents=True)
    crop = np.full((8, 10, 3), (40, 120, 220), dtype=np.uint8)
    cv2.imwrite(str(crop_dir / "f00000003_o00.jpg"), crop)

    metadata = {
        "mode": "mode3",
        "frame_width": 24,
        "frame_height": 20,
        "fps": 10.0,
        "frames": [
            {
                "source_frame_index": 3,
                "objects": [
                    {
                        "bbox": [7, 6, 10, 8],
                        "crop_path": "crops/f00000003_o00.jpg",
                        "mask_path": None,
                    }
                ],
            }
        ],
    }
    (artifact_dir / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")

    loaded = load_sparse_mode3_metadata(artifact_dir / "metadata.json")
    assert loaded is not None
    loaded_dir, loaded_metadata = loaded
    frame = render_sparse_mode3_frame(
        loaded_dir,
        loaded_metadata,
        loaded_metadata["frames"][0],
    )

    assert frame.shape == (20, 24, 3)
    assert np.count_nonzero(frame[:6]) == 0
    assert np.count_nonzero(frame[:, :7]) == 0
    assert np.count_nonzero(frame[6:14, 7:17]) > 0


def test_sparse_mode3_frame_reuses_crop_and_mask_cache(tmp_path, monkeypatch):
    artifact_dir = tmp_path / "seg"
    crop_dir = artifact_dir / "crops"
    mask_dir = artifact_dir / "masks"
    crop_dir.mkdir(parents=True)
    mask_dir.mkdir(parents=True)

    crop_path = crop_dir / "object.jpg"
    mask_path = mask_dir / "object.png"
    cv2.imwrite(str(crop_path), np.full((8, 10, 3), (40, 120, 220), dtype=np.uint8))
    mask = np.zeros((8, 10), dtype=np.uint8)
    mask[:, :5] = 255
    cv2.imwrite(str(mask_path), mask)

    metadata = {
        "mode": "mode3",
        "frame_width": 24,
        "frame_height": 20,
        "fps": 10.0,
    }
    frame_record = {
        "source_frame_index": 3,
        "objects": [
            {
                "bbox": [7, 6, 10, 8],
                "crop_path": "crops/object.jpg",
                "mask_path": "masks/object.png",
            }
        ],
    }
    image_cache = {}
    read_counts = {crop_path.resolve(): 0, mask_path.resolve(): 0}
    original_imread = cv2.imread

    def counting_imread(path, flags):
        read_counts[Path(path).resolve()] += 1
        return original_imread(path, flags)

    monkeypatch.setattr(cv2, "imread", counting_imread)

    render_sparse_mode3_frame(artifact_dir, metadata, frame_record, image_cache)
    render_sparse_mode3_frame(artifact_dir, metadata, frame_record, image_cache)

    assert read_counts[crop_path.resolve()] == 1
    assert read_counts[mask_path.resolve()] == 1

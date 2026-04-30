import json
import sqlite3
from pathlib import Path

import cv2
import numpy as np

from compression.layer_encoder import LayerSegmentEncoder


class DummyRegion:
    def __init__(self, x, y, w, h):
        self.x = x
        self.y = y
        self.w = w
        self.h = h

    def to_tuple(self):
        return (self.x, self.y, self.w, self.h)


def test_layer_encoder_writes_mode3_artifact_and_metadata(tmp_path):
    db_path = tmp_path / "metadata.db"
    encoder = LayerSegmentEncoder(output_dir=str(tmp_path), db_path=str(db_path))

    frame = np.zeros((32, 48, 3), dtype=np.uint8)
    frame[8:20, 10:26] = (40, 160, 220)
    mask = np.zeros((32, 48), dtype=np.uint8)
    mask[8:20, 10:26] = 255

    encoder.add_frame(
        frame=frame,
        mask=mask,
        regions=[DummyRegion(10, 8, 16, 12)],
        camera_id="cam_layer",
        segment_index=0,
        source_frame_index=12,
        source_time_seconds=1.2,
        fps=10.0,
    )
    preview_path = Path(encoder.flush_segment(camera_id="cam_layer", object_type="unknown"))

    assert preview_path.exists()
    artifact_dir = preview_path.parent
    metadata_path = artifact_dir / "metadata.json"
    assert metadata_path.exists()

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["mode"] == "mode3"
    assert metadata["crop_format"] == "png"
    assert metadata["mask_policy"] == "filled_external_contours"
    assert metadata["event_frame_count"] == 1
    assert metadata["object_count"] == 1
    obj = metadata["frames"][0]["objects"][0]
    assert (artifact_dir / obj["crop_path"]).exists()
    assert (artifact_dir / obj["mask_path"]).exists()
    assert obj["crop_path"].endswith(".png")

    crop_img = cv2.imread(str(artifact_dir / obj["crop_path"]), cv2.IMREAD_COLOR)
    assert crop_img is not None
    assert np.array_equal(crop_img, frame[8:20, 10:26])

    mask_img = cv2.imread(str(artifact_dir / obj["mask_path"]), cv2.IMREAD_GRAYSCALE)
    assert mask_img is not None
    assert int(mask_img.max()) == 255

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT target_detected, roi_count, file_size, file_path, object_type FROM segments"
        ).fetchone()
    assert row[0] == 1
    assert row[1] == 1
    assert row[2] > 0
    assert row[3] == str(preview_path)
    assert row[4] == "unknown"


def test_layer_encoder_empty_flush_returns_none(tmp_path):
    db_path = tmp_path / "metadata.db"
    encoder = LayerSegmentEncoder(output_dir=str(tmp_path), db_path=str(db_path))

    assert encoder.flush_segment(camera_id="cam_empty") is None

    with sqlite3.connect(db_path) as conn:
        count = conn.execute("SELECT COUNT(*) FROM segments").fetchone()[0]
    assert count == 0


def test_layer_encoder_fills_internal_mask_holes(tmp_path):
    db_path = tmp_path / "metadata.db"
    encoder = LayerSegmentEncoder(output_dir=str(tmp_path), db_path=str(db_path))

    frame = np.zeros((32, 48, 3), dtype=np.uint8)
    frame[8:24, 10:30] = (20, 80, 200)

    mask = np.zeros((32, 48), dtype=np.uint8)
    mask[8:24, 10:30] = 255
    mask[12:18, 16:24] = 0

    encoder.add_frame(
        frame=frame,
        mask=mask,
        regions=[DummyRegion(10, 8, 20, 16)],
        camera_id="cam_layer",
        segment_index=0,
        source_frame_index=1,
        source_time_seconds=0.1,
        fps=10.0,
    )
    preview_path = Path(encoder.flush_segment(camera_id="cam_layer"))

    metadata = json.loads((preview_path.parent / "metadata.json").read_text(encoding="utf-8"))
    obj = metadata["frames"][0]["objects"][0]
    mask_img = cv2.imread(str(preview_path.parent / obj["mask_path"]), cv2.IMREAD_GRAYSCALE)

    assert mask_img is not None
    assert int(mask_img[6, 8]) == 255


def test_layer_encoder_can_skip_preview_for_faster_mode3(tmp_path):
    db_path = tmp_path / "metadata.db"
    encoder = LayerSegmentEncoder(
        output_dir=str(tmp_path),
        db_path=str(db_path),
        write_preview=False,
    )

    frame = np.full((16, 16, 3), 30, dtype=np.uint8)
    mask = np.zeros((16, 16), dtype=np.uint8)
    mask[4:12, 4:12] = 255

    encoder.add_frame(
        frame=frame,
        mask=mask,
        regions=[DummyRegion(4, 4, 8, 8)],
        camera_id="cam_layer",
        segment_index=0,
        source_frame_index=1,
        source_time_seconds=0.1,
        fps=10.0,
    )
    metadata_path = Path(encoder.flush_segment(camera_id="cam_layer"))

    assert metadata_path.name == "metadata.json"
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert metadata["preview"] is None
    assert not (metadata_path.parent / "preview.mp4").exists()


def test_layer_encoder_can_store_only_bbox_crops_without_masks_or_preview(tmp_path):
    db_path = tmp_path / "metadata.db"
    encoder = LayerSegmentEncoder(
        output_dir=str(tmp_path),
        db_path=str(db_path),
        crop_format="jpg",
        crop_quality=75,
        write_preview=False,
        write_masks=False,
    )

    frame = np.full((24, 24, 3), 10, dtype=np.uint8)
    frame[6:14, 7:17] = (40, 120, 220)
    mask = np.zeros((24, 24), dtype=np.uint8)
    mask[6:14, 7:17] = 255

    encoder.add_frame(
        frame=frame,
        mask=mask,
        regions=[DummyRegion(7, 6, 10, 8)],
        camera_id="cam_layer",
        segment_index=0,
        source_frame_index=3,
        source_time_seconds=0.3,
        fps=10.0,
    )
    metadata_path = Path(encoder.flush_segment(camera_id="cam_layer"))

    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    obj = metadata["frames"][0]["objects"][0]

    assert metadata["preview"] is None
    assert metadata["mask_format"] is None
    assert metadata["mask_policy"] == "none"
    assert obj["mask_path"] is None
    assert obj["crop_path"].endswith(".jpg")
    assert (metadata_path.parent / obj["crop_path"]).exists()
    assert not (metadata_path.parent / "masks").exists()

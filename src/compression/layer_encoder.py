"""
layer_encoder.py

Sparse foreground-layer encoder for object-only compression modes.

Mode 3 stores only pixels where foreground objects were detected. Each segment
is written as an inspectable artifact directory containing:
  - object crop PNGs by default, or JPEGs when explicitly requested
  - binary mask PNGs
  - metadata.json
  - optional preview.mp4 with objects composited onto a black canvas

The implementation is intentionally CPU-only and streams preview frames directly
to OpenCV's VideoWriter. It does not keep full-frame segment buffers in memory.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import cv2
import numpy as np

from utils.db import get_connection, initialize_database, insert_segment


def _region_tuple(region: object) -> tuple[int, int, int, int]:
    if hasattr(region, "to_tuple"):
        x, y, w, h = region.to_tuple()
    else:
        x, y, w, h = region
    return int(x), int(y), int(w), int(h)


def _directory_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _filled_object_mask(mask_crop: np.ndarray, close_kernel_size: int) -> np.ndarray:
    """
    Convert a raw foreground crop into a solid object silhouette.

    Background subtraction often leaves holes inside real objects when interior
    pixels look like the learned background. Vehicle windows are the common case:
    they can be cut out of the object-only preview even though they are part of
    the object we want to retain. Drawing external contours filled preserves the
    whole visible object while still excluding the padded background around it.
    """
    _, binary = cv2.threshold(mask_crop, 0, 255, cv2.THRESH_BINARY)
    if not np.any(binary):
        return binary

    if close_kernel_size > 1:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_ELLIPSE, (close_kernel_size, close_kernel_size)
        )
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)

    contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(binary)
    if contours:
        cv2.drawContours(filled, contours, -1, 255, thickness=cv2.FILLED)
    return filled


class LayerSegmentEncoder:
    """
    Writes sparse foreground-layer segment artifacts.

    One encoder instance owns at most one open segment at a time. Frames are
    added incrementally and written to disk immediately, which keeps memory use
    bounded for CPU-only field deployments.
    """

    def __init__(
        self,
        output_dir: str = "outputs/",
        db_path: str = "outputs/metadata.db",
        crop_quality: int = 85,
        crop_format: str = "png",
        png_compression: int = 1,
        fill_mask_holes: bool = True,
        mask_close_kernel_size: int = 7,
        write_preview: bool = True,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        self.crop_quality = int(crop_quality)
        self.crop_format = crop_format.lower().lstrip(".")
        if self.crop_format not in {"png", "jpg", "jpeg"}:
            raise ValueError("crop_format must be 'png' or 'jpg'")
        self.png_compression = int(max(0, min(9, png_compression)))
        self.fill_mask_holes = bool(fill_mask_holes)
        self.mask_close_kernel_size = int(max(1, mask_close_kernel_size))
        self.write_preview = bool(write_preview)
        initialize_database(db_path)
        self._reset_segment_state()

    def _reset_segment_state(self) -> None:
        self._segment_dir: Optional[Path] = None
        self._crop_dir: Optional[Path] = None
        self._mask_dir: Optional[Path] = None
        self._preview_path: Optional[Path] = None
        self._preview_writer: Optional[cv2.VideoWriter] = None
        self._metadata: dict = {}
        self._frame_records: list[dict] = []
        self._object_count = 0
        self._event_frame_count = 0
        self._source_start_frame: Optional[int] = None
        self._source_end_frame: Optional[int] = None

    @property
    def has_data(self) -> bool:
        return self._object_count > 0

    @property
    def object_count(self) -> int:
        return self._object_count

    def _start_segment(
        self,
        *,
        camera_id: str,
        segment_index: int,
        frame_shape: tuple[int, int, int],
        fps: float,
    ) -> None:
        timestamp = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
        segment_name = f"{camera_id}_{timestamp}_mode3_seg{segment_index:04d}"
        segment_dir = self.output_dir / "mode3_segments" / segment_name
        crop_dir = segment_dir / "crops"
        mask_dir = segment_dir / "masks"
        crop_dir.mkdir(parents=True, exist_ok=True)
        mask_dir.mkdir(parents=True, exist_ok=True)

        h, w = frame_shape[:2]
        preview_path = segment_dir / "preview.mp4" if self.write_preview else None
        writer = None
        if preview_path is not None:
            writer = cv2.VideoWriter(
                str(preview_path),
                cv2.VideoWriter_fourcc(*"mp4v"),
                fps if fps > 0 else 30.0,
                (w, h),
            )
            if not writer.isOpened():
                raise RuntimeError(f"Failed to open mode3 preview writer: {preview_path}")

        self._segment_dir = segment_dir
        self._crop_dir = crop_dir
        self._mask_dir = mask_dir
        self._preview_path = preview_path
        self._preview_writer = writer
        self._metadata = {
            "mode": "mode3",
            "camera_id": camera_id,
            "created_utc": timestamp,
            "segment_index": int(segment_index),
            "frame_width": int(w),
            "frame_height": int(h),
            "fps": float(fps),
            "crop_format": "jpg" if self.crop_format == "jpeg" else self.crop_format,
            "mask_format": "png",
            "mask_policy": "filled_external_contours" if self.fill_mask_holes else "raw_foreground",
            "preview": "preview.mp4" if self.write_preview else None,
            "frames": self._frame_records,
        }

    def add_frame(
        self,
        *,
        frame: np.ndarray,
        mask: np.ndarray,
        regions: Iterable[object],
        camera_id: str,
        segment_index: int,
        source_frame_index: int,
        source_time_seconds: float,
        fps: float,
    ) -> None:
        """
        Store foreground object crops and masks for one source frame.

        Empty region lists are ignored; mode policy should normally prevent
        this method from being called for no-motion frames.
        """
        region_tuples = [_region_tuple(region) for region in regions]
        if not region_tuples:
            return

        if self._segment_dir is None:
            self._start_segment(
                camera_id=camera_id,
                segment_index=segment_index,
                frame_shape=frame.shape,
                fps=fps,
            )

        assert self._crop_dir is not None
        assert self._mask_dir is not None

        frame_h, frame_w = frame.shape[:2]
        frame_record = {
            "source_frame_index": int(source_frame_index),
            "source_time_seconds": float(source_time_seconds),
            "objects": [],
        }
        preview = np.zeros_like(frame) if self.write_preview else None

        for region_index, (x, y, w, h) in enumerate(region_tuples):
            x1 = max(0, x)
            y1 = max(0, y)
            x2 = min(frame_w, x + w)
            y2 = min(frame_h, y + h)
            if x2 <= x1 or y2 <= y1:
                continue

            crop = frame[y1:y2, x1:x2]
            mask_crop = mask[y1:y2, x1:x2]
            if self.fill_mask_holes:
                binary_mask = _filled_object_mask(mask_crop, self.mask_close_kernel_size)
            else:
                _, binary_mask = cv2.threshold(mask_crop, 0, 255, cv2.THRESH_BINARY)
            if not np.any(binary_mask):
                binary_mask = np.full((y2 - y1, x2 - x1), 255, dtype=np.uint8)

            object_id = self._object_count
            stem = f"f{source_frame_index:08d}_o{region_index:02d}"
            crop_ext = "jpg" if self.crop_format in {"jpg", "jpeg"} else "png"
            crop_name = f"{stem}.{crop_ext}"
            mask_name = f"{stem}.png"
            crop_path = self._crop_dir / crop_name
            mask_path = self._mask_dir / mask_name

            if crop_ext == "png":
                crop_params = [int(cv2.IMWRITE_PNG_COMPRESSION), self.png_compression]
            else:
                crop_params = [int(cv2.IMWRITE_JPEG_QUALITY), self.crop_quality]
            ok_crop = cv2.imwrite(str(crop_path), crop, crop_params)
            ok_mask = cv2.imwrite(str(mask_path), binary_mask)
            if not ok_crop or not ok_mask:
                raise RuntimeError(f"Failed to write mode3 crop/mask for {stem}")

            if preview is not None:
                roi = preview[y1:y2, x1:x2]
                roi[binary_mask > 0] = crop[binary_mask > 0]

            frame_record["objects"].append({
                "object_id": int(object_id),
                "bbox": [int(x1), int(y1), int(x2 - x1), int(y2 - y1)],
                "crop_path": f"crops/{crop_name}",
                "mask_path": f"masks/{mask_name}",
                "area": int((binary_mask > 0).sum()),
            })
            self._object_count += 1

        if frame_record["objects"]:
            if self._preview_writer is not None and preview is not None:
                self._preview_writer.write(preview)
            self._frame_records.append(frame_record)
            self._event_frame_count += 1
            if self._source_start_frame is None:
                self._source_start_frame = int(source_frame_index)
            self._source_end_frame = int(source_frame_index)

    def flush_segment(self, *, camera_id: str, object_type: str = "unknown") -> Optional[str]:
        """
        Finalize the current sparse segment and insert its metadata DB row.

        Returns the preview MP4 path when previews are enabled, the metadata
        path when previews are disabled, or None if no foreground objects were
        stored for this segment window.
        """
        if self._segment_dir is None or not self.has_data:
            self._close_writer()
            self._reset_segment_state()
            return None

        self._close_writer()

        self._metadata["event_frame_count"] = int(self._event_frame_count)
        self._metadata["object_count"] = int(self._object_count)
        self._metadata["source_start_frame"] = self._source_start_frame
        self._metadata["source_end_frame"] = self._source_end_frame
        metadata_path = self._segment_dir / "metadata.json"
        metadata_path.write_text(json.dumps(self._metadata, indent=2), encoding="utf-8")

        file_size = _directory_size(self._segment_dir)
        duration = (
            self._event_frame_count / float(self._metadata["fps"])
            if self._metadata["fps"] > 0
            else 0.0
        )
        timestamp = self._metadata["created_utc"]

        insert_segment(
            timestamp=timestamp,
            camera_id=camera_id,
            target_detected=True,
            roi_count=self._object_count,
            file_size=file_size,
            duration=duration,
            file_path=str(self._preview_path or metadata_path),
            object_type=object_type,
            db_path=self.db_path,
        )

        out = str(self._preview_path or metadata_path)
        self._reset_segment_state()
        return out

    def _close_writer(self) -> None:
        if self._preview_writer is not None:
            self._preview_writer.release()
            self._preview_writer = None

    def get_storage_report(self) -> dict:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*),
                    COALESCE(SUM(file_size), 0),
                    COALESCE(SUM(target_detected), 0),
                    COALESCE(SUM(roi_count), 0),
                    COALESCE(SUM(duration), 0.0)
                FROM segments
                """
            ).fetchone()

        return {
            "total_segments": row[0],
            "total_bytes": row[1],
            "total_gb": round(row[1] / 1e9, 3),
            "segments_with_targets": row[2],
            "total_roi_detections": row[3],
            "total_duration_hours": round(row[4] / 3600, 2),
        }

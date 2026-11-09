"""Segments finished in the same second must not overwrite each other."""

import sys
from pathlib import Path

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from compression.roi_encoder import _unique_segment_path  # noqa: E402


def test_first_segment_of_a_second_keeps_the_plain_name(tmp_path):
    assert _unique_segment_path(tmp_path, "cam", "20260101T000000Z") == tmp_path / "cam_20260101T000000Z.mp4"


def test_taken_names_get_a_counter(tmp_path):
    seen = []
    for _ in range(4):
        p = _unique_segment_path(tmp_path, "cam", "20260101T000000Z")
        assert p not in seen
        p.write_bytes(b"x")
        seen.append(p)
    assert [p.name for p in seen] == [
        "cam_20260101T000000Z.mp4", "cam_20260101T000000Z_1.mp4",
        "cam_20260101T000000Z_2.mp4", "cam_20260101T000000Z_3.mp4"]


def test_other_seconds_and_cameras_are_unaffected(tmp_path):
    (tmp_path / "cam_20260101T000000Z.mp4").write_bytes(b"x")
    assert _unique_segment_path(tmp_path, "cam", "20260101T000001Z").name == "cam_20260101T000001Z.mp4"
    assert _unique_segment_path(tmp_path, "other", "20260101T000000Z").name == "other_20260101T000000Z.mp4"

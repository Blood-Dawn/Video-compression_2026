"""Pins the helpers taken out of the /api/segments handler."""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.routes import files_bp as fb  # noqa: E402
from utils.db.schema import initialize_database  # noqa: E402


# -- filters -----------------------------------------------------------------


def test_no_args_means_visible_rows_only_and_limit_200():
    filters, params, limit = fb._segment_filters({})
    assert filters == ["COALESCE(hidden, 0) = 0"] and params == [] and limit == 200


@pytest.mark.parametrize("cls", ["person", "vehicle", "animal"])
def test_single_class_also_matches_combo_labels(cls):
    filters, params, limit = fb._segment_filters({"object_type": cls})
    assert params == [cls, f"{cls}+%", f"%+{cls}"] and limit == 500
    assert filters[1].count("?") == 3


@pytest.mark.parametrize("value", ["person+vehicle", "unknown", "bogus"])
def test_combo_or_other_type_is_an_exact_match(value):
    filters, params, _ = fb._segment_filters({"object_type": value})
    assert filters[1] == "COALESCE(object_type,'unknown') = ?" and params == [value]


def test_simple_filters_keep_their_order_and_values():
    args = {"color": "red", "scene_type": "highway", "time_of_day": "night", "camera_id": "cam_01",
            "start_time": "2026-01-01", "end_time": "2026-02-01"}
    filters, params, limit = fb._segment_filters(args)
    assert params == ["red", "highway", "night", "cam_01", "2026-01-01", "2026-02-01"]
    assert filters[1:] == ["dominant_color = ?", "COALESCE(scene_type,'unknown') = ?", "time_of_day = ?",
                           "camera_id = ?", "timestamp >= ?", "timestamp <= ?"] and limit == 500


def test_min_roi_count_must_be_an_integer_but_still_counts_as_a_filter():
    filters, params, limit = fb._segment_filters({"min_roi_count": "3"})
    assert filters[-1] == "roi_count >= ?" and params == [3]
    filters, params, limit = fb._segment_filters({"min_roi_count": "x"})
    assert filters == ["COALESCE(hidden, 0) = 0"] and params == [] and limit == 500


def test_flags_only_trigger_on_exactly_1():
    filters, params, _ = fb._segment_filters({"encrypted_only": "1", "pose_verified_only": "1"})
    assert params == ["%.enc"] and "COALESCE(pose_verified_person_count, 0) > 0" in filters
    assert fb._segment_filters({"encrypted_only": "yes", "pose_verified_only": "true"})[2] == 200


def test_values_are_stripped_and_never_put_in_the_sql_text():
    filters, params, _ = fb._segment_filters({"color": "  red  ", "camera_id": "x'; DROP TABLE segments;--"})
    assert params == ["red", "x'; DROP TABLE segments;--"]
    assert not any("DROP" in f for f in filters)


# -- cpu stats ---------------------------------------------------------------


def test_cpu_stats_are_read_once_per_folder(tmp_path):
    (tmp_path / "cpu_stats.json").write_text(json.dumps({"avg": 5}))
    cache = {}
    assert fb._cpu_stats_for_dir(str(tmp_path), cache) == {"avg": 5}
    (tmp_path / "cpu_stats.json").write_text(json.dumps({"avg": 99}))
    assert fb._cpu_stats_for_dir(str(tmp_path), cache) == {"avg": 5}


def test_missing_or_broken_cpu_stats_are_none(tmp_path):
    assert fb._cpu_stats_for_dir(str(tmp_path), {}) is None
    (tmp_path / "cpu_stats.json").write_text("not json")
    assert fb._cpu_stats_for_dir(str(tmp_path), {}) is None


# -- rows --------------------------------------------------------------------


def _row(path="clip.mp4", classes='["car"]', size=2048, dur=12.34):
    return ("2026-05-01T120000Z", "cam_01", 1, 4, size, dur, path, "vehicle", 55.5, "sharp", classes,
            "red", "street", "day", 2, 0, 1)


def test_row_to_json_shapes_every_field(tmp_path):
    (tmp_path / "clip.mp4").write_bytes(b"x")
    (tmp_path / "cpu_stats.json").write_text(json.dumps({"avg": 1, "max": 2, "min": 0, "samples": 3, "duration_s": 4.5}))
    out = fb._segment_to_json(_row(), str(tmp_path), {})
    assert out["file_size_kb"] == 2.0 and out["duration_s"] == 12.3 and out["target_detected"] is True
    assert out["object_classes"] == ["car"] and out["playable_url"].startswith("/api/media?path=")
    assert (out["cpu_avg"], out["cpu_max"], out["cpu_min"], out["cpu_samples"], out["cpu_duration_s"]) == (1, 2, 0, 3, 4.5)
    assert out["pose_verified_person_count"] == 1 and out["vehicle_count"] == 2


def test_row_without_a_file_or_stats_has_no_url_and_null_cpu(tmp_path):
    out = fb._segment_to_json(_row(path="gone.mp4", classes="not json"), str(tmp_path), {})
    assert out["playable_url"] is None and out["object_classes"] == []
    assert out["cpu_avg"] is None and out["cpu_samples"] is None


def test_non_playable_extension_gets_no_url(tmp_path):
    (tmp_path / "clip.enc").write_bytes(b"x")
    assert fb._segment_to_json(_row(path="clip.enc"), str(tmp_path), {})["playable_url"] is None


# -- multi database query ----------------------------------------------------


def _db(folder: Path, stamps):
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "metadata.db"
    initialize_database(str(db))
    conn = sqlite3.connect(db)
    for i, ts in enumerate(stamps):
        conn.execute("INSERT INTO segments (timestamp,camera_id,target_detected,roi_count,file_size,duration,"
                     "file_path,object_type) VALUES (?,?,?,?,?,?,?,?)", (ts, "c", 1, 1, 1, 1.0, f"{ts}.mp4", "person"))
    conn.commit()
    conn.close()
    return db


def test_rows_from_every_db_are_merged_newest_first_and_capped(tmp_path):
    a = _db(tmp_path / "a", ["2026-01-01", "2026-03-01"])
    b = _db(tmp_path / "b", ["2026-02-01", "2026-04-01"])
    rows = fb._query_segment_rows([a, b], ["COALESCE(hidden, 0) = 0"], [], 3)
    assert [r[0][0] for r in rows] == ["2026-04-01", "2026-03-01", "2026-02-01"]
    assert [Path(d).name for _, d in rows] == ["b", "a", "b"]


def test_a_corrupt_db_is_skipped(tmp_path):
    good = _db(tmp_path / "good", ["2026-01-01"])
    bad = tmp_path / "bad"
    bad.mkdir()
    (bad / "metadata.db").write_bytes(b"this is not a database")
    rows = fb._query_segment_rows([bad / "metadata.db", good], ["COALESCE(hidden, 0) = 0"], [], 10)
    assert len(rows) == 1

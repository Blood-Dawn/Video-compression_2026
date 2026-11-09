"""Pins the helpers taken out of the /api/start handler."""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.routes import pipeline_bp as bp  # noqa: E402


@pytest.mark.parametrize("raw,expected", [("0", 0), ("3", 3), ("  7  ", 7), (None, 0)])
def test_digit_strings_are_camera_indexes(raw, expected):
    data = {} if raw is None else {"input_source": raw}
    assert bp._parse_input_source(data) == (expected, None)


def test_paths_and_urls_are_returned_stripped():
    assert bp._parse_input_source({"input_source": " clip.mp4 "}) == ("clip.mp4", None)
    assert bp._parse_input_source({"input_source": "rtsp://10.0.0.5/s"}) == ("rtsp://10.0.0.5/s", None)


@pytest.mark.parametrize("bad", ["file:///etc/passwd", "http://169.254.169.254/latest"])
def test_unsafe_sources_are_refused_with_the_guard_reason(bad):
    value, error = bp._parse_input_source({"input_source": bad})
    assert value is None and error.startswith("input_source not allowed: ")


def test_encrypt_off_needs_no_credential():
    assert bp._validate_encrypt_inputs({}) == (None, None)
    assert bp._validate_encrypt_inputs({"encrypt": False, "encrypt_password": " "}) == (None, None)


def test_encrypt_without_a_credential_is_refused():
    key, error = bp._validate_encrypt_inputs({"encrypt": True})
    assert key is None and "encrypt requires encrypt_password or encrypt_key_file" in error


def test_encrypt_with_a_password_is_accepted():
    assert bp._validate_encrypt_inputs({"encrypt": True, "encrypt_password": "pw"}) == (None, None)


def test_key_file_must_exist_and_be_a_file(tmp_path):
    missing = tmp_path / "nope.key"
    key, error = bp._validate_encrypt_inputs({"encrypt_key_file": str(missing)})
    assert key is None and error.startswith("encrypt_key_file not found: ")
    key, error = bp._validate_encrypt_inputs({"encrypt_key_file": str(tmp_path)})
    assert key is None and error == "encrypt_key_file must be a regular file"


def test_good_key_file_comes_back_resolved(tmp_path):
    kf = tmp_path / "k.key"
    kf.write_text("x")
    key, error = bp._validate_encrypt_inputs({"encrypt": True, "encrypt_key_file": str(kf)})
    assert error is None and key == str(kf.resolve())


def test_config_defaults_and_live_segment_length():
    cfg = bp._build_start_config({}, "cam_00", "clip.mp4", "out", None)
    assert cfg["segment_seconds"] == 60 and cfg["mode"] == "mode0" and cfg["codec"] == "auto"
    assert cfg["crf"] is None and cfg["background_crf"] is None and cfg["target_vmaf"] is None
    assert cfg["gop_seconds"] == 20 and cfg["max_bitrate_kbps"] == 0
    for live in (0, "rtsp://cam/1", "https://host/stream.m3u8"):
        assert bp._build_start_config({}, "c", live, "out", None)["segment_seconds"] == 600
    assert bp._build_start_config({"segment_seconds": 15}, "c", 0, "out", None)["segment_seconds"] == 15


def test_config_clamps_and_normalizes():
    cfg = bp._build_start_config(
        {"max_bitrate_kbps": 99999999, "gop_seconds": -5, "denoise": "HQDN3D", "crf": "30",
         "background_crf": "45", "preset": "  ", "target_vmaf": 5}, "c", "clip.mp4", "out", None)
    assert cfg["max_bitrate_kbps"] == 200000 and cfg["gop_seconds"] == 0
    assert cfg["denoise"] == "hqdn3d" and cfg["crf"] == 30 and cfg["background_crf"] == 45
    assert cfg["preset"] is None
    assert cfg["target_vmaf"] is not None and cfg["target_vmaf"] >= bp._TARGET_VMAF_MIN


def test_bad_integers_still_raise_as_before():
    with pytest.raises(ValueError):
        bp._build_start_config({"crf": "abc"}, "c", "clip.mp4", "out", None)
    with pytest.raises(ValueError):
        bp._build_start_config({"enhance_every_n": "x"}, "c", "clip.mp4", "out", None)

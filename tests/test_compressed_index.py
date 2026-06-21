"""
tests/test_compressed_index.py

Tests the already-compressed index (R3.1a).

Covers the record + is_compressed round-trip, classification of originals vs
compressed outputs (by the compressed/ location and by recorded output), and
that the signature changes when a file at the same path is replaced (so a
re-saved clip is treated as new). The index file is isolated to a tmp path.

Author: Bloodawn (KheivenD), 2026-06-05 (R3.1a).
"""

import sys
import time
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from utils import compressed_index as ci  # noqa: E402


@pytest.fixture()
def idx(tmp_path):
    return tmp_path / "compressed_index.json"


def _mkfile(p: Path, data: bytes = b"x" * 100):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_record_and_is_compressed_round_trip(tmp_path, idx):
    src = _mkfile(tmp_path / "src.mp4")
    out = _mkfile(tmp_path / "compressed" / "src.mp4", b"y" * 40)
    assert ci.is_compressed(src, index_path=idx) is False
    entry = ci.record(src, out, preset="continuous_cctv", mode="mode0", index_path=idx)
    assert entry["preset"] == "continuous_cctv" and entry["mode"] == "mode0"
    assert ci.is_compressed(src, index_path=idx) is True
    looked = ci.lookup(src, index_path=idx)
    assert looked and looked["output"] == str(out.resolve())


def test_is_compressed_false_when_output_missing(tmp_path, idx):
    src = _mkfile(tmp_path / "s.mp4")
    out = tmp_path / "compressed" / "s.mp4"   # recorded but never created
    ci.record(src, out, index_path=idx)
    assert ci.is_compressed(src, index_path=idx) is False


def test_signature_changes_when_file_replaced(tmp_path, idx):
    src = _mkfile(tmp_path / "s.mp4", b"a" * 100)
    out = _mkfile(tmp_path / "compressed" / "s.mp4")
    ci.record(src, out, index_path=idx)
    assert ci.is_compressed(src, index_path=idx) is True
    sig_before = ci.signature(src)
    # Replace the file at the same path with different content (and bump mtime).
    time.sleep(0.01)
    _mkfile(tmp_path / "s.mp4", b"b" * 250)
    import os
    os.utime(src, (time.time() + 5, time.time() + 5))
    assert ci.signature(src) != sig_before
    # The old entry no longer matches the new signature -> treated as new.
    assert ci.is_compressed(src, index_path=idx) is False
    assert ci.lookup(src, index_path=idx) is None


def test_classify_by_compressed_folder(tmp_path, idx):
    original = _mkfile(tmp_path / "vids" / "a.mp4")
    comp = _mkfile(tmp_path / "out" / "compressed" / "a.mp4")
    assert ci.classify(original, index_path=idx) == "original"
    assert ci.classify(comp, index_path=idx) == "compressed"


def test_classify_by_recorded_output(tmp_path, idx):
    src = _mkfile(tmp_path / "src.mp4")
    # An output NOT under a compressed/ folder, but recorded as an output.
    out = _mkfile(tmp_path / "elsewhere" / "out.mp4")
    assert ci.classify(out, index_path=idx) == "original"
    ci.record(src, out, index_path=idx)
    assert ci.classify(out, index_path=idx) == "compressed"


def test_compressed_subdir_created(tmp_path):
    d = ci.compressed_subdir(tmp_path / "out")
    assert d == (tmp_path / "out" / "compressed")
    assert d.is_dir()


def test_index_uses_app_data_by_default(monkeypatch, tmp_path):
    # Default index path comes from paths.state_file (no index_path passed).
    monkeypatch.setattr(ci._paths, "state_file",
                        lambda name: tmp_path / name)
    src = _mkfile(tmp_path / "d.mp4")
    out = _mkfile(tmp_path / "compressed" / "d.mp4")
    ci.record(src, out)
    assert (tmp_path / ci.INDEX_FILENAME).is_file()
    assert ci.is_compressed(src) is True

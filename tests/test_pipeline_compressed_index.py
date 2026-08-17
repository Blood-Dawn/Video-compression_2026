"""
tests/test_pipeline_compressed_index.py - file-input pipeline runs register
their output in the compressed index (M4 follow-up, 2026-08-16).

A compress started from the dashboard or the phone goes through /api/start ->
_run_pipeline_thread, which never recorded its output in the compressed index,
so the Library's COMPRESSED view did not show a clip the user just compressed.
_record_compressed_outputs pairs the newest verified camera_id-prefixed output
with the source file.

Author: Bloodawn (KheivenD), 2026-08-16 (M4 follow-up).
"""

import sys
import time
import types
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import pipeline_runner as pr  # noqa: E402
from utils import compressed_index as cidx  # noqa: E402


@pytest.fixture()
def fake_probe_ok(monkeypatch):
    """ffprobe always reports a decodable video stream."""
    def _fake_run(*a, **kw):
        return types.SimpleNamespace(returncode=0, stdout="video\n", stderr="")
    monkeypatch.setattr(pr.subprocess, "run", _fake_run)


def _setup_run(tmp_path, cam="mobile"):
    src = tmp_path / "watch" / "clip.mp4"
    src.parent.mkdir(parents=True)
    src.write_bytes(b"src" * 100)
    out_dir = tmp_path / "outdir"
    out_dir.mkdir()
    output = out_dir / f"{cam}_20260816T000000Z.mp4"
    output.write_bytes(b"out" * 500)
    config = {"input_source": str(src), "output_dir": str(out_dir),
              "camera_id": cam, "mode": "mode1"}
    with pr._state_lock:
        pr._status["start_time"] = time.time() - 5
    return src, output, config


def test_file_input_output_is_recorded(tmp_path, monkeypatch, fake_probe_ok):
    idx = tmp_path / "index.json"
    src, output, config = _setup_run(tmp_path)
    recorded = {}
    real_record = cidx.record

    def _spy(source, out, **kw):
        recorded["pair"] = (str(Path(source).resolve()), str(Path(out).resolve()))
        return real_record(source, out, index_path=idx, **kw)
    monkeypatch.setattr(cidx, "record", _spy)

    pr._record_compressed_outputs(config)
    assert recorded["pair"] == (str(src.resolve()), str(output.resolve()))
    # And the classification flips for the recorded output.
    assert cidx.classify(output, index_path=idx) == "compressed"
    assert cidx.is_compressed(src, index_path=idx) is True


def test_webcam_input_records_nothing(tmp_path, monkeypatch, fake_probe_ok):
    _, _, config = _setup_run(tmp_path)
    config["input_source"] = "0"  # webcam index: no source file to pair
    called = []
    monkeypatch.setattr(cidx, "record", lambda *a, **k: called.append(a))
    pr._record_compressed_outputs(config)
    assert called == []


def test_unverified_output_is_not_recorded(tmp_path, monkeypatch):
    _, _, config = _setup_run(tmp_path)

    def _fake_run(*a, **kw):
        return types.SimpleNamespace(returncode=1, stdout="", stderr="broken")
    monkeypatch.setattr(pr.subprocess, "run", _fake_run)
    called = []
    monkeypatch.setattr(cidx, "record", lambda *a, **k: called.append(a))
    pr._record_compressed_outputs(config)
    assert called == []


def test_never_raises_on_garbage_config():
    pr._record_compressed_outputs({})
    pr._record_compressed_outputs({"input_source": 0})
    pr._record_compressed_outputs({"input_source": "C:/does/not/exist.mp4",
                                   "output_dir": "C:/nor/this"})

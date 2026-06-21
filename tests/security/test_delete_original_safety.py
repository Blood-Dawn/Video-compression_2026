"""
tests/security/test_delete_original_safety.py  (SEC-011, SEC-012, SEC-007)

The delete-original-after-compress feature can destroy the only copy of footage,
so attack its safety gates:
  * SEC-011: an interrupted (stopped mid-encode) run must NEVER record a
    partial-but-decodable output or delete the original.
  * SEC-012: a concurrent/leftover file in compressed/ that is not THIS source's
    output (wrong camera_id) must not be attributed as its output (and gate a
    delete).
  * SEC-007: the audio-mux subprocess must run with a timeout so a crafted clip
    cannot hang the encode worker.
The happy path (a real, verified output) must still record + delete when opted in.
"""

import inspect
import sys
import threading
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import gui.services.autocompress_runner as ac  # noqa: E402
from utils import compressed_index as cidx  # noqa: E402


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    monkeypatch.setattr(cidx._paths, "state_file", lambda name: tmp_path / name)
    try:
        from gui.services import gui_state_persist as gsp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.services import gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")
    # Trust a non-empty file as a "valid" output for these logic tests.
    monkeypatch.setattr(ac, "_verify_output",
                        lambda p: Path(p).is_file() and Path(p).stat().st_size > 0)
    return tmp_path


def _mkvid(p: Path, data: bytes = b"v" * 500) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def test_stop_mid_encode_keeps_original(iso, monkeypatch):
    watch, out = iso / "watch", iso / "out"
    src = _mkvid(watch / "clip.mp4")
    stop = threading.Event()

    def fake_pipeline(input_source, camera_id, output_dir, **kw):
        # Write a partial-but-nonempty (decodable-looking) output, then signal a
        # stop, exactly as a daemon shutdown mid-encode would.
        d = Path(output_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{camera_id}.mp4").write_bytes(b"partial-but-passes-verify")
        (kw.get("stop_event") or stop).set()

    monkeypatch.setattr(ac, "run_pipeline", fake_pipeline)
    res = ac._process_one(src, str(out), "mode0", None, True, watch.resolve(), stop_event=stop)

    assert res is None
    assert src.exists(), "SEC-011: original deleted on an interrupted encode"
    assert cidx.is_compressed(src) is False, "SEC-011: partial output was recorded"
    assert (watch / "clip.mp4.processing").exists(), "interrupted run should leave a retry marker"


def test_leftover_file_not_attributed_as_output(iso, monkeypatch):
    watch, out = iso / "watch", iso / "out"
    src = _mkvid(watch / "clip.mp4")

    def fake_pipeline(input_source, camera_id, output_dir, **kw):
        # A concurrent/leftover file with a DIFFERENT name appears in compressed/.
        d = Path(output_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / "someone_elses_file.mp4").write_bytes(b"not this source's output")

    monkeypatch.setattr(ac, "run_pipeline", fake_pipeline)
    res = ac._process_one(src, str(out), "mode0", None, True, watch.resolve())

    assert res is None, "SEC-012: a non-matching leftover was attributed as the output"
    assert src.exists(), "SEC-012: original deleted on a mis-attributed output"
    assert cidx.is_compressed(src) is False


def test_real_output_is_attributed_and_deletes_when_opted_in(iso, monkeypatch):
    watch, out = iso / "watch", iso / "out"
    src = _mkvid(watch / "clip.mp4")

    def fake_pipeline(input_source, camera_id, output_dir, **kw):
        d = Path(output_dir)
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{camera_id}_20260101T000000Z.mp4").write_bytes(b"the real compressed output")

    monkeypatch.setattr(ac, "run_pipeline", fake_pipeline)
    res = ac._process_one(src, str(out), "mode0", None, True, watch.resolve())

    assert res is not None, "a verified, correctly-named output should be recorded"
    assert not src.exists(), "delete-original ON should remove the source after a verified compress"
    assert Path(res["output"]).is_file()


def test_audio_mux_runs_with_timeout():
    import compression.roi_encoder as roi
    src = inspect.getsource(roi)
    assert "timeout=300" in src, "SEC-007: audio-mux subprocess.run lost its timeout"

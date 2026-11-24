"""Pipeline job history records real byte counts.

Author: Bloodawn (KheivenD), 2026-11-24.
"""
import os
import time

from src.gui.services import job_history
from src.gui.services import pipeline_runner as pr


def test_job_records_source_and_output_bytes(tmp_path, monkeypatch):
    src = tmp_path / "in.mp4"
    src.write_bytes(b"x" * 1000)
    out = tmp_path / "out"
    out.mkdir()
    started = time.time() - 1
    (out / "seg.mp4").write_bytes(b"y" * 300)
    seen = {}
    monkeypatch.setattr(job_history, "record_job", lambda *a, **k: seen.update(k))
    try:
        from gui.services import job_history as alt
        monkeypatch.setattr(alt, "record_job", lambda *a, **k: seen.update(k))
    except ModuleNotFoundError:
        pass
    pr._record_job_history({"input_source": str(src), "output_dir": str(out), "mode": "mode1"},
                           None, started, None, 10, 1)
    assert seen["bytes_in"] == 1000
    assert seen["bytes_out"] == 300
    assert [os.path.basename(o) for o in seen["outputs"]] == ["seg.mp4"]

"""A run that finishes with no clips says why, instead of a bare 'complete' (issue #18)."""

import threading
from pathlib import Path

from gui.services import job_history, pipeline_runner

ROOT = Path(__file__).parent.parent


def test_no_note_when_clips_were_written():
    assert pipeline_runner.no_output_note("completed", 900, 3) is None


def test_no_target_run_explains_modes():
    note = pipeline_runner.no_output_note("completed", 1099, 0)
    assert note == pipeline_runner.NO_CLIPS_NOTE
    assert "moving target" in note and "Mode 0" in note


def test_unreadable_source_gets_its_own_note():
    note = pipeline_runner.no_output_note("completed", 0, 0)
    assert note == pipeline_runner.NO_FRAMES_NOTE


def test_stopped_and_failed_runs_get_no_note():
    assert pipeline_runner.no_output_note("stopped", 10, 0) is None
    assert pipeline_runner.no_output_note("error", 10, 0) is None


def test_history_entry_carries_the_note(monkeypatch):
    seen = {}
    monkeypatch.setattr(job_history, "record_job", lambda *a, **kw: seen.update(kw))
    pipeline_runner._record_job_history(
        {"input_source": "clip.mp4", "mode": "mode2"},
        threading.Event(),
        None,
        None,
        1099,
        0,
    )
    assert seen["counts"]["note"] == pipeline_runner.NO_CLIPS_NOTE
    assert seen["status"] == "completed"


def test_summary_modal_shows_the_reason():
    js = (ROOT / "src" / "gui" / "static" / "js" / "ui.js").read_text(encoding="utf-8")
    assert "JOB COMPLETE, NO OUTPUT" in js
    assert "'Why no output'" in js

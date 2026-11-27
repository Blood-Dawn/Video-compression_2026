"""
tests/test_live_clips.py

Finished clips are listed in /api/status while a run is still going, so the
dashboard can play them. Encrypted clips are left out (a browser cannot play
them) and the list keeps only the newest 20.

Author: Bloodawn (KheivenD), 2026-11-27.
"""
from gui.services import pipeline_runner as runner
from gui.state import _state_lock, _status


class _Enc:
    encryption_failures = 0

    def __init__(self, paths):
        self._paths = list(paths)

    def finish_segment(self, *a, **k):
        return {"file_path": self._paths.pop(0)}


def _reset():
    with _state_lock:
        _status["segment_count"] = 0
        _status["segment_files"] = []


def test_finished_clips_are_listed_and_encrypted_ones_skipped():
    _reset()
    enc = runner._patch_encoder(_Enc(["/o/a.mp4", "/o/b.mp4.enc", "/o/c.mp4"]))
    for _ in range(3):
        enc.finish_segment()
    with _state_lock:
        assert _status["segment_count"] == 3
        assert _status["segment_files"] == ["/o/a.mp4", "/o/c.mp4"]
    _reset()


def test_only_the_newest_twenty_are_kept():
    _reset()
    paths = ["/o/%02d.mp4" % i for i in range(25)]
    enc = runner._patch_encoder(_Enc(paths))
    for _ in range(25):
        enc.finish_segment()
    with _state_lock:
        assert len(_status["segment_files"]) == 20
        assert _status["segment_files"][-1] == "/o/24.mp4"
    _reset()


def test_status_route_exposes_the_list():
    from gui.app import app

    _reset()
    with _state_lock:
        _status["segment_files"] = ["/o/a.mp4"]
    body = app.test_client().get("/api/status").get_json()
    assert body["segment_files"] == ["/o/a.mp4"]
    _reset()

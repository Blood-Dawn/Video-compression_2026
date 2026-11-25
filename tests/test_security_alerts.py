"""
tests/test_security_alerts.py

Security cam alerts say what was seen, and only for clips from the phone.

Author: Bloodawn (KheivenD), 2026-11-25.
"""
import json
import sqlite3
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import security_alerts as sa  # noqa: E402


@pytest.fixture()
def state(tmp_path, monkeypatch):
    f = tmp_path / "alerts.json"
    monkeypatch.setattr(sa, "_file", lambda: f)
    sent = []
    from utils import push_notify
    monkeypatch.setattr(push_notify, "publish",
                        lambda title, message, tags="", priority="", cfg=None: sent.append((title, message, tags)) or True)
    return f, sent


def test_titles():
    assert sa.title_for(["person"], "mode0") == "Person detected"
    assert sa.title_for(["vehicle"], "mode2") == "Vehicle detected"
    assert sa.title_for(["person", "vehicle"], "mode1") == "Person and vehicle detected"
    assert sa.title_for(["dog"], "mode0") == "Dog detected"
    assert sa.title_for([], "mode3") == "Motion detected"
    assert sa.title_for([], "mode0") is None          # mode 0 records everything


def _clip_with_labels(tmp_path, labels_json, person, vehicle):
    out_dir = tmp_path / "compressed"
    out_dir.mkdir()
    out = out_dir / "cam_1.mp4"
    out.write_bytes(b"x" * 10)
    conn = sqlite3.connect(out_dir / "metadata.db")
    conn.execute("CREATE TABLE segments (id INTEGER PRIMARY KEY, file_path TEXT, object_classes TEXT,"
                 " person_count INTEGER, vehicle_count INTEGER)")
    conn.execute("INSERT INTO segments (file_path, object_classes, person_count, vehicle_count) VALUES (?,?,?,?)",
                 (str(out), labels_json, person, vehicle))
    conn.commit()
    conn.close()
    return out


def test_phone_clip_with_a_person_raises_one_alert_and_one_push(tmp_path, state):
    f, sent = state
    phone = tmp_path / "phone"
    phone.mkdir()
    out = _clip_with_labels(tmp_path, '["person"]', 1, 0)
    rec = {"source": str(phone / "clip_001.mp4"), "output": str(out), "mode": "mode1", "when": 1795642817.0}
    alert = sa.maybe_alert(rec, phone)
    assert alert["title"] == "Person detected" and alert["labels"] == ["person"]
    assert sent == [("Security cam: Person detected", "clip_001.mp4", "bust_in_silhouette")]
    rows = sa.recent_alerts()
    assert rows[0]["name"] == "clip_001.mp4" and rows[0]["thumb"].startswith("/api/library/thumb?path=")
    assert json.loads(f.read_text())[0]["output"] == str(out)


def test_clips_from_other_folders_are_ignored(tmp_path, state):
    f, sent = state
    phone, other = tmp_path / "phone", tmp_path / "other"
    phone.mkdir(); other.mkdir()
    out = _clip_with_labels(tmp_path, '["person"]', 1, 0)
    rec = {"source": str(other / "clip.mp4"), "output": str(out), "mode": "mode1"}
    assert sa.maybe_alert(rec, phone) is None
    assert sent == [] and sa.recent_alerts() == []


def test_mode0_without_labels_stays_quiet(tmp_path, state):
    f, sent = state
    phone = tmp_path / "phone"
    phone.mkdir()
    out = _clip_with_labels(tmp_path, "[]", 0, 0)
    rec = {"source": str(phone / "c.mp4"), "output": str(out), "mode": "mode0"}
    assert sa.maybe_alert(rec, phone) is None and sent == []


def test_alert_list_is_capped(tmp_path, state):
    f, sent = state
    for i in range(60):
        sa.record_alert({"when": float(i), "name": f"c{i}.mp4", "output": "", "labels": [], "title": "Motion detected"}, push=False)
    assert len(json.loads(f.read_text())) == sa.MAX_ALERTS
    assert sa.recent_alerts(limit=3)[0]["name"] == "c59.mp4"

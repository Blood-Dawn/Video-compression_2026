"""Opt-in benchmark: how fast does each mode compress compared with playback?

Skipped unless SVCS_SPEED_CLIPS is set (semicolon separated video paths).
SVCS_SPEED_MODES picks the modes (default mode1,mode2,mode3). Results go to
the JSON file named by SVCS_SPEED_OUT. State files are isolated by conftest.

    set SVCS_SPEED_CLIPS=C:\\clips\\a.mp4;C:\\clips\\b.mp4
    set SVCS_SPEED_OUT=C:\\temp\\speed.json
    python -m pytest tests/test_speed_benchmark.py -s

Author: Bloodawn (KheivenD), 2026-11-25.
"""
import json
import os
import sys
import time
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

CLIPS = [c.strip() for c in os.environ.get("SVCS_SPEED_CLIPS", "").split(";") if c.strip()]
MODES = [m.strip() for m in os.environ.get("SVCS_SPEED_MODES", "mode1,mode2,mode3").split(",") if m.strip()]
OUT = os.environ.get("SVCS_SPEED_OUT", "").strip()

pytestmark = pytest.mark.skipif(not CLIPS, reason="set SVCS_SPEED_CLIPS to run the speed benchmark")


@pytest.fixture
def client():
    from gui.app import app as flask_app
    flask_app.config["TESTING"] = True
    with flask_app.test_client() as c:
        yield c


def _run_one(client, clip, mode, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    cfg = {"input_source": clip, "output_dir": str(out_dir), "mode": mode, "preset": "balanced"}
    for _ in range(20):
        r = client.post("/api/start", json=cfg)
        if r.status_code == 200:
            break
        time.sleep(2)
    assert r.status_code == 200, r.get_data(as_text=True)
    time.sleep(2)
    t0 = time.time()
    while client.get("/api/status").get_json().get("running"):
        time.sleep(2)
        assert time.time() - t0 < 4 * 3600
    jobs = client.get("/api/jobs/recent?limit=5").get_json().get("jobs", [])
    job = next((j for j in jobs if (j.get("counts") or {}).get("mode") == mode), jobs[0] if jobs else {})
    c = job.get("counts") or {}
    return {
        "clip": Path(clip).name, "mode": mode,
        "video_seconds": c.get("video_seconds"), "wall_seconds": c.get("wall_seconds"),
        "realtime_x": c.get("realtime_x"), "bytes_in": job.get("bytes_in"),
        "bytes_out": job.get("bytes_out"), "segments": c.get("segments"),
        "status": job.get("status"),
    }


def test_speed_benchmark(client, tmp_path):
    rows = []
    for clip in CLIPS:
        for mode in MODES:
            row = _run_one(client, clip, mode, tmp_path / (Path(clip).stem + "_" + mode))
            rows.append(row)
            print(row, flush=True)
            if OUT:
                Path(OUT).write_text(json.dumps(rows, indent=2), encoding="utf-8")
    assert rows and all(r["realtime_x"] for r in rows)

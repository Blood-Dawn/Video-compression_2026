"""
tests/test_empty_metadata_db.py

A metadata.db can exist before the pipeline has ever created its tables:
sqlite3.connect() makes an empty file for any path whose folder exists, and
Setup and the dev scripts create the output folder up front. The read-only
stats routes used to answer that state with a 500 ("no such table:
segments"), which the dashboard shows as an error on a fresh install. They
now report "nothing recorded yet", the same as when the file is missing.

Found 2026-09-24 when tests/test_end_to_end_smoke.py started failing once an
outputs/ folder existed in the checkout.

Author: Bloodawn (KheivenD), 2026-09-24 (cleanup sweep).
"""

import sqlite3
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import gui.app as gui_module  # noqa: E402


@pytest.fixture()
def empty_db_dir(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    sqlite3.connect(str(out / "metadata.db")).close()  # file exists, no tables
    return out


@pytest.fixture()
def client():
    gui_module.app.config["TESTING"] = True
    return gui_module.app.test_client()


def test_storage_reports_unavailable_not_500(client, empty_db_dir, monkeypatch):
    monkeypatch.setitem(gui_module._status, "config", {"output_dir": str(empty_db_dir)})
    r = client.get("/api/storage")
    assert r.status_code == 200
    assert r.get_json() == {"available": False}


@pytest.mark.parametrize("route,key", [
    ("/api/daily_summary", "rows"),
    ("/api/busiest", "segments"),
    ("/api/query_segments?object_type=person", "segments"),
])
def test_archive_queries_return_empty_not_500(client, empty_db_dir, route, key):
    sep = "&" if "?" in route else "?"
    r = client.get(f"{route}{sep}archive_dir={empty_db_dir}")
    assert r.status_code == 200, r.get_json()
    assert r.get_json()[key] == []


def test_other_db_errors_still_surface(client, tmp_path, monkeypatch):
    # A corrupt file is a real problem and must not be hidden as "empty".
    out = tmp_path / "out"
    out.mkdir()
    (out / "metadata.db").write_bytes(b"this is not a sqlite database at all" * 10)
    monkeypatch.setitem(gui_module._status, "config", {"output_dir": str(out)})
    r = client.get("/api/storage")
    assert r.status_code == 500


def test_encrypting_before_any_job_does_not_create_an_empty_db(client, tmp_path, monkeypatch):
    """The encrypt route's DB bookkeeping used to open metadata.db in the output
    folder unconditionally, which is what created the empty database above
    (found through tests/security/test_encrypt_confinement.py, which left one
    in the repo's own outputs/ folder)."""
    import gui.routes.encryption_bp as eb
    if not eb._CRYPTO_AVAILABLE:
        pytest.skip("cryptography not installed")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    out = tmp_path / "out"
    out.mkdir()
    monkeypatch.setattr(eb, "_safe_segment_roots", lambda: [allowed.resolve()])
    monkeypatch.setitem(gui_module._status, "config", {"output_dir": str(out)})
    src = allowed / "clip.mp4"
    src.write_bytes(b"z" * 256)
    r = client.post("/api/encrypt", json={"file_path": str(src), "password": "pw"})
    assert r.status_code == 200, r.get_json()
    assert not (out / "metadata.db").exists()

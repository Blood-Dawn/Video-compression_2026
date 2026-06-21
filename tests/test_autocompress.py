"""
tests/test_autocompress.py

Tests for the auto-compress service (R3.1b runner + blueprint).

These cover the auto-compress LOGIC with the encode step stubbed out (a fake
run_pipeline writes a placeholder output, and ffprobe verification is stubbed
True) so they are fast and need no ffmpeg: the skip/dedup rules, output landing
under ``compressed/`` with an index record, the opt-in delete-original safety
gates, and the HTTP endpoints. The end-to-end LIVE-SAVE behaviour with a real
clip (real run_pipeline + ffprobe) is added in R3.1e.

Author: Bloodawn (KheivenD), 2026-06-06 (R3.1b - auto-compress).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import autocompress_runner as ac  # noqa: E402
from utils import compressed_index as cidx  # noqa: E402


def _mkvid(p: Path, data: bytes = b"v" * 500) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


@pytest.fixture()
def iso(tmp_path, monkeypatch):
    """Isolate the index + persistence, and stub the encode + verify steps.

    The fake run_pipeline writes ``<output_dir>/<camera_id>.mp4`` (a unique name
    per source, since the camera id derives from the file stem) so the runner's
    snapshot-diff sees a brand-new output for each clip.
    """
    # Index and gui-state both isolated to tmp.
    monkeypatch.setattr(cidx._paths, "state_file", lambda name: tmp_path / name)
    try:
        from gui.services import gui_state_persist as gsp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.services import gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")

    # Stub the encode: drop a placeholder file into the output (compressed) dir.
    def _fake_pipeline(input_source, camera_id, output_dir, **kw):
        out = Path(output_dir) / f"{camera_id}.mp4"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"compressed-bytes")
        return None

    monkeypatch.setattr(ac, "run_pipeline", _fake_pipeline)
    # Verification is exercised separately; here trust a non-empty file.
    monkeypatch.setattr(ac, "_verify_output", lambda p: Path(p).is_file() and Path(p).stat().st_size > 0)
    return tmp_path


def _scan(folder, out, **kw):
    # Fast stability check (no real settle wait) for the synthetic files.
    kw.setdefault("settle_seconds", 0.0)
    kw.setdefault("stable_checks", 1)
    return ac.scan_once(str(folder), str(out), **kw)


def test_compresses_into_compressed_subdir_and_records(iso):
    watch = iso / "watch"
    out = iso / "out"
    src = _mkvid(watch / "clip.mp4")
    done = _scan(watch, out)
    assert len(done) == 1
    comp_dir = out / "compressed"
    produced = list(comp_dir.glob("*.mp4"))
    assert produced, "an output should land under compressed/"
    # The source -> output mapping is recorded so Library can find it.
    assert cidx.is_compressed(src) is True
    assert done[0]["output"] == str(produced[0].resolve())


def test_dedup_second_scan_compresses_nothing(iso):
    watch = iso / "watch"
    out = iso / "out"
    _mkvid(watch / "clip.mp4")
    assert len(_scan(watch, out)) == 1
    # Second pass: the clip is already compressed -> skipped.
    assert len(_scan(watch, out)) == 0


def test_never_recompresses_its_own_output(iso):
    # When the watched folder IS the output base, the compressed/ subtree must
    # be ignored so outputs are never fed back in.
    base = iso / "base"
    src = _mkvid(base / "clip.mp4")
    first = _scan(base, base)        # output base == watch folder
    assert len(first) == 1
    # A second scan sees the compressed/ output but must not recompress it.
    assert len(_scan(base, base)) == 0


def test_delete_original_off_keeps_source(iso):
    watch = iso / "watch"
    out = iso / "out"
    src = _mkvid(watch / "clip.mp4")
    _scan(watch, out, delete_original=False)
    assert src.exists(), "with delete_original OFF the source is never touched"


def test_delete_original_on_removes_source_after_verified_output(iso):
    watch = iso / "watch"
    out = iso / "out"
    src = _mkvid(watch / "clip.mp4")
    done = _scan(watch, out, delete_original=True)
    assert len(done) == 1
    assert not src.exists(), "with delete_original ON a verified compress removes the source"
    # The output still exists.
    assert Path(done[0]["output"]).is_file()


def test_safe_delete_refuses_outside_watch_root(iso):
    watch = iso / "watch"
    out = iso / "out"
    comp = cidx.compressed_subdir(out)
    outsider = _mkvid(iso / "elsewhere" / "x.mp4")
    valid_output = _mkvid(comp / "x.mp4")
    # Source is NOT under the watch root -> refuse.
    assert ac._safe_delete_original(outsider, valid_output, comp, watch) is False
    assert outsider.exists()


def test_safe_delete_refuses_file_inside_compressed(iso):
    watch = iso / "watch"
    out = iso / "out"
    comp = cidx.compressed_subdir(out)
    inside = _mkvid(comp / "already.mp4")
    other_output = _mkvid(comp / "other.mp4")
    # A file living inside compressed/ must never be deleted as an "original".
    assert ac._safe_delete_original(inside, other_output, comp, watch) is False
    assert inside.exists()


def test_safe_delete_refuses_zero_byte_output(iso):
    watch = iso / "watch"
    out = iso / "out"
    comp = cidx.compressed_subdir(out)
    src = _mkvid(watch / "clip.mp4")
    empty = comp / "clip.mp4"
    empty.parent.mkdir(parents=True, exist_ok=True)
    empty.write_bytes(b"")          # zero-byte output
    assert ac._safe_delete_original(src, empty, comp, watch) is False
    assert src.exists()


# ── HTTP surface ──────────────────────────────────────────────────────────────

@pytest.fixture()
def client(iso, monkeypatch):
    # Point the blueprint's output base at tmp so scan_now never writes to the
    # real default output folder.
    try:
        from gui.routes import autocompress_bp as acbp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.routes import autocompress_bp as acbp
    monkeypatch.setattr(acbp, "_default_output_dir", lambda: str(iso / "out"))
    from gui.app import app
    return app.test_client()


def test_status_endpoint_reports_not_running(client):
    body = client.get("/api/autocompress/status").get_json()
    assert body["running"] is False
    assert "recent" in body and "queue" in body


def test_start_requires_existing_folder(client):
    assert client.post("/api/autocompress/start", json={}).status_code == 400
    assert client.post("/api/autocompress/start",
                       json={"folder": "Z:/nope/nope"}).status_code == 400


def test_scan_now_compresses_existing(client, iso):
    watch = iso / "watch"
    _mkvid(watch / "a.mp4")
    _mkvid(watch / "b.mp4")
    resp = client.post("/api/autocompress/scan_now", json={"folder": str(watch)})
    body = resp.get_json()
    assert resp.status_code == 200 and body["ok"] is True
    assert body["compressed"] == 2

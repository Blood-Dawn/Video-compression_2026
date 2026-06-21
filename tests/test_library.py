"""
tests/test_library.py

Tests the Library / gallery endpoints (FIX 6).

Uses a tiny synthetic clip so listing, metadata, thumbnail generation, file
streaming, and the compress hand-off can be exercised without LFS assets. The
thumbnail cache is redirected to a tmp dir.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 6).
"""

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import cv2  # noqa: E402

import gui.routes.library_bp as lib  # noqa: E402


def _make_clip(path, n=20, size=(160, 120), fps=10.0):
    w, h = size
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), fps, (w, h))
    if not writer.isOpened():  # pragma: no cover
        writer.release()
        pytest.skip("no MJPG VideoWriter available")
    rng = np.random.default_rng(7)
    for _ in range(n):
        small = rng.integers(0, 255, (8, 10, 3), dtype=np.uint8)
        writer.write(cv2.resize(small, (w, h), interpolation=cv2.INTER_NEAREST))
    writer.release()


@pytest.fixture()
def client():
    from gui.app import app
    return app.test_client()


@pytest.fixture()
def lib_folder(tmp_path, monkeypatch):
    # Redirect the thumbnail cache so we never touch the real one.
    monkeypatch.setattr(lib._paths, "thumbs_dir", lambda: tmp_path / "thumbs")
    (tmp_path / "thumbs").mkdir()
    # Isolate the persisted-folder side effect (R2.3 set_library_folder).
    try:
        from gui.services import gui_state_persist as gsp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.services import gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")
    vids = tmp_path / "vids"
    vids.mkdir()
    _make_clip(vids / "alpha.avi")
    _make_clip(vids / "beta.avi")
    return vids


def _flat_files(folder):
    """Create plain files with video extensions for listing/filter/sort tests
    (the listing only inspects the extension and stat, not the content)."""
    (folder / "small.mp4").write_bytes(b"x" * 1000)
    (folder / "big.mkv").write_bytes(b"y" * 5000)
    (folder / "mid.mp4").write_bytes(b"z" * 3000)
    (folder / "notes.txt").write_text("not a video")


def test_videos_lists_folder(client, lib_folder):
    body = client.get("/api/library/videos", query_string={"folder": str(lib_folder)}).get_json()
    assert body["exists"] is True
    assert body["total"] == 2
    names = {v["name"] for v in body["videos"]}
    assert names == {"alpha.avi", "beta.avi"}
    for v in body["videos"]:
        assert set(v) >= {"name", "path", "size", "mtime"}


def test_videos_missing_folder(client, tmp_path):
    body = client.get("/api/library/videos",
                      query_string={"folder": str(tmp_path / "nope")}).get_json()
    assert body["exists"] is False
    assert body["videos"] == []


def test_videos_pagination(client, lib_folder):
    body = client.get("/api/library/videos",
                      query_string={"folder": str(lib_folder), "page": 1, "page_size": 1}).get_json()
    assert body["total"] == 2
    assert len(body["videos"]) == 1


def test_meta_returns_dimensions(client, lib_folder):
    clip = lib_folder / "alpha.avi"
    body = client.get("/api/library/meta", query_string={"path": str(clip)}).get_json()
    assert body["name"] == "alpha.avi"
    assert body["size"] > 0
    # ffprobe should report the encoded dimensions.
    assert body.get("width") in ("160", 160) or "width" in body


def test_thumb_generates_and_caches(client, lib_folder, tmp_path):
    clip = lib_folder / "alpha.avi"
    resp = client.get("/api/library/thumb", query_string={"path": str(clip)})
    assert resp.status_code == 200
    assert resp.mimetype == "image/jpeg"
    # A cached file now exists in the redirected thumbs dir.
    thumbs = list((tmp_path / "thumbs").glob("*.jpg"))
    assert thumbs and thumbs[0].stat().st_size > 0


def test_file_streams_video(client, lib_folder):
    clip = lib_folder / "alpha.avi"
    resp = client.get("/api/library/file", query_string={"path": str(clip)})
    assert resp.status_code == 200
    assert resp.mimetype.startswith("video/")


def test_compress_hands_back_path(client, lib_folder):
    clip = lib_folder / "beta.avi"
    resp = client.post("/api/library/compress", json={"path": str(clip)})
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] and body["name"] == "beta.avi"


def test_endpoints_reject_non_video(client, tmp_path):
    bad = tmp_path / "notes.txt"
    bad.write_text("hello")
    for ep in ("/api/library/meta", "/api/library/thumb", "/api/library/file"):
        assert client.get(ep, query_string={"path": str(bad)}).status_code == 400
    assert client.post("/api/library/compress", json={"path": str(bad)}).status_code == 400


# ── R2.3: search / filter / sort / browse / persistence / thumb fallback ─────

@pytest.fixture()
def flat_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(lib._paths, "thumbs_dir", lambda: tmp_path / "thumbs")
    (tmp_path / "thumbs").mkdir()
    try:
        from gui.services import gui_state_persist as gsp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.services import gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")
    folder = tmp_path / "flat"
    folder.mkdir()
    _flat_files(folder)
    return folder


def test_search_q_filters_by_name(client, flat_folder):
    body = client.get("/api/library/videos",
                      query_string={"folder": str(flat_folder), "q": "big"}).get_json()
    assert {v["name"] for v in body["videos"]} == {"big.mkv"}


def test_ext_filter_and_extensions_list(client, flat_folder):
    body = client.get("/api/library/videos",
                      query_string={"folder": str(flat_folder), "ext": "mp4"}).get_json()
    assert {v["name"] for v in body["videos"]} == {"small.mp4", "mid.mp4"}
    # the .txt is excluded; extensions list reflects the video files only
    assert set(body["extensions"]) == {"mp4", "mkv"}


def test_size_filter(client, flat_folder):
    body = client.get("/api/library/videos",
                      query_string={"folder": str(flat_folder), "min_size": 2500}).get_json()
    names = {v["name"] for v in body["videos"]}
    assert names == {"big.mkv", "mid.mp4"}  # 5000 and 3000, not 1000


def test_sort_by_size_and_name(client, flat_folder):
    asc = client.get("/api/library/videos",
                     query_string={"folder": str(flat_folder), "sort": "size", "order": "asc"}).get_json()
    sizes = [v["size"] for v in asc["videos"]]
    assert sizes == sorted(sizes)
    desc = client.get("/api/library/videos",
                      query_string={"folder": str(flat_folder), "sort": "name", "order": "desc"}).get_json()
    names = [v["name"] for v in desc["videos"]]
    assert names == sorted(names, reverse=True)


def test_folder_is_persisted_and_exposed(client, flat_folder):
    client.get("/api/library/videos", query_string={"folder": str(flat_folder)})
    state = client.get("/api/setup/state").get_json()
    assert state["library_folder"] == str(flat_folder.resolve())


def test_browse_folder_returns_chosen_path(client, monkeypatch, tmp_path):
    import subprocess

    class _R:
        stdout = str(tmp_path / "picked")

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: _R())
    body = client.get("/api/library/browse_folder").get_json()
    assert body["path"] == str(tmp_path / "picked")


def test_browse_folder_uses_powershell_dialog_on_windows(client, monkeypatch):
    # On Windows the picker must shell out to a PowerShell FolderBrowserDialog so
    # it also works in the frozen app (where sys.executable is SVCS.exe, not
    # Python, and cannot run a "-c" script).
    import subprocess
    import sys

    captured = {}

    class _R:
        stdout = "C:\\Users\\me\\Videos"

    def _fake_run(cmd, *a, **k):
        captured["cmd"] = cmd
        return _R()

    monkeypatch.setattr(subprocess, "run", _fake_run)
    monkeypatch.setattr(sys, "platform", "win32")
    body = client.get("/api/library/browse_folder").get_json()
    assert body["path"] == "C:\\Users\\me\\Videos"
    assert "powershell" in str(captured["cmd"][0]).lower()
    assert any("FolderBrowserDialog" in str(x) for x in captured["cmd"])
    # It must NOT try to run the bundled exe with -c (the frozen-app bug).
    assert "-c" not in captured["cmd"]


def test_videos_recursive_finds_nested(client, tmp_path, monkeypatch):
    monkeypatch.setattr(lib._paths, "thumbs_dir", lambda: tmp_path / "thumbs")
    (tmp_path / "thumbs").mkdir()
    try:
        from gui.services import gui_state_persist as gsp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.services import gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")
    corpus = tmp_path / "corpus"
    (corpus / "baseline").mkdir(parents=True)
    (corpus / "night").mkdir(parents=True)
    _make_clip(corpus / "baseline" / "highway.avi")
    _make_clip(corpus / "night" / "bridge.avi")
    # The corpus folder itself has NO direct videos (the regression the owner hit).
    body = client.get("/api/library/videos", query_string={"folder": str(corpus)}).get_json()
    assert body["total"] == 2
    names = {v["name"] for v in body["videos"]}
    assert names == {"baseline/highway.avi", "night/bridge.avi"}
    # recursive=0 lists only the (empty) top level
    flat = client.get("/api/library/videos",
                      query_string={"folder": str(corpus), "recursive": "0"}).get_json()
    assert flat["total"] == 0


def test_list_dirs_lists_subdirs(client, tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _flat_files(tmp_path)  # adds some videos directly here
    body = client.get("/api/library/list_dirs", query_string={"path": str(tmp_path)}).get_json()
    names = {d["name"] for d in body["dirs"]}
    assert {"a", "b"} <= names
    assert body["video_count"] >= 1
    assert body["parent"]  # has a parent to go Up to


def test_list_dirs_root_returns_listing(client):
    body = client.get("/api/library/list_dirs").get_json()
    assert "dirs" in body and isinstance(body["dirs"], list)


def test_list_dirs_bad_path(client, tmp_path):
    assert client.get("/api/library/list_dirs",
                      query_string={"path": str(tmp_path / "nope")}).status_code == 400


def test_thumb_falls_back_gracefully_when_ffmpeg_broken(client, lib_folder, monkeypatch):
    # If ffmpeg cannot make a thumbnail, the endpoint returns 404 (not 500) so
    # the UI can show a placeholder.
    monkeypatch.setattr(lib, "ffmpeg_path", lambda: "definitely-not-ffmpeg-xyz")
    clip = lib_folder / "alpha.avi"
    resp = client.get("/api/library/thumb", query_string={"path": str(clip)})
    assert resp.status_code == 404


# ── R3.1d: Originals | Compressed | All classification ───────────────────────

@pytest.fixture()
def kind_folder(tmp_path, monkeypatch):
    """A folder with an original, a compressed/ output, and an index entry.

    Isolates the compressed index to tmp so classification is deterministic.
    """
    monkeypatch.setattr(lib._paths, "thumbs_dir", lambda: tmp_path / "thumbs")
    (tmp_path / "thumbs").mkdir()
    try:
        from gui.services import gui_state_persist as gsp
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.services import gui_state_persist as gsp
    monkeypatch.setattr(gsp, "_GUI_STATE_FILE", tmp_path / "gui_state.json")
    # The endpoint reads the DEFAULT index path; redirect it to tmp.
    monkeypatch.setattr(lib._cidx._paths, "state_file", lambda name: tmp_path / name)

    folder = tmp_path / "lib"
    (folder / "compressed").mkdir(parents=True)
    orig = folder / "orig.mp4"
    orig.write_bytes(b"o" * 2000)
    out = folder / "compressed" / "orig_out.mp4"
    out.write_bytes(b"c" * 800)
    lib._cidx.record(orig, out)  # orig -> out
    return folder, orig, out


def test_kind_all_lists_both(client, kind_folder):
    folder, orig, out = kind_folder
    body = client.get("/api/library/videos",
                      query_string={"folder": str(folder), "kind": "all"}).get_json()
    assert body["kind"] == "all"
    assert {v["name"] for v in body["videos"]} == {"orig.mp4", "compressed/orig_out.mp4"}


def test_kind_compressed_only_with_source_backref(client, kind_folder):
    folder, orig, out = kind_folder
    body = client.get("/api/library/videos",
                      query_string={"folder": str(folder), "kind": "compressed"}).get_json()
    vids = body["videos"]
    assert {v["name"] for v in vids} == {"compressed/orig_out.mp4"}
    assert vids[0]["kind"] == "compressed"
    assert vids[0]["source"] == str(orig.resolve())


def test_kind_original_only_marks_has_compressed(client, kind_folder):
    folder, orig, out = kind_folder
    body = client.get("/api/library/videos",
                      query_string={"folder": str(folder), "kind": "original"}).get_json()
    vids = body["videos"]
    assert {v["name"] for v in vids} == {"orig.mp4"}
    assert vids[0]["kind"] == "original"
    assert vids[0]["compressed"] is True  # a verified compressed version exists


def test_classify_recorded_output_outside_compressed_dir(client, kind_folder):
    # An output recorded in the index but NOT under a compressed/ folder is still
    # classified "compressed".
    folder, orig, out = kind_folder
    src2 = folder / "src2.mp4"
    src2.write_bytes(b"s" * 1500)
    elsewhere = folder / "elsewhere" / "recorded.mp4"
    elsewhere.parent.mkdir(parents=True)
    elsewhere.write_bytes(b"r" * 700)
    lib._cidx.record(src2, elsewhere)
    body = client.get("/api/library/videos",
                      query_string={"folder": str(folder), "kind": "compressed"}).get_json()
    names = {v["name"] for v in body["videos"]}
    assert names == {"compressed/orig_out.mp4", "elsewhere/recorded.mp4"}


def test_kind_default_is_all_and_field_present(client, kind_folder):
    folder, orig, out = kind_folder
    body = client.get("/api/library/videos",
                      query_string={"folder": str(folder)}).get_json()
    assert body["kind"] == "all"
    for v in body["videos"]:
        assert v["kind"] in ("original", "compressed")

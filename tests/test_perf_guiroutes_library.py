"""The scandir library walk lists the same files, in the same order, as rglob.

_walk_and_classify used Path.rglob("*") plus a resolve() per file; it now uses
os.scandir and resolves each folder once. The cap on the listing keeps the
first N files in walk order, so the order has to match, not just the set.

Author: Bloodawn (KheivenD), 2026-10-13 (perf sweep).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from gui.routes import library_bp as lib  # noqa: E402

LAYOUT = [
    "a.mp4", "B.MKV", ".mp4", "x.", "notes.txt",
    "cam1/seg1.mp4", "cam1/seg0.mp4", "cam1/deep/er/clip.mov",
    "HLS/playlist0.ts", "cam1/hls/p1.ts", "cam1/hlsx/keep.ts",
    "compressed/out.mp4", "zz/last.webm", "aa/first.avi",
]


def _rglob_reference(folder: Path, recursive: bool) -> list[str]:
    """The pre-scandir walk: rglob/iterdir order, hls/ subfolders skipped."""
    names = []
    walker = folder.rglob("*") if recursive else folder.iterdir()
    for f in walker:
        if not (f.is_file() and f.suffix.lower() in lib.VIDEO_EXTS):
            continue
        rel = f.relative_to(folder)
        if "hls" in {p.lower() for p in rel.parts[:-1]}:
            continue
        names.append(rel.as_posix())
    return names


def _make_tree(tmp_path: Path) -> Path:
    for rel in LAYOUT:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * len(rel))
    return tmp_path.resolve()


def test_recursive_walk_matches_rglob_order_and_skips_hls(tmp_path):
    folder = _make_tree(tmp_path)
    got = [i["name"] for i in lib._walk_and_classify(folder, True)["items"]]
    assert got == _rglob_reference(folder, True)
    assert "cam1/hlsx/keep.ts" in got
    assert not any("/p1.ts" in n or "playlist0" in n for n in got)


def test_top_level_walk_matches_iterdir(tmp_path):
    folder = _make_tree(tmp_path)
    got = [i["name"] for i in lib._walk_and_classify(folder, False)["items"]]
    assert got == _rglob_reference(folder, False)


def test_items_carry_size_path_and_classification(tmp_path):
    folder = _make_tree(tmp_path)
    items = {i["name"]: i for i in lib._walk_and_classify(folder, True)["items"]}
    clip = items["cam1/deep/er/clip.mov"]
    assert clip["size"] == len("cam1/deep/er/clip.mov")
    assert Path(clip["path"]) == folder / "cam1" / "deep" / "er" / "clip.mov"
    assert clip["kind"] == "original"
    assert items["compressed/out.mp4"]["kind"] == "compressed"
    assert all("_resolved" not in i for i in items.values())


def test_cap_keeps_the_first_files_in_walk_order(tmp_path, monkeypatch):
    folder = _make_tree(tmp_path)
    monkeypatch.setattr(lib, "_LIB_CACHE_CAP", 3)
    out = lib._walk_and_classify(folder, True)
    assert out["truncated"] is True
    assert [i["name"] for i in out["items"]] == _rglob_reference(folder, True)[:3]

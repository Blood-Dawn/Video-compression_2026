"""
tests/test_library_cache.py

M2.1a: cache the library folder walk.

/api/library/videos re-walked the entire folder tree on EVERY request, including
every page of one listing. Measured before the fix:

    100 files ->    45 ms        5,000 files -> 2,153 ms
    50x the files -> 47.8x the time, i.e. strictly linear

and since every page repeats it, paging costs O(pages * files). Projected onto a
real deployment (one camera writing 60s segments makes 1,440 a day) that is
~18.6 s per page at 30 days and ~74 s at four cameras.

That is not a mobile-only bug. The desktop Library tab calls the same endpoint,
so a user with a month of footage already had an 18 second Library. It surfaced
while sizing the phone LIBRARY tab, where infinite scroll multiplies it.

After the fix, at 5,000 files a page costs 3.3 ms instead of 2,153 ms.

The tests that matter most here are the CORRECTNESS ones, not the speed one.
The fix moved file classification from a per-request loop into the cached walk,
so the risk is that filters now read stale or wrong fields. Several tests below
exist purely to pin that the answers did not change.

Author: Bloodawn (KheivenD), 2026-07-19 (M2.1a).
"""

import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import app                          # noqa: E402
from gui.routes import library_bp as lib         # noqa: E402


@pytest.fixture(autouse=True)
def clean_cache():
    """Every test starts with an empty cache.

    Without this the cache is module-global and leaks across tests, so a test
    asserting a cold walk could silently get a warm hit from an earlier test
    and pass for the wrong reason.
    """
    lib._reset_library_cache()
    yield
    lib._reset_library_cache()


@pytest.fixture()
def client():
    app.config["TESTING"] = True
    return app.test_client()


def _make_tree(root: Path, n: int, per_dir: int = 50) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for i in range(n):
        d = root / f"cam_{i // per_dir:02d}"
        d.mkdir(exist_ok=True)
        (d / f"seg_{i:05d}.mp4").write_bytes(b"")
    return root


def _url(folder: Path, **kw) -> str:
    q = "&".join(f"{k}={v}" for k, v in kw.items())
    return f"/api/library/videos?folder={folder.as_posix()}" + (f"&{q}" if q else "")


# ── correctness: the cache must not change any answer ────────────────────────

def test_listing_matches_the_files_on_disk(client, tmp_path):
    root = _make_tree(tmp_path / "lib", 12)
    d = client.get(_url(root, page_size=200)).get_json()
    assert d["total"] == 12
    assert len(d["videos"]) == 12
    names = {v["name"] for v in d["videos"]}
    assert "cam_00/seg_00000.mp4" in names


def test_pagination_is_consistent_across_pages(client, tmp_path):
    """Page 2 must come from the same snapshot as page 1, with no overlap."""
    root = _make_tree(tmp_path / "lib", 30)
    p1 = client.get(_url(root, page=1, page_size=10)).get_json()
    p2 = client.get(_url(root, page=2, page_size=10)).get_json()
    p3 = client.get(_url(root, page=3, page_size=10)).get_json()
    assert p1["total"] == p2["total"] == p3["total"] == 30
    seen = [v["path"] for v in p1["videos"] + p2["videos"] + p3["videos"]]
    assert len(seen) == 30
    assert len(set(seen)) == 30, "pages overlapped or repeated an item"


def test_filters_still_work_against_the_cached_listing(client, tmp_path):
    """The whole point of the split: filters run per request, over the cache."""
    root = tmp_path / "lib"
    root.mkdir()
    (root / "alpha.mp4").write_bytes(b"x" * 100)
    (root / "beta.mp4").write_bytes(b"x" * 5000)
    (root / "gamma.mkv").write_bytes(b"x" * 100)

    all_d = client.get(_url(root, page_size=200)).get_json()
    assert all_d["total"] == 3

    # Same cached walk, three different filter results.
    q = client.get(_url(root, q="alph", page_size=200)).get_json()
    assert [v["name"] for v in q["videos"]] == ["alpha.mp4"]

    ext = client.get(_url(root, ext="mkv", page_size=200)).get_json()
    assert [v["name"] for v in ext["videos"]] == ["gamma.mkv"]

    big = client.get(_url(root, min_size=1000, page_size=200)).get_json()
    assert [v["name"] for v in big["videos"]] == ["beta.mp4"]


def test_sort_still_works_against_the_cached_listing(client, tmp_path):
    root = tmp_path / "lib"
    root.mkdir()
    (root / "b.mp4").write_bytes(b"x" * 300)
    (root / "a.mp4").write_bytes(b"x" * 100)
    (root / "c.mp4").write_bytes(b"x" * 200)

    asc = client.get(_url(root, sort="name", order="asc", page_size=200)).get_json()
    assert [v["name"] for v in asc["videos"]] == ["a.mp4", "b.mp4", "c.mp4"]

    by_size = client.get(_url(root, sort="size", order="desc", page_size=200)).get_json()
    assert [v["size"] for v in by_size["videos"]] == [300, 200, 100]


def test_every_item_still_carries_its_classification(client, tmp_path):
    """kind/compressed moved into the cached walk; they must still be present."""
    root = _make_tree(tmp_path / "lib", 4)
    d = client.get(_url(root, page_size=200)).get_json()
    for v in d["videos"]:
        assert v["kind"] in ("original", "compressed")
        if v["kind"] == "original":
            assert "compressed" in v, "originals must report whether a compressed copy exists"


def test_extensions_list_reflects_the_whole_folder_not_the_filtered_page(client, tmp_path):
    """Pre-existing behavior worth not regressing: the type dropdown shows every
    type present, independent of the active filter."""
    root = tmp_path / "lib"
    root.mkdir()
    (root / "a.mp4").write_bytes(b"")
    (root / "b.mkv").write_bytes(b"")
    d = client.get(_url(root, ext="mp4", page_size=200)).get_json()
    assert set(d["extensions"]) == {"mp4", "mkv"}
    assert len(d["videos"]) == 1


# ── the cache behaviour itself ───────────────────────────────────────────────

def test_second_request_is_served_from_cache(client, tmp_path):
    root = _make_tree(tmp_path / "lib", 300)
    t0 = time.perf_counter()
    client.get(_url(root, page=1, page_size=20))
    cold = time.perf_counter() - t0
    t0 = time.perf_counter()
    client.get(_url(root, page=2, page_size=20))
    warm = time.perf_counter() - t0
    assert warm < cold, f"page 2 ({warm*1000:.1f}ms) was not faster than page 1 ({cold*1000:.1f}ms)"


def test_a_new_file_appears_after_a_forced_refresh(client, tmp_path):
    """refresh=1 must give an exact answer, for the dashboard refresh button and
    for a client that has just finished compressing something."""
    root = _make_tree(tmp_path / "lib", 3)
    assert client.get(_url(root, page_size=200)).get_json()["total"] == 3
    (root / "cam_00" / "brand_new.mp4").write_bytes(b"")
    # Still cached, so the new file is not visible yet.
    assert client.get(_url(root, page_size=200)).get_json()["total"] == 3
    forced = client.get(_url(root, page_size=200, refresh=1)).get_json()
    assert forced["total"] == 4


def test_cache_expires_after_the_ttl(client, tmp_path, monkeypatch):
    root = _make_tree(tmp_path / "lib", 2)
    assert client.get(_url(root, page_size=200)).get_json()["total"] == 2
    (root / "cam_00" / "later.mp4").write_bytes(b"")

    real = time.monotonic
    monkeypatch.setattr(lib.time, "monotonic",
                        lambda: real() + lib._LIB_CACHE_TTL_S + 1)
    assert client.get(_url(root, page_size=200)).get_json()["total"] == 3, (
        "the listing did not refresh after the TTL elapsed")


def test_different_folders_do_not_share_a_cache_entry(client, tmp_path):
    a = _make_tree(tmp_path / "a", 2)
    b = _make_tree(tmp_path / "b", 5)
    assert client.get(_url(a, page_size=200)).get_json()["total"] == 2
    assert client.get(_url(b, page_size=200)).get_json()["total"] == 5
    assert client.get(_url(a, page_size=200)).get_json()["total"] == 2


def test_recursive_flag_is_part_of_the_cache_key(client, tmp_path):
    """recursive=0 and recursive=1 are different listings of the same folder and
    must not be served from one another's cache."""
    root = _make_tree(tmp_path / "lib", 6, per_dir=3)   # nested in subfolders
    deep = client.get(_url(root, page_size=200, recursive=1)).get_json()
    flat = client.get(_url(root, page_size=200, recursive=0)).get_json()
    assert deep["total"] == 6
    assert flat["total"] == 0, "recursive=0 should not see nested files"


def test_cache_table_is_bounded(client, tmp_path):
    """A user browsing many folders must not grow the cache without limit."""
    for i in range(lib._LIB_CACHE_MAX_FOLDERS + 3):
        f = _make_tree(tmp_path / f"lib{i}", 2)
        client.get(_url(f, page_size=200))
    assert len(lib._lib_cache) <= lib._LIB_CACHE_MAX_FOLDERS, (
        f"cache holds {len(lib._lib_cache)} folders, bound is "
        f"{lib._LIB_CACHE_MAX_FOLDERS}")


def test_missing_folder_still_reports_cleanly(client, tmp_path):
    missing = tmp_path / "does_not_exist"
    d = client.get(_url(missing, page_size=200)).get_json()
    assert d["exists"] is False
    assert d["total"] == 0


def test_truncation_flag_survives_the_cache(client, tmp_path):
    """The 5000 cap predates this change and must still be reported, or a client
    silently believes it has seen every clip."""
    lib._reset_library_cache()
    monkey_cap = 5
    original = lib._LIB_CACHE_CAP
    try:
        lib._LIB_CACHE_CAP = monkey_cap
        root = _make_tree(tmp_path / "lib", 20)
        d = client.get(_url(root, page_size=200)).get_json()
        assert d["truncated"] is True
        assert d["total"] == monkey_cap
    finally:
        lib._LIB_CACHE_CAP = original

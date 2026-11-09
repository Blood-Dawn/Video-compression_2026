"""Pins the filter and sort helpers taken out of /api/library/videos."""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.routes import library_bp as lb  # noqa: E402


def _item(name, size, mtime, kind="original", ext=None, **extra):
    d = {"name": name, "path": f"/v/{name}", "size": size, "mtime": mtime, "kind": kind,
         "_ext": ext or Path(name).suffix.lower(), "_resolved": "private"}
    d.update(extra)
    return d


ITEMS = [
    _item("a.mp4", 1000, 10, compressed=True),
    _item("B.mkv", 5000, 30),
    _item("c.avi", 300, 20),
    _item("a_comp.mp4", 400, 40, kind="compressed", source="/v/a.mp4"),
]


@pytest.mark.parametrize("raw,expected", [
    ("", None), ("mp4", {".mp4"}), (".mkv,avi", {".mkv", ".avi"}),
    (",,", set()),
    # Pinned quirk kept from the original handler: only the whole string is
    # stripped by the route, so spaces around a part survive inside the extension.
    ("mp4 , mov", {".mp4 ", ". mov"}),
])
def test_parse_ext_filter(raw, expected):
    assert lb._parse_ext_filter(raw) == expected


def test_no_filters_returns_everything_without_private_keys():
    out = lb._filter_library_items(ITEMS, None, "", None, None, "all")
    assert [i["name"] for i in out] == ["a.mp4", "B.mkv", "c.avi", "a_comp.mp4"]
    assert all(set(i) <= {"name", "path", "size", "mtime", "kind", "source", "compressed"} for i in out)


def test_compressed_items_carry_source_and_originals_the_flag():
    out = {i["name"]: i for i in lb._filter_library_items(ITEMS, None, "", None, None, "all")}
    assert out["a_comp.mp4"]["source"] == "/v/a.mp4" and "compressed" not in out["a_comp.mp4"]
    assert out["a.mp4"]["compressed"] is True and "source" not in out["a.mp4"]
    assert out["c.avi"]["compressed"] is False


@pytest.mark.parametrize("kwargs,expected", [
    (dict(allowed_exts={".mp4"}), ["a.mp4", "a_comp.mp4"]),
    (dict(q="a"), ["a.mp4", "c.avi", "a_comp.mp4"]),
    (dict(q="b"), ["B.mkv"]),
    (dict(min_size=1000), ["a.mp4", "B.mkv"]),
    (dict(max_size=400), ["c.avi", "a_comp.mp4"]),
    (dict(min_size=300, max_size=1000), ["a.mp4", "c.avi", "a_comp.mp4"]),
    (dict(kind="compressed"), ["a_comp.mp4"]),
    (dict(kind="original"), ["a.mp4", "B.mkv", "c.avi"]),
    (dict(allowed_exts=set()), []),
])
def test_filters(kwargs, expected):
    args = dict(allowed_exts=None, q="", min_size=None, max_size=None, kind="all")
    args.update(kwargs)
    out = lb._filter_library_items(ITEMS, args["allowed_exts"], args["q"], args["min_size"],
                                   args["max_size"], args["kind"])
    assert [i["name"] for i in out] == expected


@pytest.mark.parametrize("sort,order,expected", [
    ("name", "asc", ["a.mp4", "a_comp.mp4", "B.mkv", "c.avi"]),
    ("name", "desc", ["c.avi", "B.mkv", "a_comp.mp4", "a.mp4"]),
    ("size", "asc", ["c.avi", "a_comp.mp4", "a.mp4", "B.mkv"]),
    ("size", "desc", ["B.mkv", "a.mp4", "a_comp.mp4", "c.avi"]),
    ("date", "asc", ["a.mp4", "c.avi", "B.mkv", "a_comp.mp4"]),
    ("date", "desc", ["a_comp.mp4", "B.mkv", "c.avi", "a.mp4"]),
    ("bogus", "desc", ["a_comp.mp4", "B.mkv", "c.avi", "a.mp4"]),
    ("size", "anything", ["B.mkv", "a.mp4", "a_comp.mp4", "c.avi"]),
])
def test_sorting_in_place(sort, order, expected):
    items = lb._filter_library_items(ITEMS, None, "", None, None, "all")
    assert lb._sort_library_items(items, sort, order) is None
    assert [i["name"] for i in items] == expected

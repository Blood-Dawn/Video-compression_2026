"""Backwards line reading matches a forward read, and read_recent keeps its contract."""

import json
import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils import event_log  # noqa: E402
from utils.tail import iter_lines_backwards  # noqa: E402

SAMPLES = {
    "empty": "",
    "one-no-newline": "abc",
    "trailing-newline": "a\nb\n",
    "crlf": "a\r\nb\r\n\r\nc",
    "lone-cr": "a\rb\nc",
    "unicode": "café\n☃ snow\n中文\n",
    "blank-runs": "\n\n x \n\n\ny\n\n",
}


def _non_empty(lines):
    return [ln for ln in lines if ln]


@pytest.mark.parametrize("block", [1, 2, 3, 7, 64, 65536])
@pytest.mark.parametrize("name", sorted(SAMPLES))
def test_backwards_matches_reversed_splitlines(tmp_path, name, block):
    text = SAMPLES[name]
    p = tmp_path / "f.txt"
    p.write_bytes(text.encode("utf-8"))

    got = list(iter_lines_backwards(p, block_size=block))

    assert _non_empty(got) == _non_empty(list(reversed(text.splitlines())))


def test_random_files_with_small_blocks(tmp_path):
    rnd = random.Random(7)
    alphabet = ["a", "b", "\n", "\r\n", "é", "☃", " "]
    for i in range(50):
        text = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 400)))
        p = tmp_path / f"r{i}.txt"
        p.write_bytes(text.encode("utf-8"))
        for block in (1, 5, 13):
            got = _non_empty(list(iter_lines_backwards(p, block_size=block)))
            assert got == _non_empty(list(reversed(text.splitlines())))


def test_read_recent_returns_newest_first_and_skips_junk(tmp_path):
    lines = [json.dumps({"n": i}) for i in range(500)]
    lines.insert(250, "{broken")
    (tmp_path / event_log.EVENTS_FILENAME).write_text("\n".join(lines) + "\n\n", encoding="utf-8")

    got = event_log.read_recent(tmp_path, limit=5)

    assert [e["n"] for e in got] == [499, 498, 497, 496, 495]
    assert len(event_log.read_recent(tmp_path, limit=10_000)) == 500
    assert event_log.read_recent(tmp_path / "missing") == []

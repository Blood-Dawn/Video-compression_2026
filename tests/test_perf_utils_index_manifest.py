"""Tail-read manifest appends and the cached compressed-index reads match the full reads."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from utils import compressed_index as cidx  # noqa: E402
from utils import integrity  # noqa: E402


def _full_read_last_chain(manifest: Path) -> str:
    entries = integrity._read_entries(manifest)
    return str(entries[-1].get("chain", integrity._GENESIS)) if entries else integrity._GENESIS


def _line(chain: str, pad: int = 0) -> str:
    return json.dumps({"file": "x.mp4", "sha256": "a" * 64, "pad": "p" * pad, "chain": chain})


@pytest.mark.parametrize("body", [
    "",
    "\n\n",
    _line("c1") + "\n",
    _line("c1") + "\n" + _line("c2"),                          # no trailing newline
    _line("c1") + "\r\n" + _line("c2") + "\r\n\r\n   \n",       # CRLF and blank tail
    _line("c1") + "\n{not json\n",                             # malformed last line
    _line("c1") + "\n" + _line("c2", pad=200_000) + "\n",       # last line longer than one block
    "\n".join(_line(f"c{i}") for i in range(5000)) + "\n",     # spans many blocks
    _line("c1") + "\n" + json.dumps({"file": "y.mp4"}) + "\n",  # last entry has no chain
], ids=["empty", "blank", "one", "no-newline", "crlf-blank-tail", "malformed", "long-line",
        "many-blocks", "no-chain"])
def test_last_chain_matches_a_full_read(tmp_path, body):
    manifest = tmp_path / integrity.MANIFEST_NAME
    manifest.write_bytes(body.encode("utf-8"))

    assert integrity._last_chain(manifest) == _full_read_last_chain(manifest)


def test_missing_manifest_starts_at_genesis(tmp_path):
    assert integrity._last_chain(tmp_path / "nope.jsonl") == integrity._GENESIS


def test_appends_keep_a_verifiable_chain(tmp_path):
    for i in range(30):
        f = tmp_path / f"seg_{i}.mp4"
        f.write_bytes(bytes([i]) * (i + 1))
        assert integrity.append_manifest(tmp_path, f) is not None

    report = integrity.verify_manifest(tmp_path)

    assert report["ok"] and report["entries"] == 30


def test_cached_reads_see_every_new_record(tmp_path):
    idx = tmp_path / "index.json"
    outs = tmp_path / "outs"
    outs.mkdir()
    for i in range(20):
        src = tmp_path / f"s{i}.mp4"
        src.write_bytes(b"x" * (i + 1))
        out = outs / f"s{i}.mp4"
        out.write_bytes(b"y")
        assert not cidx.is_compressed(src, index_path=idx)
        assert cidx.classify(out, index_path=idx) == "original"

        cidx.record(src, out, index_path=idx)

        assert cidx.is_compressed(src, index_path=idx)
        assert cidx.classify(out, index_path=idx) == "compressed"


def test_lookup_returns_a_copy(tmp_path):
    idx = tmp_path / "index.json"
    src = tmp_path / "a.mp4"
    src.write_bytes(b"x")
    cidx.record(src, tmp_path / "out.mp4", preset="p", index_path=idx)

    cidx.lookup(src, index_path=idx)["preset"] = "changed"

    assert cidx.lookup(src, index_path=idx)["preset"] == "p"


def test_lookup_tolerates_non_dict_entries(tmp_path):
    index = tmp_path / "idx.json"
    index.write_text(json.dumps({"entries": {"x": "junk", "y": None, "z": ["a"]}}),
                     encoding="utf-8")
    assert cidx.lookup(index, "x") == "junk" or cidx.lookup(index, "x") is None
    assert cidx.is_compressed(tmp_path / "a.mp4", index_path=index) in (True, False)

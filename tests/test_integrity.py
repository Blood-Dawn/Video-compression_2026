"""
tests/test_integrity.py - R5 TASK 5.8 (tamper-evident output manifests).

Covers the acceptance cases from docs/CLAUDE-CODE-R5.md: verify passes on an
untouched set, a single flipped byte fails verification and names the file,
and an edited manifest line breaks the hash chain.

Author: Bloodawn (KheivenD), 2026-08-16 (R5 TASK 5.8).
"""

import json
from pathlib import Path

from utils.integrity import (  # noqa: E402
    MANIFEST_NAME,
    append_manifest,
    file_sha256,
    main,
    verify_manifest,
)


def _make_outputs(tmp_path: Path, count: int = 3) -> list[Path]:
    files = []
    for i in range(count):
        p = tmp_path / f"cam1_clip{i}.mp4"
        p.write_bytes(b"fake-video-payload-%d" % i * 100)
        files.append(p)
        assert append_manifest(tmp_path, p) is not None
    return files


def test_verify_passes_on_untouched_outputs(tmp_path):
    _make_outputs(tmp_path)
    report = verify_manifest(tmp_path)
    assert report["ok"] is True
    assert report["entries"] == 3
    assert report["bad_files"] == []
    assert report["missing"] == []
    assert report["chain_broken_at"] is None


def test_single_flipped_byte_fails_and_names_the_file(tmp_path):
    files = _make_outputs(tmp_path)
    victim = files[1]
    data = bytearray(victim.read_bytes())
    data[10] ^= 0xFF  # flip one byte
    victim.write_bytes(bytes(data))
    report = verify_manifest(tmp_path)
    assert report["ok"] is False
    assert report["bad_files"] == [victim.name]
    # The manifest itself was not touched, so the chain still verifies.
    assert report["chain_broken_at"] is None


def test_missing_file_detected(tmp_path):
    files = _make_outputs(tmp_path)
    files[0].unlink()
    report = verify_manifest(tmp_path)
    assert report["ok"] is False
    assert files[0].name in report["missing"]


def test_manifest_tamper_breaks_the_chain(tmp_path):
    files = _make_outputs(tmp_path)
    manifest = tmp_path / MANIFEST_NAME
    lines = manifest.read_text(encoding="utf-8").splitlines()
    entry = json.loads(lines[0])
    # Forge the first entry to vouch for different content: recompute a
    # plausible-looking sha but do NOT know how to rebuild the chain.
    entry["sha256"] = "ab" * 32
    lines[0] = json.dumps(entry, separators=(",", ":"))
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    report = verify_manifest(tmp_path)
    assert report["ok"] is False
    assert report["chain_broken_at"] == 0


def test_chain_links_entries_in_order(tmp_path):
    _make_outputs(tmp_path)
    manifest = tmp_path / MANIFEST_NAME
    entries = [json.loads(l) for l in manifest.read_text(encoding="utf-8").splitlines()]
    assert entries[0]["prev"] == "0" * 64
    assert entries[1]["prev"] == entries[0]["chain"]
    assert entries[2]["prev"] == entries[1]["chain"]


def test_empty_folder_verifies_ok(tmp_path):
    report = verify_manifest(tmp_path)
    assert report["ok"] is True
    assert report["entries"] == 0


def test_file_sha256_matches_manifest_record(tmp_path):
    files = _make_outputs(tmp_path, count=1)
    manifest = tmp_path / MANIFEST_NAME
    entry = json.loads(manifest.read_text(encoding="utf-8").splitlines()[0])
    assert entry["sha256"] == file_sha256(files[0])


def test_cli_verify_exit_codes(tmp_path, capsys):
    files = _make_outputs(tmp_path)
    assert main(["verify", str(tmp_path)]) == 0
    data = bytearray(files[0].read_bytes())
    data[0] ^= 0x01
    files[0].write_bytes(bytes(data))
    assert main(["verify", str(tmp_path)]) == 1
    assert main(["bogus"]) == 2
    capsys.readouterr()

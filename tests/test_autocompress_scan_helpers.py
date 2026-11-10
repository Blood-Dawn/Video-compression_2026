"""Pins the helpers taken out of autocompress_runner.scan_once."""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.services import autocompress_runner as acr  # noqa: E402
from utils import watchfolder as wf  # noqa: E402


def test_no_profile_uses_the_plain_defaults():
    assert acr._scan_settings(None, None, None) == (False, 1.0, 2)


def test_unknown_profile_name_falls_back_to_the_defaults():
    assert acr._scan_settings("no-such-profile", None, None) == (False, 1.0, 2)


@pytest.mark.parametrize("name", sorted(wf.WATCHFOLDER_PROFILES))
def test_a_named_profile_supplies_layout_and_stability(name):
    prof = wf.WATCHFOLDER_PROFILES[name]
    assert acr._scan_settings(name, None, None) == (prof.recursive, prof.settle_seconds, prof.stable_checks)


@pytest.mark.parametrize("name", [None] + sorted(wf.WATCHFOLDER_PROFILES))
def test_explicit_arguments_win_over_the_profile(name):
    recursive, settle, checks = acr._scan_settings(name, 0.0, 7)
    assert (settle, checks) == (0.0, 7)
    prof = wf.WATCHFOLDER_PROFILES.get(name) if name else None
    assert recursive == (prof.recursive if prof else False)


def _touch(p: Path, data=b"x" * 50):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)


@pytest.fixture()
def tree(tmp_path):
    watch = tmp_path / "watch"
    for rel in ["a.mp4", "b.MKV", "notes.txt", "sub/d.mp4", "sub/deep/e.avi"]:
        _touch(watch / rel)
    comp = tmp_path / "out" / "compressed"
    _touch(comp / "a_out.mp4")
    return watch, comp.resolve()


def test_top_level_scan_skips_subfolders_and_non_video(tree):
    watch, comp = tree
    assert sorted(f.name for f in acr._find_candidates(watch, False, comp)) == ["a.mp4", "b.MKV"]


def test_recursive_scan_finds_nested_clips(tree):
    watch, comp = tree
    assert sorted(f.name for f in acr._find_candidates(watch, True, comp)) == [
        "a.mp4", "b.MKV", "d.mp4", "e.avi"]


def test_files_inside_the_compressed_folder_are_skipped(tree):
    watch, comp = tree
    inside = watch / "compressed"
    _touch(inside / "z.mp4")
    found = [f.name for f in acr._find_candidates(watch, True, inside.resolve())]
    assert "z.mp4" not in found and "a.mp4" in found


def test_anything_under_a_folder_named_compressed_is_skipped(tree):
    watch, comp = tree
    _touch(watch / "sub" / "compressed" / "y.mp4")
    found = [f.name for f in acr._find_candidates(watch, True, comp)]
    assert "y.mp4" not in found and "d.mp4" in found


def test_an_empty_folder_has_no_candidates(tmp_path):
    (tmp_path / "w").mkdir()
    assert acr._find_candidates(tmp_path / "w", True, tmp_path / "c") == []

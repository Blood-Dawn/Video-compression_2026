"""
tests/security/test_ingest_filename_normalization.py

Regression coverage for the chunked-upload filename sanitizer
(src/gui/routes/ingest_bp.py::_safe_leaf_name).

Found 2026-09-21: the endpoint used Path(name).name to strip directory
components from a client-supplied filename. That only strips the separator
the HOST OS recognizes. On a POSIX host (this project also ships a Dockerfile
and an AppImage build, so POSIX is a real target, not hypothetical) a
Windows-style payload like "..\\..\\escape\\clip.mp4" has no '/' in it, so
Path.name returned it unchanged: a literal, garbled filename on disk instead
of the intended clean "clip.mp4". It did not escape the upload directory for
this specific payload (backslash is just a normal character to a POSIX
filesystem), but the sanitizer was not doing what it claimed to do, and a
mixed-separator or double-encoded payload against a Linux/Docker deployment
is exactly the kind of thing that turns into a real escape with one more bug
stacked on top. Fixed by normalizing both separator styles before taking the
leaf component, regardless of host OS.

This file is deliberately unit-level (imports the helper directly) so it
stays fast and exercises payload shapes the end-to-end
tests/test_chunked_upload.py test does not: drive letters, UNC paths, and
bare "..".
"""

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).parent.parent.parent / "src"))

import pytest

from gui.routes.ingest_bp import _safe_leaf_name


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("..\\..\\escape\\clip.mp4", "clip.mp4"),      # Windows-style traversal
        ("../../escape/clip.mp4", "clip.mp4"),          # POSIX-style traversal
        ("..\\../mixed\\clip.mp4", "clip.mp4"),         # mixed separators
        ("C:\\Windows\\System32\\evil.mp4", "evil.mp4"),  # drive-letter absolute path
        ("\\\\server\\share\\evil.mp4", "evil.mp4"),    # UNC path
        ("sub/dir/clip.mp4", "clip.mp4"),               # ordinary nested path
        ("clip.mp4", "clip.mp4"),                       # already a bare leaf
        ("....mp4", "....mp4"),                         # leading dots, no separator: not traversal
    ],
)
def test_traversal_payloads_reduce_to_a_bare_leaf(raw, expected):
    assert _safe_leaf_name(raw, fallback="<FALLBACK>") == expected


@pytest.mark.parametrize("raw", ["..", "../..", "", "   ", "/", "\\", "//", "\\\\"])
def test_degenerate_names_fall_back_instead_of_producing_a_traversal_segment(raw):
    # A payload that is ENTIRELY separators or dot-segments must never pass
    # through as itself: that is exactly the shape a traversal attempt takes.
    result = _safe_leaf_name(raw, fallback="<FALLBACK>")
    assert result == "<FALLBACK>"


def test_default_fallback_is_a_safe_filename():
    assert _safe_leaf_name("..") == "upload.mp4"

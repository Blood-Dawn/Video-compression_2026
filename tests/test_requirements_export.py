"""
tests/test_requirements_export.py

requirements.txt is a generated export of uv.lock, not a second place to
declare dependencies. The hand-maintained copy had drifted into listing the
wrong OpenCV build and missing three core packages, so this pins it to the
lock: if pyproject.toml/uv.lock change and nobody reruns
scripts/export_requirements.py, this fails with the command to fix it.

Author: Bloodawn (KheivenD), 2026-09-24 (repo cleanup sweep).
"""

import importlib.util
import shutil
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
REQS = ROOT / "requirements.txt"


def _exporter():
    spec = importlib.util.spec_from_file_location(
        "export_requirements", ROOT / "scripts" / "export_requirements.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_requirements_is_marked_generated():
    head = REQS.read_text(encoding="utf-8").splitlines()[0]
    assert head.startswith("# GENERATED from uv.lock")


def test_requirements_has_the_contrib_opencv_not_the_plain_one():
    # cv2.bgsegm (the GMG subtractor) only exists in the contrib build, and
    # the two wheels clobber each other's cv2/ package if both are installed.
    names = {line.split("==")[0].strip().lower()
             for line in REQS.read_text(encoding="utf-8").splitlines()
             if line and not line.startswith(("#", " "))}
    assert "opencv-contrib-python" in names
    assert "opencv-python" not in names
    # torch stays an optional extra; the slim install must not pull it.
    assert "torch" not in names


@pytest.mark.skipif(shutil.which("uv") is None, reason="uv not installed")
def test_requirements_matches_uv_lock():
    want = _exporter().render()
    assert REQS.read_text(encoding="utf-8") == want, (
        "requirements.txt is stale; run: python scripts/export_requirements.py")

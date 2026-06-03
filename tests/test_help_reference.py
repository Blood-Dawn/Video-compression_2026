"""
tests/test_help_reference.py

Guards the in-app Help / Reference overlay (FIX 8).

Asserts the Help overlay documents the round-1 features (Setup destination
chooser, Library tab, Tools tab, verbose logging, factory reset, dependency
status) and keeps the existing Network Access section.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 8).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(scope="module")
def html():
    from gui.app import app
    return app.test_client().get("/").get_data(as_text=True)


def test_help_documents_new_features(html):
    low = html.lower()
    for needle in (
        "setup &amp; maintenance",
        "reset app data",
        "library tab",
        "tools tab",
        "verbose logging",
        "dependency status",
        "output destination",
    ):
        assert needle in low, f"Help is missing: {needle!r}"


def test_help_keeps_network_access(html):
    assert "network access" in html.lower()


def test_help_dependency_check_wired(html):
    assert "checkDependencies()" in html
    assert 'id="help-deps-result"' in html


def test_checkdependencies_defined_in_js():
    js = (SRC / "gui" / "static" / "js" / "setup.js").read_text(encoding="utf-8")
    assert "function checkDependencies" in js
    assert "/api/setup/dependencies" in js

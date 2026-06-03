"""
tests/test_upload_tab.py

Guards the dedicated "Upload Video" topbar tab (M1 TASK 1.7).

Static checks on the rendered dashboard HTML: the UPLOAD nav button exists, sits
second (right after HOME, before METRICS), the tab-upload page exists, and the
upload dropzone (#upload-input) lives there exactly once (it was relocated from
the sidebar, not duplicated). Frontend-only — the /api/upload route is unchanged,
so route-count guards stay put.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 1.7 — Upload tab).
"""

import re
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


def _nav_order(html: str):
    # Order of the topbar tab buttons (data-tab on .tab-btn), in source order.
    return re.findall(r'class="tab-btn[^"]*"\s+data-tab="(\w+)"', html)


def test_upload_nav_button_exists(html):
    assert 'data-tab="upload"' in html


def test_upload_is_second_after_home_before_metrics(html):
    order = _nav_order(html)
    assert order[0] == "home" and order[1] == "upload", order
    assert order.index("upload") < order.index("metrics")


def test_full_nav_order(html):
    # FIX 4 inserted TOOLS (between SEARCH and ENCRYPT); FIX 6 inserted LIBRARY
    # (right after UPLOAD).
    assert _nav_order(html) == [
        "home", "upload", "library", "metrics", "search", "tools", "encrypt"]


def test_upload_tab_page_exists(html):
    assert 'id="tab-upload"' in html
    assert 'class="tab-page"' in html  # the upload page is a tab-page


def test_dropzone_moved_not_duplicated(html):
    # The upload input/zone exist exactly once (relocated into the Upload tab).
    assert html.count('id="upload-input"') == 1
    assert html.count('id="upload-zone"') == 1
    assert html.count('id="video-list"') == 1


def test_upload_tab_has_active_css_rule(html):
    assert re.search(r'\.tab-btn\[data-tab="upload"\]\.active', html)


def test_sidebar_has_launcher_to_upload_tab(html):
    # The sidebar keeps a button that switches to the Upload tab.
    assert "switchTab('upload')" in html

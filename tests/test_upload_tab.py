"""
tests/test_upload_tab.py

Guards the merged Home page. Upload used to be its own tab (M1 TASK 1.7). On the
demo branch it lives inside Home, step 1 ("Choose the video"), so there is no
UPLOAD tab, no sidebar, and the dropzone exists exactly once inside #tab-home.
The /api/upload route is unchanged.
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
    return re.findall(r'class="tab-btn[^"]*"\s+data-tab="(\w+)"', html)


def test_no_upload_tab_or_sidebar(html):
    assert 'data-tab="upload"' not in html
    assert 'id="tab-upload"' not in html
    assert "<aside" not in html


def test_full_nav_order(html):
    assert _nav_order(html) == [
        "home", "library", "autocompress", "security",
        "metrics", "search", "tools", "encrypt"]


def test_dropzone_inside_home_once(html):
    assert html.count('id="upload-input"') == 1
    assert html.count('id="upload-zone"') == 1
    assert html.count('id="video-list"') == 1
    home = html.index('id="tab-home"')
    assert home < html.index('id="upload-zone"')
    # The next tab page after home must come after the dropzone.
    nxt = [m.start() for m in re.finditer(r'id="tab-\w+" class="tab-page', html) if m.start() > home]
    assert not nxt or nxt[0] > html.index('id="upload-zone"')


def test_compress_column_is_a_section_in_home(html):
    assert re.search(r'<section class="sidebar compress-col" aria-label="Compression setup">', html)
"""
tests/test_tools_tab.py

Guards the TOOLS topbar tab (FIX 4): RTSP + HLS controls moved out of the
sidebar into a dedicated tab. The relocation happens at runtime in tools.js, so
these are static checks that the tab, the relocation target, and the loader are
in place and the nav order is correct. The route count is unchanged (no backend
change) and is asserted by the blueprint guards.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 4).
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


def _nav(html):
    return re.findall(r'class="tab-btn[^"]*"\s+data-tab="(\w+)"', html)


def test_tools_tab_between_search_and_encrypt(html):
    nav = _nav(html)
    assert "tools" in nav
    assert nav.index("search") + 1 == nav.index("tools")
    assert nav.index("tools") + 1 == nav.index("encrypt")


def test_tools_page_and_relocation_target_exist(html):
    assert 'id="tab-tools"' in html
    assert 'id="tab-tools-body"' in html  # tools.js moves the controls here


def test_tools_js_loaded(html):
    assert "js/tools.js" in html


def test_relocated_controls_still_in_document(html):
    # The nodes still ship in the HTML (tools.js reparents them at load time).
    for needle in ('id="rtsp-server-details"', 'id="hls-input"', 'id="hls-section"'):
        assert needle in html


def test_tools_js_moves_known_nodes():
    js = (SRC / "gui" / "static" / "js" / "tools.js").read_text(encoding="utf-8")
    assert "tab-tools-body" in js
    assert "rtsp-server-details" in js
    assert "hls-input" in js
    assert "hls-section" in js

"""
tests/test_sticky_header.py

Guards the sticky, opaque top header (FIX 3).

Static check on the rendered CSS so the header cannot regress to a low z-index
or a see-through background that lets text bleed through scrolled content.

Author: Bloodawn (KheivenD), 2026-06-03 (FIX 3).
"""

import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(scope="module")
def header_css():
    from gui.app import app
    html = app.test_client().get("/").get_data(as_text=True)
    # Grab the `header { ... }` rule block from the inline stylesheet.
    m = re.search(r"\bheader\s*\{([^}]*)\}", html)
    assert m, "header CSS rule not found"
    return m.group(1)


def test_header_is_sticky(header_css):
    assert "position: sticky" in header_css
    assert re.search(r"top:\s*0", header_css)


def test_header_is_above_content(header_css):
    m = re.search(r"z-index:\s*(\d+)", header_css)
    assert m and int(m.group(1)) >= 1000, "header z-index must be high enough to stay on top"


def test_header_background_is_opaque(header_css):
    # A solid hex (or rgb without alpha) so scrolled text never shows through.
    assert re.search(r"background-color:\s*#[0-9a-fA-F]{6}\b", header_css), header_css
    assert "rgba(" not in header_css.split("box-shadow")[0]  # bg itself not alpha

"""
tests/security/test_xss.py  (SEC-014, SEC-D3)

The scanVideos() list builds an inline onclick from a user-controlled FILENAME.
It must interpolate the filename with jsAttr (which escapes single quotes and
backslashes), not escHtml (which does not), so a file named
`x';alert(1);'.mp4` cannot break out of the JS string and execute. This is a
static guard on the source so the quote-unsafe form cannot be reintroduced; the
live DOM behaviour is browser-verified during the audit.
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def test_scan_videos_onclick_uses_quote_safe_escaper():
    js = (SRC / "gui" / "static" / "js" / "pipeline.js").read_text(encoding="utf-8")
    # The onclick value= must use jsAttr (quote-safe), never escHtml.
    assert "value='${jsAttr(v)}'" in js, "SEC-014: scanVideos onclick lost its quote-safe escaper"
    assert "value='${escHtml(v)}'" not in js, "SEC-014: scanVideos onclick uses the quote-UNSAFE escHtml"


def test_jsattr_escapes_single_quotes_and_backslashes():
    js = (SRC / "gui" / "static" / "js" / "ui.js").read_text(encoding="utf-8")
    # jsAttr must neutralize the characters that allow a JS-string breakout.
    assert r".replace(/\\/g" in js, "jsAttr must escape backslashes"
    assert ".replace(/'/g" in js, "jsAttr must escape single quotes"

"""The dashboard must not execute scripts fetched from a third-party host.

A CDN script tag (especially an unpinned one such as hls.js@latest) lets a
changed or compromised upstream release run inside the dashboard. Scripts are
vendored under src/gui/static/js/vendor instead.
"""

import re
from pathlib import Path

_TEMPLATES = Path(__file__).resolve().parent.parent / "src" / "gui" / "templates"
_EXTERNAL_SCRIPT = re.compile(r"<script\b[^>]*\bsrc\s*=\s*[\"']?(?:https?:)?//", re.IGNORECASE)


def test_no_template_loads_an_external_script():
    offenders = []
    for path in sorted(_TEMPLATES.rglob("*.html")):
        text = path.read_text(encoding="utf-8")
        for match in _EXTERNAL_SCRIPT.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            offenders.append(f"{path.name}:{line}")
    assert not offenders, f"external <script src> found: {offenders}"


def test_vendored_hls_is_pinned_and_present():
    vendor = Path(__file__).resolve().parent.parent / "src" / "gui" / "static" / "js" / "vendor"
    assert (vendor / "hls.min.js").stat().st_size > 100_000
    assert "1.7.4" in (vendor / "README.md").read_text(encoding="utf-8")
    index = (_TEMPLATES / "index.html").read_text(encoding="utf-8")
    assert "js/vendor/hls.min.js" in index
    assert "hls.js@latest" not in index

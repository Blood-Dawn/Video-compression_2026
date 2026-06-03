"""
tests/test_download_page.py

Guards the public download page (M5 TASK 5.1).

Static checks: the page exists, leads with the surveillance/self-hosted/
open-source wedge, links the GitHub Releases installer, documents SHA-256
verification and system requirements, pulls in NO CDN/external resources (DoD-
network / offline friendly), and makes no competitor comparisons.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5.1 — download page).
"""

import re
from pathlib import Path

import pytest

SITE = Path(__file__).parent.parent / "docs" / "site"
INDEX = SITE / "index.html"
CSS = SITE / "style.css"
README = Path(__file__).parent.parent / "README.md"


@pytest.fixture(scope="module")
def html():
    return INDEX.read_text(encoding="utf-8")


def test_page_and_stylesheet_exist():
    assert INDEX.is_file()
    assert CSS.is_file()


def test_links_release_installer(html):
    assert "releases/latest" in html
    assert "SVCS-Setup" in html


def test_documents_checksum_verification(html):
    low = html.lower()
    assert "sha256" in low
    assert "get-filehash" in low or "sha256sum" in low


def test_lists_system_requirements(html):
    low = html.lower()
    flat = re.sub(r"\s+", " ", low)  # collapse the wrapped <strong>No GPU required</strong>
    assert "system requirements" in low
    assert "windows" in low
    assert "no gpu required" in flat


def test_leads_with_the_wedge(html):
    low = html.lower()
    for word in ("surveillance", "self-hosted", "open source", "agpl"):
        assert word in low, f"download copy should mention {word!r}"


def test_no_cdn_or_external_resources(html):
    # No external scripts, stylesheets, fonts, or CDN hosts — fully self-hosted.
    assert "<script" not in html.lower(), "download page should ship no JS"
    assert "cdn" not in html.lower()
    # Every href/src is either a relative asset or a github.com/repo link.
    for url in re.findall(r'(?:href|src)\s*=\s*"([^"]+)"', html):
        if url.startswith("#"):
            continue
        ok = (
            not url.startswith("http")          # relative asset (style.css, docs/…)
            or url.startswith("https://github.com/Blood-Dawn/")
        )
        assert ok, f"unexpected external resource: {url}"


def test_no_competitor_comparisons(html):
    low = html.lower()
    for name in ("axis camera station", "milestone", "blue iris", "genetec",
                 "better than", "vs.", "competitor"):
        assert name not in low, f"download copy should not compare to {name!r}"


def test_readme_has_download_link():
    body = README.read_text(encoding="utf-8")
    assert "releases/latest" in body
    assert "## Download" in body

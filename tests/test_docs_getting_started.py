"""
tests/test_docs_getting_started.py

Guards the getting-started + camera-setup docs (M5 TASK 5.3).

Static checks: getting-started.md walks install -> point at a folder/camera ->
compress, and camera-ingestion.md carries a camera compatibility table that is
honest about the cloud-locked limit and marked community-maintained with a date.

Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5.3).
"""

import re
from pathlib import Path

import pytest

DOCS = Path(__file__).parent.parent / "docs"
GETTING_STARTED = DOCS / "getting-started.md"
CAMERA = DOCS / "camera-ingestion.md"


@pytest.fixture(scope="module")
def gs():
    return GETTING_STARTED.read_text(encoding="utf-8").lower()


@pytest.fixture(scope="module")
def cam():
    return CAMERA.read_text(encoding="utf-8")


def test_getting_started_exists():
    assert GETTING_STARTED.is_file()


def test_getting_started_covers_install_point_compress(gs):
    assert "install" in gs
    # point at a folder or a camera
    assert "watch-dir" in gs or "watch-folder" in gs
    assert "rtsp" in gs or "onvif" in gs
    # compress / presets
    assert "preset" in gs
    assert "compress" in gs


def test_getting_started_is_honest_about_unsigned_beta(gs):
    assert "unsigned" in gs and "smartscreen" in gs


def test_camera_compatibility_table_present(cam):
    low = cam.lower()
    assert "compatibility table" in low
    # A markdown table with the three connection columns.
    assert "bridge" in low and "export" in low
    assert "direct" in low


def test_table_is_marked_community_maintained_with_date(cam):
    low = cam.lower()
    assert "community-maintained" in low
    # an ISO-ish date stamp (last updated YYYY-MM-DD)
    assert re.search(r"last updated\s+\d{4}-\d{2}-\d{2}", low)


def test_table_is_honest_about_cloud_locked(cam):
    low = cam.lower()
    for brand in ("ring", "nest", "arlo"):
        assert brand in low
    assert "cloud-locked" in low
    assert "never scrape a vendor cloud" in low or "no vendor-cloud" in low

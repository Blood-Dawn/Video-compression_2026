"""
tests/test_gui_blueprint_registration.py

Guard test for the M1 TASK 1.3 blueprint split.

The 48 routes that used to live in gui/app.py were carved into 12 blueprints
under gui.routes. This pins:
  * the exact route count (48 non-static rules),
  * every expected URL is registered under the correct blueprint,
  * every `/api/...` (and /media) URL the dashboard's index.html fetches is
    served by a registered route — so a renamed/dropped route can't silently
    break the frontend (its only contract is the URL string).

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — blueprint guard).
"""

import re
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import app as flask_app  # noqa: E402

# Authoritative inventory: rule -> blueprint that must own it.
EXPECTED = {
    "/": "ui",
    "/api/status": "pipeline",
    "/api/start": "pipeline",
    "/api/stop": "pipeline",
    "/api/segments": "files",
    "/api/storage": "files",
    "/api/scan_videos": "files",
    "/media/<path:rel_path>": "files",
    "/api/media_debug": "files",
    "/api/media": "files",
    "/api/browse": "files",
    "/api/open_folder": "files",
    "/api/upload": "files",
    "/api/segments/clear": "files",
    "/api/segments/hide_one": "files",
    "/api/segments/cleanup_missing": "files",
    "/api/logs": "sse",
    "/api/query_segments": "queries",
    "/api/daily_summary": "queries",
    "/api/busiest": "queries",
    "/api/demo": "demo",
    "/api/demo/status": "demo",
    "/api/demo/search_debug": "demo",
    "/api/demo/history": "demo",
    "/api/hls/start": "hls",
    "/api/hls/stop": "hls",
    "/api/hls/status": "hls",
    "/api/hls/latency": "hls",
    "/api/hls/<camera_id>/playlist.m3u8": "hls",
    "/api/hls/<camera_id>/<path:ts_file>": "hls",
    "/api/rtsp/status": "rtsp",
    "/api/rtsp/download": "rtsp",
    "/api/rtsp/start": "rtsp",
    "/api/rtsp/stop": "rtsp",
    "/api/rtsp/push": "rtsp",
    "/api/rtsp/stop_push": "rtsp",
    "/api/system_metrics": "metrics",
    "/api/gpu_info": "metrics",
    "/api/network_info": "metrics",
    "/api/enhance/plates/status": "plates",
    "/api/enhance/benchmark": "plates",
    "/api/enhance/plates": "plates",
    "/api/presets": "presets",
    "/api/detect_content": "presets",
    "/api/config/import": "presets",
    "/api/config/export": "presets",
    "/api/gdrive/detect": "presets",
    "/api/keygen": "encryption",
    "/api/decrypt": "encryption",
    "/api/encrypt": "encryption",
    "/api/cameras/discover": "cameras",
    "/api/cameras/rtsp_url": "cameras",
    "/api/usage_stats": "usage",
    "/api/usage_stats/consent": "usage",
    "/api/setup/state": "setup",
    "/api/setup/destinations": "setup",
    "/api/setup/choose": "setup",
    "/api/setup/reset": "setup",
    "/api/setup/dependencies": "setup",
}

EXPECTED_BLUEPRINTS = {
    "ui", "sse", "metrics", "presets", "encryption", "plates",
    "queries", "rtsp", "demo", "hls", "files", "pipeline", "cameras", "usage",
    "setup",
}


def _rules():
    return {r.rule: r for r in flask_app.url_map.iter_rules() if r.endpoint != "static"}


def test_route_count():
    rules = _rules()
    assert len(rules) == 59, f"expected 59 non-static routes, got {len(rules)}: {sorted(rules)}"


def test_all_twelve_blueprints_registered():
    assert set(flask_app.blueprints) == EXPECTED_BLUEPRINTS


@pytest.mark.parametrize("rule,blueprint", sorted(EXPECTED.items()))
def test_expected_route_registered_under_right_blueprint(rule, blueprint):
    rules = _rules()
    assert rule in rules, f"route {rule!r} is not registered"
    endpoint = rules[rule].endpoint
    assert endpoint.split(".")[0] == blueprint, (
        f"{rule!r} is on blueprint {endpoint.split('.')[0]!r}, expected {blueprint!r}"
    )


def test_no_unexpected_routes():
    rules = _rules()
    extra = set(rules) - set(EXPECTED)
    assert not extra, f"unexpected routes registered: {sorted(extra)}"


def test_index_html_fetches_are_all_served():
    """Every /api or /media URL fetched by the dashboard resolves to a route."""
    html = (SRC / "gui" / "templates" / "index.html").read_text(encoding="utf-8")
    # Collect URL-ish literals beginning with /api or /media, trimming JS
    # template params (${...}) and query strings to the static prefix.
    found = set()
    for m in re.finditer(r"['\"`](/(?:api|media)[a-zA-Z0-9_/.\-]*)", html):
        url = m.group(1)
        found.add(url)
    # Build a matcher: a fetched URL is "served" if it equals a registered rule
    # or shares the registered rule's static prefix (for <param> rules).
    registered = set(_rules())
    static_prefixes = []
    for rule in registered:
        prefix = rule.split("<")[0].rstrip("/")
        static_prefixes.append((prefix, rule))

    unserved = []
    for url in sorted(found):
        if url in registered:
            continue
        # match against a parametrized rule's static prefix
        if any(url == p or url.startswith(p + "/") for p, _ in static_prefixes if p):
            continue
        unserved.append(url)
    assert not unserved, f"index.html fetches URLs with no registered route: {unserved}"

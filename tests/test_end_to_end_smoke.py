"""
tests/test_end_to_end_smoke.py

End-to-end smoke test (R2.1).

The cheap guard that no route 500s on a clean install: GET the dashboard and
every param-free read-only API route through the Flask test client, asserting
each returns a non-5xx status and (for JSON endpoints) a parseable body of a
sane shape. Env-light: no real video, no external services. POST/mutating routes
and streaming routes (SSE /api/logs) are intentionally excluded.

Author: Bloodawn (KheivenD), 2026-06-03 (R2.1).
"""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture(scope="module")
def client():
    from gui.app import app
    return app.test_client()


# Curated param-free read-only GET routes (the dashboard polls these on load).
READ_ONLY_GETS = [
    "/api/status",
    "/api/segments",
    "/api/storage",
    "/api/scan_videos",
    "/api/media_debug",
    "/api/media",
    # NOTE: /api/browse is intentionally excluded - it opens a native blocking
    # file-picker dialog (tkinter) on the host, so it cannot run headless.
    "/api/query_segments",
    "/api/daily_summary",
    "/api/busiest",
    "/api/demo/status",
    "/api/demo/search_debug",
    "/api/demo/history",
    "/api/hls/status",
    "/api/hls/latency",
    "/api/rtsp/status",
    "/api/system_metrics",
    "/api/gpu_info",
    "/api/network_info",
    "/api/enhance/plates/status",
    "/api/presets",
    "/api/config/export",
    "/api/gdrive/detect",
    "/api/setup/state",
    "/api/setup/destinations",
    "/api/setup/dependencies",
    "/api/library/videos",
    "/api/usage_stats",
]


def test_index_serves_dashboard(client):
    resp = client.get("/")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "SVCS" in body
    assert 'class="tab-nav"' in body


@pytest.mark.parametrize("route", READ_ONLY_GETS)
def test_read_only_route_does_not_5xx(client, route):
    resp = client.get(route)
    assert resp.status_code < 500, f"{route} returned {resp.status_code}"
    ct = resp.headers.get("Content-Type", "")
    if "application/json" in ct:
        # Must be parseable JSON of a container shape (dict or list).
        data = resp.get_json()
        assert isinstance(data, (dict, list)), f"{route} JSON was {type(data)}"


def test_no_param_free_get_route_5xxs(client):
    """Dynamic backstop: every registered GET rule with no required params and
    not SSE/static returns a non-5xx status, so a newly added route is covered
    automatically."""
    app = client.application
    # SSE streams forever; these open native blocking file/folder dialogs.
    skip = {"static", "sse.api_logs", "files.api_browse",
            "library.api_library_browse_folder"}
    checked = 0
    for rule in app.url_map.iter_rules():
        if rule.endpoint in skip:
            continue
        if "GET" not in (rule.methods or set()):
            continue
        if rule.arguments:  # needs path params; covered by curated/other tests
            continue
        resp = client.get(rule.rule)
        assert resp.status_code < 500, f"{rule.rule} returned {resp.status_code}"
        checked += 1
    assert checked >= 20  # sanity: we actually exercised a meaningful set

"""
tests/test_gui_routes_resolve.py

Guard test for the M1 TASK 1.3 blueprint split: every registered URL pattern
resolves through the Flask url_map to a real endpoint, for the methods it
declares. Catches a blueprint that registers a rule whose view function isn't
actually wired (or a method mismatch) after the carve.

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - route-resolution guard).
"""

import sys
from pathlib import Path

import pytest
from werkzeug.exceptions import MethodNotAllowed, NotFound
from werkzeug.routing import RequestRedirect

SRC = Path(__file__).parent.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import app as flask_app  # noqa: E402

# A concrete sample URL + method for every registered rule (params filled in).
SAMPLES = [
    ("GET", "/"),
    ("GET", "/api/status"),
    ("GET", "/api/jobs/recent"),
    ("POST", "/api/start"),
    ("POST", "/api/stop"),
    ("GET", "/api/segments"),
    ("GET", "/api/storage"),
    ("GET", "/api/scan_videos"),
    ("GET", "/media/some/file.mp4"),
    ("GET", "/api/media_debug"),
    ("GET", "/api/media"),
    ("GET", "/api/browse"),
    ("POST", "/api/open_folder"),
    ("POST", "/api/upload"),
    ("POST", "/api/segments/clear"),
    ("POST", "/api/segments/hide_one"),
    ("POST", "/api/segments/cleanup_missing"),
    ("GET", "/api/logs"),
    ("GET", "/api/query_segments"),
    ("GET", "/api/daily_summary"),
    ("GET", "/api/busiest"),
    ("POST", "/api/demo"),
    ("GET", "/api/demo/status"),
    ("GET", "/api/demo/search_debug"),
    ("GET", "/api/demo/history"),
    ("POST", "/api/hls/start"),
    ("POST", "/api/hls/stop"),
    ("GET", "/api/hls/status"),
    ("GET", "/api/hls/latency"),
    ("GET", "/api/hls/cam_00/playlist.m3u8"),
    ("GET", "/api/hls/cam_00/seg0.ts"),
    ("GET", "/api/rtsp/status"),
    ("POST", "/api/rtsp/download"),
    ("POST", "/api/rtsp/start"),
    ("POST", "/api/rtsp/stop"),
    ("POST", "/api/rtsp/push"),
    ("POST", "/api/rtsp/stop_push"),
    ("GET", "/api/system_metrics"),
    ("GET", "/api/gpu_info"),
    ("GET", "/api/network_info"),
    ("GET", "/api/enhance/plates/status"),
    ("POST", "/api/enhance/benchmark"),
    ("POST", "/api/enhance/plates"),
    ("GET", "/api/presets"),
    ("POST", "/api/detect_content"),
    ("POST", "/api/config/import"),
    ("GET", "/api/config/export"),
    ("GET", "/api/gdrive/detect"),
    ("POST", "/api/keygen"),
    ("POST", "/api/decrypt"),
    ("POST", "/api/encrypt"),
    ("GET", "/api/cameras/discover"),
    ("POST", "/api/cameras/rtsp_url"),
    ("GET", "/api/usage_stats"),
    ("POST", "/api/usage_stats/consent"),
    ("GET", "/api/setup/state"),
    ("GET", "/api/setup/destinations"),
    ("POST", "/api/setup/choose"),
    ("POST", "/api/setup/reset"),
    ("GET", "/api/setup/dependencies"),
    ("GET", "/api/library/videos"),
    ("GET", "/api/library/browse_folder"),
    ("GET", "/api/library/list_dirs"),
    ("GET", "/api/library/meta"),
    ("GET", "/api/library/thumb"),
    ("GET", "/api/library/file"),
    ("POST", "/api/library/compress"),
    ("POST", "/api/autocompress/start"),
    ("POST", "/api/autocompress/stop"),
    ("GET", "/api/autocompress/status"),
    ("POST", "/api/autocompress/scan_now"),
    ("GET", "/api/retention"),
    ("POST", "/api/retention/purge_now"),
    # M0.10: device tokens for the mobile client.
    ("GET", "/api/auth/tokens"),
    ("POST", "/api/auth/tokens"),
    ("DELETE", "/api/auth/tokens/abc123"),
    ("POST", "/api/auth/tokens/revoke_all"),
    # M0.6: capabilities probe.
    ("GET", "/api/capabilities"),
    # M2.3: compression savings summary.
    ("GET", "/api/savings"),
    # R5 5.4: natural-language search.
    ("GET", "/api/nl_search"),
    # R5 5.6/5.7: zones config + behavior events.
    ("GET", "/api/zones"),
    ("GET", "/api/events/recent"),
]


@pytest.mark.parametrize("method,url", SAMPLES)
def test_url_resolves(method, url):
    """The URL binds to an endpoint for its method (no NotFound / 405)."""
    adapter = flask_app.url_map.bind("localhost")
    try:
        endpoint, _args = adapter.match(url, method=method)
    except RequestRedirect as exc:  # trailing-slash redirect still means it resolves
        endpoint = exc.new_url
    except (NotFound, MethodNotAllowed) as exc:  # pragma: no cover
        pytest.fail(f"{method} {url} did not resolve: {type(exc).__name__}")
    assert endpoint, f"{method} {url} resolved to an empty endpoint"


def test_sample_count_matches_route_count():
    """Every registered non-static route has a resolution sample here.

    73 through v2.2.0.dev0, then +4 for the M0.10 device-token routes and +1
    for the M0.6 capabilities probe. Note this counts url_map rules, so the GET
    and POST on /api/auth/tokens count twice; the sibling guard in
    test_gui_blueprint_registration.py keys on the rule STRING instead and so
    expects 77, not 78.
    """
    rules = [r for r in flask_app.url_map.iter_rules() if r.endpoint != "static"]
    # +1 for /api/nl_search (R5 5.4), +2 for /api/zones and /api/events/recent
    # (R5 5.6/5.7).
    assert len(SAMPLES) == len(rules) == 82

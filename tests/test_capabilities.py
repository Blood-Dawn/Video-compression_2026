"""
tests/test_capabilities.py

M0.6: GET /api/capabilities.

The mobile client calls this before it draws anything. The field edition drops
the HLS and RTSP blueprints entirely, so a phone pointed at a field build must
not render a LIVE tab whose every request would 404. Before this endpoint the
edition was reachable only by scraping the rendered dashboard HTML.

The tests that matter most here are the ones asserting the feature flags track
the REAL url_map rather than a hand-maintained list, and that the endpoint
itself survives in both editions. A capabilities probe that disappears in one
edition cannot do its job.

Author: Bloodawn (KheivenD), 2026-07-18 (M0.6).
"""

import sys
from pathlib import Path

import pytest
from flask import Flask

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from gui.app import register_blueprints                          # noqa: E402
from gui.routes.capabilities_bp import CAPABILITIES_VERSION      # noqa: E402


def _client(edition=None):
    app = Flask(__name__)
    register_blueprints(app, edition=edition)
    app.config["TESTING"] = True
    return app.test_client()


@pytest.fixture()
def server_client():
    return _client("server")


@pytest.fixture()
def field_client():
    return _client("field")


# ── shape ─────────────────────────────────────────────────────────────────────

def test_returns_200_and_the_expected_shape(server_client):
    r = server_client.get("/api/capabilities")
    assert r.status_code == 200
    d = r.get_json()
    for key in ("capabilities_version", "app", "version", "edition",
                "edition_label", "server_features", "features", "auth"):
        assert key in d, f"missing {key!r}"
    assert d["app"] == "SVCS"
    assert d["capabilities_version"] == CAPABILITIES_VERSION


def test_reports_a_real_version(server_client):
    """A client shows this during pairing, so "unknown" would be a defect."""
    v = server_client.get("/api/capabilities").get_json()["version"]
    assert v != "unknown"
    assert v[0].isdigit(), f"version does not look like a version: {v!r}"


def test_version_matches_pyproject(server_client):
    import tomllib
    with open(ROOT / "pyproject.toml", "rb") as fh:
        expected = tomllib.load(fh)["project"]["version"]
    assert server_client.get("/api/capabilities").get_json()["version"] == expected


def test_advertises_both_auth_schemes(server_client):
    """The client picks a credential from this rather than probing and failing."""
    auth = server_client.get("/api/capabilities").get_json()["auth"]
    assert set(auth["schemes"]) == {"basic", "bearer"}
    assert auth["token_management"] is True


# ── the endpoint exists in BOTH editions ──────────────────────────────────────

def test_present_in_server_edition(server_client):
    assert server_client.get("/api/capabilities").status_code == 200


def test_present_in_field_edition(field_client):
    """The whole point: a phone must be able to ask a field build what it is."""
    assert field_client.get("/api/capabilities").status_code == 200


# ── flags track the real url_map ──────────────────────────────────────────────

def test_server_edition_reports_streaming_available(server_client):
    d = server_client.get("/api/capabilities").get_json()
    assert d["edition"] == "server"
    assert d["server_features"] is True
    assert d["features"]["hls"] is True
    assert d["features"]["rtsp"] is True


def test_field_edition_reports_streaming_absent(field_client):
    """Field drops the HLS and RTSP blueprints, so the phone must hide LIVE."""
    d = field_client.get("/api/capabilities").get_json()
    assert d["edition"] == "field"
    assert d["server_features"] is False
    assert d["features"]["hls"] is False
    assert d["features"]["rtsp"] is False


def test_field_edition_keeps_the_local_features(field_client):
    """Field is offline, not crippled: library and compression still work."""
    f = field_client.get("/api/capabilities").get_json()["features"]
    assert f["library"] is True
    assert f["upload"] is True
    assert f["presets"] is True
    assert f["device_tokens"] is True


@pytest.mark.parametrize("flag,rule", [
    ("hls", "/api/hls/start"),
    ("rtsp", "/api/rtsp/start"),
    ("upload", "/api/upload"),
    ("library", "/api/library/videos"),
    ("autocompress", "/api/autocompress/start"),
    ("retention", "/api/retention"),
    ("encryption", "/api/encrypt"),
    ("plates", "/api/enhance/plates"),
    ("presets", "/api/presets"),
    ("metrics", "/api/system_metrics"),
    ("device_tokens", "/api/auth/tokens"),
    ("logs_stream", "/api/logs"),
])
@pytest.mark.parametrize("edition", ["server", "field"])
def test_every_flag_matches_actual_registration(flag, rule, edition):
    """Each flag must equal whether the rule is really registered.

    This is the guard that keeps the response honest: a blueprint dropped from
    an edition, or a route renamed, flips the flag automatically instead of the
    endpoint advertising a feature that 404s.
    """
    app = Flask(__name__)
    register_blueprints(app, edition=edition)
    registered = {r.rule for r in app.url_map.iter_rules()}
    reported = app.test_client().get("/api/capabilities").get_json()["features"][flag]
    assert reported == (rule in registered), (
        f"{flag!r} reported {reported} but {rule!r} registered={rule in registered} "
        f"in the {edition} edition")


# ── it must stay cheap ────────────────────────────────────────────────────────

def test_probe_does_no_disk_or_subprocess_work():
    """This is the pairing screen's connectivity probe, so it must be cheap.

    Guards against someone later adding a directory walk or an ffmpeg -version
    call, which would make a phone's "Test connection" button slow or hang.

    Matches on CODE, not prose: an earlier version of this test grepped the
    whole file and tripped on the word "subprocess" inside a comment saying the
    module must not use one.
    """
    src = (SRC / "gui" / "routes" / "capabilities_bp.py").read_text(encoding="utf-8")
    code = "\n".join(
        line.split("#", 1)[0]
        for line in src.splitlines()
        if not line.strip().startswith("#")
    )
    for banned in ("subprocess.", "rglob(", "iterdir(", "requests.",
                   "urlopen(", "connect("):
        assert banned not in code, (
            f"capabilities_bp must stay cheap; found {banned!r} in code")


def test_probe_never_500s_when_version_lookup_fails(server_client, monkeypatch):
    """A failed version lookup must degrade to "unknown", not error.

    A 500 here reads to the user as a wrong server address or a bad token,
    which sends them debugging the wrong thing entirely.
    """
    import gui.routes.capabilities_bp as cap

    def boom():
        raise RuntimeError("no package metadata")

    monkeypatch.setattr(cap, "_server_version", boom)
    r = server_client.get("/api/capabilities")
    assert r.status_code == 200, "the pairing probe must not 500"
    assert r.get_json()["version"] == "unknown"


def test_frozen_exe_scenario_still_reports_real_version(server_client, monkeypatch):
    """Simulates a PyInstaller build: no package metadata, no pyproject.toml.

    _server_version() used to try importlib.metadata then a pyproject.toml
    read, in that order. Neither survives a PyInstaller freeze of the main
    script - there is no installed-package metadata to find, and
    installer/svcs.spec never bundles pyproject.toml as a data file - so the
    real shipped exe fell through both on every release and reported
    "unknown" here, which is exactly what the mobile app shows as the paired
    server's version during pairing. utils.version.APP_VERSION is a plain
    constant compiled into the exe's bytecode, so it survives the freeze; with
    the other two sources forced to fail the way they would in a real frozen
    build, the probe must still report the real version through it.
    """
    import importlib.metadata

    def boom_metadata(name):
        raise importlib.metadata.PackageNotFoundError(name)

    def boom_open(*args, **kwargs):
        raise FileNotFoundError("pyproject.toml not bundled in a frozen exe")

    import gui.routes.capabilities_bp as cap
    monkeypatch.setattr(cap, "open", boom_open, raising=False)
    monkeypatch.setattr(importlib.metadata, "version", boom_metadata)

    r = server_client.get("/api/capabilities")
    assert r.status_code == 200, "the pairing probe must not 500"
    v = r.get_json()["version"]
    assert v != "unknown", "APP_VERSION should have carried the probe through"
    assert v[0].isdigit(), f"version does not look like a version: {v!r}"


def test_version_prefers_app_version_constant(server_client, monkeypatch):
    """APP_VERSION is the primary source now, not just a last-resort fallback.

    Makes importlib.metadata succeed with a DIFFERENT, clearly-fake version
    rather than raising, so a future edit that reorders _server_version() back
    to trying importlib.metadata first would make this test fail loudly (by
    returning the fake version) instead of passing by accident through a
    swallowed exception - which would silently reopen the frozen-exe bug this
    fix closes.
    """
    from utils.version import APP_VERSION

    import importlib.metadata
    monkeypatch.setattr(
        importlib.metadata, "version", lambda name: "999.999.999-fake"
    )

    v = server_client.get("/api/capabilities").get_json()["version"]
    assert v == APP_VERSION
    assert v != "999.999.999-fake"


def test_reported_edition_cannot_contradict_the_feature_flags():
    """The label must match the surface that is actually registered.

    edition/edition_label/server_features used to come from the environment
    while the feature flags came from the live url_map, so an explicit
    edition argument produced a response that disagreed with itself.
    """
    for edition in ("server", "field"):
        app = Flask(__name__)
        register_blueprints(app, edition=edition)
        d = app.test_client().get("/api/capabilities").get_json()
        assert d["edition"] == edition
        assert d["server_features"] is (edition == "server")
        # ...and the flags agree with the label.
        assert d["features"]["hls"] is (edition == "server")
        assert d["features"]["rtsp"] is (edition == "server")

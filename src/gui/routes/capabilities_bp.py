"""
src/gui/routes/capabilities_bp.py

GET /api/capabilities - what this server is and what it can do (M0.6).

Before this, the edition and the server_features flag were reachable ONLY by
scraping the rendered dashboard HTML (ui_bp passes them into index.html, which
publishes them as window.SVCS_EDITION). A non-browser client had no way to ask.

The mobile client needs the answer before it draws anything: the field edition
registers no HLS or RTSP blueprints at all, so a phone pointed at a field build
must not show a LIVE tab whose every request would 404. This is also the natural
"is my server address and token correct?" probe for the pairing screen, which is
why it stays deliberately cheap: no disk walk, no subprocess, no DB read.

Registered in BOTH editions, unlike the feature blueprints it reports on. A
capabilities endpoint that disappears in one edition cannot do its job.

Author: Bloodawn (KheivenD), 2026-07-18 (M0.6 - capabilities for the mobile client).
"""

from flask import Blueprint, current_app, jsonify

try:
    from gui.edition import (EDITION_FIELD, edition_label, get_edition,
                             server_features_enabled)
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.edition import (EDITION_FIELD, edition_label, get_edition,
                                 server_features_enabled)

capabilities_bp = Blueprint("capabilities", __name__)

# Bumped when the SHAPE of this response changes in a way a client must notice.
# Lets an older app detect a newer server rather than silently mis-parsing.
CAPABILITIES_VERSION = 1


def _server_version() -> str:
    """The running version, or "unknown" rather than raising.

    importlib.metadata works for an installed package; the pyproject fallback
    covers a source checkout. A capabilities probe must never 500, since it is
    the first call a client makes and a failure here looks like a bad address.
    """
    try:
        from importlib.metadata import PackageNotFoundError, version
        try:
            return version("svcs")
        except PackageNotFoundError:
            pass
    except Exception:  # noqa: BLE001 - never break the probe
        pass
    try:
        import tomllib
        from pathlib import Path
        root = Path(__file__).resolve().parents[3]
        with open(root / "pyproject.toml", "rb") as fh:
            return str(tomllib.load(fh)["project"]["version"])
    except Exception:  # noqa: BLE001
        return "unknown"


def _registered_rules() -> set:
    """Every registered rule string on the running app."""
    try:
        return {r.rule for r in current_app.url_map.iter_rules()}
    except Exception:  # noqa: BLE001 - defensive
        return set()


@capabilities_bp.route("/api/capabilities", methods=["GET"])
def api_capabilities():
    """Report edition, version, and which feature surfaces actually exist.

    Feature flags are derived from the LIVE url_map rather than hardcoded, so
    they cannot drift from what is really registered. That matters because the
    field edition drops whole blueprints at registration time.
    """
    rules = _registered_rules()

    def has(rule: str) -> bool:
        return rule in rules

    # Prefer the edition these blueprints were actually registered under
    # (stashed by register_blueprints) over re-deriving it from the
    # environment, so the label can never contradict the feature flags below.
    edition = current_app.config.get("SVCS_RESOLVED_EDITION") or get_edition()

    try:
        version_str = _server_version()
    except Exception:  # noqa: BLE001 - the probe must never 500
        # A 500 here reads to the user as a wrong server address, which sends
        # them debugging the wrong thing entirely.
        version_str = "unknown"

    return jsonify({
        "capabilities_version": CAPABILITIES_VERSION,
        "app": "SVCS",
        "version": version_str,
        "edition": edition,
        "edition_label": edition_label(edition),
        "server_features": edition != EDITION_FIELD,
        # Derived from the real url_map, not a hand-maintained list.
        "features": {
            "hls":          has("/api/hls/start"),
            "rtsp":         has("/api/rtsp/start"),
            "upload":       has("/api/upload"),
            "library":      has("/api/library/videos"),
            "autocompress": has("/api/autocompress/start"),
            "retention":    has("/api/retention"),
            "encryption":   has("/api/encrypt"),
            "plates":       has("/api/enhance/plates"),
            "presets":      has("/api/presets"),
            "metrics":      has("/api/system_metrics"),
            "device_tokens": has("/api/auth/tokens"),
            "logs_stream":  has("/api/logs"),
        },
        # Which credentials this build understands. Lets a client choose without
        # probing and failing. Note this describes SUPPORT, not whether auth is
        # currently enforced: the guard is installed by the entry point, not by
        # create_app, so the reply cannot truthfully report enforcement here.
        "auth": {
            "schemes": ["basic", "bearer"],
            "token_management": has("/api/auth/tokens"),
        },
    })

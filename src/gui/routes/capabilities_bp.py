"""
src/gui/routes/capabilities_bp.py

GET /api/capabilities - what this server is and what it can do.

A non-browser client cannot read window.SVCS_EDITION from the dashboard HTML.
The mobile client needs the answer before drawing anything: the field edition
registers no HLS or RTSP blueprints, so a LIVE tab there would only 404. It is
also the "is my server address and token correct?" probe for the pairing screen,
so it stays cheap: no disk walk, no subprocess, no DB read.

Registered in both editions, unlike the feature blueprints it reports on.

Author: Bloodawn (KheivenD), 2026-07-18 (M0.6 - capabilities for the mobile client).
"""

from flask import Blueprint, current_app, jsonify

try:
    from gui.edition import EDITION_FIELD, edition_label, get_edition
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.edition import (EDITION_FIELD, edition_label, get_edition)

capabilities_bp = Blueprint("capabilities", __name__)

# Bumped when the response shape changes in a way a client must notice.
CAPABILITIES_VERSION = 1


def _server_version() -> str:
    """The running version, or "unknown" rather than raising.

    utils.version.APP_VERSION comes first because PyInstaller compiles it into
    the frozen exe; importlib.metadata and pyproject.toml only work from a
    source checkout or an installed wheel. The probe must never 500: a failure
    looks like a bad address to the user.
    """
    try:
        try:
            from utils.version import APP_VERSION
        except ModuleNotFoundError:  # pragma: no cover - import path shim
            from src.utils.version import APP_VERSION
        if APP_VERSION:
            return APP_VERSION
    except Exception:  # noqa: BLE001 - never break the probe
        pass
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

    # The edition register_blueprints actually used, so the label cannot
    # contradict the feature flags below.
    edition = current_app.config.get("SVCS_RESOLVED_EDITION") or get_edition()

    try:
        version_str = _server_version()
    except Exception:  # noqa: BLE001 - the probe must never 500
        version_str = "unknown"

    return jsonify({
        "capabilities_version": CAPABILITIES_VERSION,
        "app": "SVCS",
        "version": version_str,
        "edition": edition,
        "edition_label": edition_label(edition),
        "server_features": edition != EDITION_FIELD,
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
        # Credentials this build understands (support, not enforcement: the
        # entry point installs the guard, so enforcement cannot be reported).
        "auth": {
            "schemes": ["basic", "bearer"],
            "token_management": has("/api/auth/tokens"),
        },
    })

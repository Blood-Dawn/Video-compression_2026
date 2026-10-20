"""
src/gui/routes/ui_bp.py

Serves the dashboard page.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

from flask import Blueprint, render_template

try:
    from gui.edition import get_edition, server_features_enabled, edition_label
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.edition import get_edition, server_features_enabled, edition_label

ui_bp = Blueprint("ui", __name__)


@ui_bp.route("/")
def index():
    # The field (offline) build hides the server-making surfaces (TOOLS tab:
    # RTSP server + HLS); the template and JS gate on these. Resolved once:
    # get_edition() can probe up to three edition.txt files.
    edition = get_edition()
    return render_template(
        "index.html",
        edition=edition,
        edition_label=edition_label(edition),
        server_features=server_features_enabled(edition),
    )



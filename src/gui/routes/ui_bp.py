"""
src/gui/routes/ui_bp.py

ui routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
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
    # R4 Phase 4: the field (offline) build hides the server-making surfaces
    # (the TOOLS tab: RTSP server + HLS). The template + JS gate on these.
    return render_template(
        "index.html",
        edition=get_edition(),
        edition_label=edition_label(),
        server_features=server_features_enabled(),
    )



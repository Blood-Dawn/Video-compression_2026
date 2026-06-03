"""
src/gui/routes/ui_bp.py

ui routes blueprint, carved from gui/app.py (TASK 1.3).
Pure relocation: every URL, method, and response shape is unchanged.
Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - blueprints).
"""

from flask import Blueprint, render_template

ui_bp = Blueprint("ui", __name__)

@ui_bp.route("/")
def index():
    return render_template("index.html")



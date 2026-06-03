# GUI services layer: pipeline/IO/threading helpers extracted from gui/app.py.
#
# Import direction is one-way and must stay that way (REFACTOR-PLAN §5):
#   state <- logging_setup <- services <- routes <- app
# Services may import gui.state and gui.logging_setup; they must NOT import
# gui.app or the gui.routes blueprints.
#
# Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — TASK 1.2).

"""
installer/launcher.py  —  PyInstaller entry point for SVCS desktop.

This is the script PyInstaller bundles as the main executable. Keeping
it tiny and dependency-free makes packaging more predictable: heavyweight
imports (torch, opencv, ultralytics, flask, …) happen inside the regular
``src/gui/run_gui`` flow, not here.

Why not point PyInstaller at run_gui.py directly?

1. ``run_gui.py`` tries to call ``uv sync`` on first run. That makes
   sense in dev (auto-install enhance extras) but is wrong inside a
   frozen .exe: the user almost certainly doesn't have `uv` on PATH
   and there's no pyproject.toml next to the binary anyway. We set
   ``SVCS_NO_AUTOSYNC=1`` here so the GUI skips that step.

2. The frozen exe runs from a different cwd than the source tree, and
   ``sys.path`` has to be primed before we try to import from ``src/``.
   PyInstaller does this through ``_MEIPASS`` (the temp dir it unpacks
   into); we make that explicit so debugging is easier.

3. We may want to drop a single combined Windows + macOS + Linux
   launcher in front of the GUI later (splash screen, license check,
   update prompt). Easier to do that here than to refactor run_gui.

Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).
"""

from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _bundle_root() -> Path:
    """Where do bundled resources (templates, models, etc.) live at runtime?

    When frozen by PyInstaller this is the _MEIPASS temp dir. When run
    from source it's the repo root (one level above installer/).
    """
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        return Path(meipass)
    return Path(__file__).resolve().parent.parent


def _prime_sys_path() -> None:
    """Make sure both the bundle root and the src/ dir are importable.

    The frozen bundle ships ``src`` flattened into the root, so the
    canonical ``from gui import app`` style imports already work. In
    source mode we have to add ``src/`` ourselves because we're being
    run from ``installer/`` instead of from the repo root.
    """
    root = _bundle_root()
    candidates = [root, root / "src"]
    for c in candidates:
        s = str(c)
        if c.exists() and s not in sys.path:
            sys.path.insert(0, s)


def _set_frozen_env() -> None:
    """Tell run_gui to skip the dependency auto-sync step.

    Inside the frozen exe there's no uv, no pyproject, no source tree.
    Letting run_gui try to shell out to ``uv sync`` only produces a
    confusing error popup for the end user. run_gui.py honors a
    ``--no-sync`` argparse flag, so we splice it into sys.argv if it
    isn't already there.
    """
    if getattr(sys, "frozen", False):
        os.environ.setdefault("SVCS_FROZEN", "1")
        os.environ.setdefault("SVCS_BUNDLE_ROOT", str(_bundle_root()))
        if "--no-sync" not in sys.argv:
            sys.argv.append("--no-sync")


def main() -> int:
    _prime_sys_path()
    _set_frozen_env()

    try:
        # Delayed import: keeps PyInstaller's startup phase fast and
        # lets us catch import errors with a clean message instead of
        # the default Python traceback dialog. run_gui.py lives at the
        # repo root (not under src/gui/) and re-exports main().
        from run_gui import main as run_gui_main
    except Exception:  # noqa: BLE001  — top-level startup must not crash silently
        sys.stderr.write(
            "SVCS failed to start while importing the dashboard.\n"
            "Please report this with the traceback below.\n\n"
        )
        traceback.print_exc()
        # Hold the window open so the user can read the error on
        # Windows when launched via double-click.
        if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close...")
        return 1

    try:
        run_gui_main()
        return 0
    except KeyboardInterrupt:
        return 0
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else 0
    except Exception:  # noqa: BLE001
        sys.stderr.write("SVCS crashed. Traceback follows.\n\n")
        traceback.print_exc()
        if getattr(sys, "frozen", False) and sys.stdin and sys.stdin.isatty():
            input("\nPress Enter to close...")
        return 2


if __name__ == "__main__":
    sys.exit(main())

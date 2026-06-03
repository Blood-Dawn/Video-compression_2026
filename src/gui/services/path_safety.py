"""
src/gui/services/path_safety.py

Path-traversal guards for the dashboard, extracted from gui/app.py (TASK 1.2).

These are pure functions — no shared state, no threads, no I/O beyond
``Path.resolve()``. They gate every route that turns a user-supplied path or
filename into a filesystem access (media serving, uploads, encrypt/decrypt).

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — path-safety extraction).
"""

from pathlib import Path

try:
    from gui.state import _SAFE_FILENAME_RE
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.gui.state import _SAFE_FILENAME_RE


def _safe_output_dir(raw: str) -> Path:
    """Resolve output_dir and verify it stays within the project root or is absolute
    and already trusted (e.g. a cloud sync folder outside the repo).

    We don't restrict to project root because legitimate use cases include pointing
    at OneDrive/Google Drive mounts. Instead we block path traversal tricks and
    require the directory to be absolute or resolvable.
    """
    p = Path(raw).resolve()
    # Block traversal sequences that survived resolution (should never happen after
    # resolve(), but guard explicitly)
    if ".." in p.parts:
        raise ValueError(f"output_dir contains traversal: {raw!r}")
    return p


def _assert_within_output(file_path: str, output_dir: str) -> Path:
    """Resolve file_path and verify it lives inside output_dir.

    Raises ValueError if path traversal is detected.
    """
    out = Path(output_dir).resolve()
    fp  = Path(file_path).resolve()
    if out != fp and out not in fp.parents:
        raise ValueError(
            f"Path {fp} is outside the output directory {out}. "
            "Access denied."
        )
    return fp


def _safe_filename(name: str) -> str:
    """Strip directory components and validate the filename is safe."""
    name = Path(name).name   # strip any directory component
    if not _SAFE_FILENAME_RE.match(name):
        raise ValueError(f"Unsafe filename: {name!r}")
    return name

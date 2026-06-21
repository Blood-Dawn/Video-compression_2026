"""
src/gui/services/path_safety.py

Path-traversal guards for the dashboard, extracted from gui/app.py (TASK 1.2).

These are pure functions - no shared state, no threads, no I/O beyond
``Path.resolve()``. They gate every route that turns a user-supplied path or
filename into a filesystem access (media serving, uploads, encrypt/decrypt).

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - path-safety extraction).
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


# ── Central confinement (SEC-002/003/004/015 hardening) ───────────────────────
# A single helper every file-SERVING route funnels through, so a path can never
# be read/served from outside the set of folders the operator actually uses.
# This replaces the ad-hoc, inconsistent per-route checks (some of which were
# dead `'..' in p.parts` tests that resolve() had already collapsed).

def is_within(path, root) -> bool:
    """True if ``path`` (resolved) equals or is nested under ``root`` (resolved)."""
    try:
        p = Path(path).resolve()
        r = Path(root).resolve()
    except (OSError, ValueError):
        return False
    return p == r or r in p.parents


def confine_to_allowed(path, allowed_roots):
    """Resolve ``path`` and require it to live within one of ``allowed_roots``.

    Returns the resolved Path, or raises ValueError if it escapes every root.
    Use for any route that reads/serves a user-supplied filesystem path.
    """
    p = Path(path).resolve()
    for root in allowed_roots:
        if is_within(p, root):
            return p
    raise ValueError(f"path is outside the allowed folders: {p}")


def is_path_allowed(path, allowed_roots) -> bool:
    """Non-raising variant of confine_to_allowed."""
    try:
        confine_to_allowed(path, allowed_roots)
        return True
    except ValueError:
        return False


def allowed_media_roots() -> list:
    """The folders a media/library path is allowed to be read or served from.

    The user's legitimate areas only: the configured output / library / encrypted
    folders, the last demo output root, the default cloud output dir and detected
    cloud SVCS root, the per-user Videos/SVCS and app-data dirs, and the repo's
    ``data/`` and ``outputs/``. NOT the whole drive and NOT the repo source tree,
    so a LAN/CSRF client cannot read arbitrary files off the host.
    """
    roots = []

    def _add(v):
        if v:
            try:
                roots.append(Path(v).resolve())
            except (OSError, ValueError):
                pass

    # Configured + persisted folders.
    try:
        from gui.state import _state_lock, _status
    except ModuleNotFoundError:  # pragma: no cover - import path shim
        from src.gui.state import _state_lock, _status
    try:
        with _state_lock:
            cfg = dict(_status.get("config", {}))
        for k in ("output_dir", "library_folder", "encrypted_dir"):
            _add(cfg.get(k))
    except Exception:  # noqa: BLE001
        pass

    # Last demo output root.
    try:
        from gui.state import _demo_lock, _demo_state
    except ModuleNotFoundError:  # pragma: no cover
        from src.gui.state import _demo_lock, _demo_state
    try:
        with _demo_lock:
            _add(_demo_state.get("last_output_root"))
    except Exception:  # noqa: BLE001
        pass

    # Per-user + app-data dirs.
    try:
        from utils import paths as _paths
    except ModuleNotFoundError:  # pragma: no cover
        from src.utils import paths as _paths
    for fn in ("default_videos_dir", "data_dir"):
        try:
            _add(getattr(_paths, fn)())
        except Exception:  # noqa: BLE001
            pass

    # Cloud default output + detected cloud SVCS root.
    try:
        from gui.services.cloud_detection import _default_output_dir, _detect_cloud_root
    except ModuleNotFoundError:  # pragma: no cover
        try:
            from src.gui.services.cloud_detection import _default_output_dir, _detect_cloud_root
        except Exception:  # noqa: BLE001
            _default_output_dir = _detect_cloud_root = None
    if _default_output_dir is not None:
        try:
            _add(_default_output_dir())
        except Exception:  # noqa: BLE001
            pass
        try:
            r, _label, _url = _detect_cloud_root()
            _add(r)
        except Exception:  # noqa: BLE001
            pass

    # Repo data/ and outputs/ (covers samples + the default local output).
    _root = Path(__file__).resolve().parents[3]
    _add(_root / "data")
    _add(_root / "outputs")

    # De-dup while preserving order.
    seen, uniq = set(), []
    for r in roots:
        s = str(r)
        if s and s not in seen:
            seen.add(s)
            uniq.append(r)
    return uniq

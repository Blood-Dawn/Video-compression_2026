"""
src/gui/services/path_safety.py

Path-traversal guards for the dashboard, extracted from gui/app.py (TASK 1.2).

These are pure functions - no shared state, no threads, no I/O beyond
``Path.resolve()``. They gate every route that turns a user-supplied path or
filename into a filesystem access (media serving, uploads, encrypt/decrypt).

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor - path-safety extraction).
"""

import ipaddress
from pathlib import Path
from urllib.parse import urlparse

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


# ── Input-source SSRF guard (SEC-013) ─────────────────────────────────────────
# The pipeline / HLS input_source is opened with cv2.VideoCapture, which honours
# http(s) and file:// URLs. An operator (or, pre-CSRF-fix, a malicious page) could
# point it at file:///etc/passwd or a cloud-metadata endpoint. We allow the real
# media schemes (and local paths + webcam indices) and block file:// and friends
# plus the link-local / cloud-metadata hosts. Private-LAN hosts stay allowed so
# real RTSP cameras on the network keep working.

_INPUT_BLOCKED_SCHEMES = {"file", "gopher", "dict", "ftp", "sftp", "smb",
                          "data", "php", "jar", "netdoc", "ldap"}
_INPUT_ALLOWED_SCHEMES = {"", "rtsp", "rtsps", "rtp", "rtmp", "rtmps",
                          "http", "https", "udp", "tcp", "mms", "srt"}
_INPUT_BLOCKED_HOSTS = {"169.254.169.254", "100.100.100.100",
                        "metadata.google.internal", "metadata"}


def redact_input_source(src) -> str:
    """Strip the password out of an input_source before it is sent to a client.

    RTSP camera URLs routinely carry credentials inline, and
    /api/cameras/rtsp_url builds exactly that shape. Those URLs were being
    echoed verbatim by /api/hls/status and by /api/status (as
    config.input_source), so any caller holding a DEVICE TOKEN could read the
    camera's password. Device tokens are deliberately the weaker credential -
    M0.10 made sure a stolen one cannot mint successors or revoke other
    devices - but a camera password usually unlocks the camera's own web admin,
    which is a worse thing to lose than the dashboard.

    Host, port, path and username survive: an operator still has to be able to
    tell which camera a stream belongs to, and the house rule names passwords.
    Webcam indexes and local file paths have no userinfo and pass through
    untouched.

    Author: Bloodawn (KheivenD), 2026-07-19 (M3 pre-work).
    """
    if src is None:
        return ""
    s = str(src)
    # No "@" means no userinfo to strip. Cheap bail-out that also keeps
    # Windows drive paths away from urlparse.
    if "@" not in s:
        return s
    try:
        parsed = urlparse(s)
    except ValueError:
        # Unparseable but contains "@": redact the whole thing rather than
        # risk passing a credential through on a parser edge case.
        return "***"
    if not parsed.scheme or parsed.password is None:
        return s
    userinfo = f"{parsed.username}:***@" if parsed.username else "***@"
    port = f":{parsed.port}" if parsed.port else ""
    return f"{parsed.scheme}://{userinfo}{parsed.hostname or ''}{port}{parsed.path}"


def is_safe_input_source(src) -> "tuple[bool, str]":
    """Validate a pipeline/HLS input_source. Returns (ok, reason).

    Allows: a webcam index, a local file path (incl. Windows drive paths), and
    real streaming URLs (rtsp/http/...). Blocks: file:// and other
    local/protocol-smuggling schemes, and the cloud-metadata / link-local hosts.
    """
    s = str(src).strip()
    if not s:
        return False, "empty input_source"
    if s.isdigit():                       # webcam index
        return True, ""
    parsed = urlparse(s)
    scheme = (parsed.scheme or "").lower()
    if len(scheme) <= 1:                   # "" (relative/abs path) or "c:" drive letter
        return True, ""
    if scheme in _INPUT_BLOCKED_SCHEMES:
        return False, f"scheme not allowed: {scheme}"
    if scheme not in _INPUT_ALLOWED_SCHEMES:
        return False, f"scheme not allowed: {scheme}"
    host = (parsed.hostname or "").lower()
    if host in _INPUT_BLOCKED_HOSTS:
        return False, "blocked internal host"
    try:
        ip = ipaddress.ip_address(host)
        if ip.is_link_local:               # 169.254.0.0/16, fe80::/10 (metadata)
            return False, "blocked link-local host"
    except ValueError:
        pass                               # a hostname, not a literal IP
    return True, ""

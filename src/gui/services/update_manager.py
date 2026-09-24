"""
src/gui/services/update_manager.py

In-app auto-update pipeline for the desktop build (Fall TASK 3.18).

Fall 3.17 (src/gui/routes/setup_bp.py::api_setup_update_check) already tells
the dashboard whether a newer desktop release exists on GitHub, but it is
check-and-notify only: a human still has to click through to GitHub, download
the installer by hand, and reinstall. This module is the rest of the
pipeline - actually fetching that release's installer, verifying it against
the checksums the release publishes (every release ships a SHA256SUMS.txt
beside its .exe/.apk assets, see docs/RELEASE-CHECKLIST.md), and launching it
- so "Install update" in the dashboard can mean exactly that.

check_for_update() below is now the single source of truth for "what is the
newest desktop release on GitHub" - setup_bp's route calls into it instead of
keeping its own copy, so the notify-only check and the actual downloader can
never disagree about which release is newest.

Design constraints, on purpose (same reasoning as the encryption-honesty and
dead-segment-counter fixes from the 2026-09-24 dishonesty audit: a feature
that can silently do something other than what it visibly says is a
liability, and an auto-updater is exactly the kind of feature where that
liability is worst):

  * The only URL this module ever fetches a RELEASE LISTING from is the
    hardcoded GitHub API endpoint for this repo (GITHUB_RELEASES_URL). The
    installer/checksum URLs it downloads are never caller-supplied either -
    they come only from the asset list GitHub itself returned for that
    listing. There is no code path anywhere in this module that downloads a
    URL a client passed in.
  * A downloaded installer is NEVER launched without its SHA256 matching the
    release's own SHA256SUMS.txt asset. Missing checksum asset, unparseable
    checksum file, or a hash that doesn't match all refuse to install and
    say why - none of them fall back to "trust it anyway".
  * Checking, downloading, and installing are three separate calls
    (check_for_update / start_download / install_and_restart), so the
    dashboard can show progress and require an explicit "Install & restart"
    click before anything destructive happens. Nothing here runs on a timer;
    the periodic background check the dashboard already does (Fall 3.17)
    only ever calls check_for_update(), never start_download() or
    install_and_restart().
  * Installing means replacing files the running app is currently executing
    from, which Windows will not let the installer do while this process
    holds them open. install_and_restart() hands off to a small detached
    PowerShell helper (PowerShell ships with every supported Windows install
    and does not depend on anything the update is about to replace) that
    waits for THIS process's pid to exit, runs the installer silently, then
    relaunches the app. The route that calls install_and_restart() is
    responsible for then calling quit_app_for_update() so this process
    actually exits and the helper's wait loop can proceed.

Author: Bloodawn (KheivenD), 2026-09-24 (Fall 3.18 - auto-update pipeline).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Optional

try:
    from gui.logging_setup import log
    from utils.version import APP_VERSION, is_newer
except ModuleNotFoundError:  # pragma: no cover - import path shim
    from src.gui.logging_setup import log
    from src.utils.version import APP_VERSION, is_newer

# Same repo, same endpoint the Fall 3.17 check has always used.
GITHUB_RELEASES_URL = (
    "https://api.github.com/repos/Blood-Dawn/Video-compression_2026/releases"
)
MOBILE_TAG_PREFIX = "mobile-"
_USER_AGENT = "SVCS-dashboard-update-check"
_CHECKSUM_ASSET_NAMES = {"sha256sums.txt"}
_INSTALL_WAIT_TIMEOUT_S = 30


# ── Fall 3.17: find the newest desktop release (shared with setup_bp) ────────

def _is_mobile_only(release: dict) -> bool:
    """True if a GitHub release ships APKs and no Windows installer."""
    names = [str(a.get("name") or "").lower()
             for a in release.get("assets") or [] if isinstance(a, dict)]
    return any(n.endswith(".apk") for n in names) and not any(n.endswith(".exe") for n in names)


def _fetch_releases() -> Optional[list]:
    """Best effort: the parsed GitHub releases list, or None on any failure
    (offline, GitHub down/rate-limited, an unparseable body)."""
    try:
        req = urllib.request.Request(
            GITHUB_RELEASES_URL,
            headers={
                "Accept": "application/vnd.github+json",
                # GitHub's API rejects requests with no User-Agent at all.
                "User-Agent": _USER_AGENT,
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            releases = json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    return releases if isinstance(releases, list) else None


def _best_desktop_release(releases: list) -> tuple[Optional[str], Optional[dict]]:
    """The newest non-draft, non-mobile release with a real desktop build.

    Prereleases are NOT excluded on purpose: every release this project has
    published so far is marked prerelease on GitHub (it's a beta product).
    """
    best_tag: Optional[str] = None
    best_release: Optional[dict] = None
    for rel in releases:
        if not isinstance(rel, dict):
            continue
        tag = str(rel.get("tag_name") or "")
        if not tag or rel.get("draft") or tag.startswith(MOBILE_TAG_PREFIX):
            continue
        if _is_mobile_only(rel):
            continue
        if best_tag is None or is_newer(tag, best_tag):
            best_tag, best_release = tag, rel
    return best_tag, best_release


def check_for_update(current_version: Optional[str] = None) -> dict:
    """Check GitHub releases for a newer DESKTOP build.

    Best effort and silent on failure: offline, GitHub unreachable, rate
    limited, or an unexpected response shape all fall through to
    update_available=False rather than raising, since a flaky network check
    must never itself look like an app error to the caller.
    """
    current = current_version or APP_VERSION
    result = {
        "current_version": current,
        "latest_version": None,
        "update_available": False,
        "release_url": None,
        "download_url": None,
        "checksum_url": None,
        "checked": False,
    }

    releases = _fetch_releases()
    if releases is None:
        return result

    best_tag, best_release = _best_desktop_release(releases)
    if best_release is not None:
        result["latest_version"] = best_tag
        result["update_available"] = is_newer(best_tag, current)
        result["release_url"] = best_release.get("html_url")
        for asset in best_release.get("assets") or []:
            if not isinstance(asset, dict):
                continue
            name = str(asset.get("name") or "").lower()
            if name.endswith(".exe") and not result["download_url"]:
                result["download_url"] = asset.get("browser_download_url")
            elif name in _CHECKSUM_ASSET_NAMES:
                result["checksum_url"] = asset.get("browser_download_url")

    result["checked"] = True
    return result


# ── Fall 3.18: download, verify, install ─────────────────────────────────────

_lock = threading.Lock()
_state = {
    # idle -> downloading -> verifying -> ready -> installing
    #                    \-> error  (from any of the above)
    "phase": "idle",
    "error": None,
    "latest_version": None,
    "download_url": None,
    "installer_path": None,
    "bytes_downloaded": 0,
    "bytes_total": 0,
}
_download_thread: Optional[threading.Thread] = None


def get_status() -> dict:
    """A snapshot of the current download/verify/install state."""
    with _lock:
        return dict(_state)


def _set(**kwargs) -> None:
    with _lock:
        _state.update(kwargs)


def reset() -> None:
    """Back to idle. Exposed mainly for tests; the dashboard has no button
    for this - a fresh "Download update" click after an error re-checks and
    re-downloads on its own."""
    with _lock:
        _state.update({
            "phase": "idle", "error": None, "latest_version": None,
            "download_url": None, "installer_path": None,
            "bytes_downloaded": 0, "bytes_total": 0,
        })


def _staging_dir() -> Path:
    """Where downloaded installers land: %LOCALAPPDATA%\\SVCS\\updates,
    falling back to a temp dir if that can't be created (sandboxed test
    runs, non-Windows dev machines)."""
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("TEMP")
    candidates = []
    if base:
        candidates.append(Path(base) / "SVCS" / "updates")
    candidates.append(Path(tempfile.gettempdir()) / "svcs_updates")
    for d in candidates:
        try:
            d.mkdir(parents=True, exist_ok=True)
            return d
        except OSError:
            continue
    # Last resort: cwd. mkdir above never raises for "." in practice.
    d = Path(".") / "svcs_updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fetch_checksum(checksum_url: str, installer_name: str) -> Optional[str]:
    """Parse a SHA256SUMS.txt-style body (``<hex>  <filename>`` per line,
    optionally with a leading ``*`` on the filename for binary mode) for the
    hash matching ``installer_name``.

    Returns None on any failure to reach or parse the file, or if that exact
    filename isn't listed - callers MUST treat None as "cannot verify", not
    as "verified", and refuse to install.
    """
    try:
        req = urllib.request.Request(checksum_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=8) as resp:
            text = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, OSError):
        return None

    target = installer_name.strip().lower()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            continue
        digest, name = parts
        name = name.strip().lstrip("*").strip().lower()
        if name == target or name.endswith("/" + target):
            digest = digest.strip().lower()
            if len(digest) == 64:
                return digest
    return None


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def start_download() -> dict:
    """Kick off a background download of the latest desktop installer.

    Re-checks GitHub itself rather than trusting anything the caller passes
    in - the only URLs ever fetched are the ones this call's own
    check_for_update() just found on the pinned releases endpoint. Returns
    the status immediately; poll get_status() for progress.
    """
    global _download_thread
    with _lock:
        if _state["phase"] in ("downloading", "verifying", "installing"):
            return dict(_state)

    info = check_for_update()
    if not info.get("update_available") or not info.get("download_url"):
        _set(phase="error", error="No downloadable desktop update is available.",
             latest_version=info.get("latest_version"))
        return get_status()

    _set(
        phase="downloading",
        error=None,
        latest_version=info.get("latest_version"),
        download_url=info.get("download_url"),
        installer_path=None,
        bytes_downloaded=0,
        bytes_total=0,
    )

    _download_thread = threading.Thread(
        target=_download_and_verify, args=(info,),
        daemon=True, name="svcs-update-download",
    )
    _download_thread.start()
    return get_status()


def _download_and_verify(info: dict) -> None:
    """Runs on the background thread started by start_download()."""
    url = info["download_url"]
    name = url.rsplit("/", 1)[-1] or "SVCS-Setup.exe"
    dest = _staging_dir() / name
    tmp = dest.with_suffix(dest.suffix + ".part")

    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=30) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            _set(bytes_total=total)
            written = 0
            with open(tmp, "wb") as fh:
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    fh.write(chunk)
                    written += len(chunk)
                    _set(bytes_downloaded=written)
        tmp.replace(dest)
    except Exception as exc:  # noqa: BLE001 - reported via status, this runs off-thread
        log.warning("Update download failed: %s", exc)
        _set(phase="error", error=f"Download failed: {exc}")
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        return

    _set(phase="verifying")
    checksum_url = info.get("checksum_url")
    expected = _fetch_checksum(checksum_url, name) if checksum_url else None
    if expected is None:
        log.warning(
            "Update verification: no usable checksum for %s (checksum_url=%s)",
            name, checksum_url,
        )
        _set(phase="error", error=(
            "Could not verify the download's checksum (SHA256SUMS.txt was "
            "missing from the release, unreachable, or didn't list this "
            "file). Refusing to install an unverified installer."
        ))
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return

    actual = _sha256_file(dest)
    if actual != expected:
        log.warning(
            "Update verification FAILED for %s: expected sha256=%s got %s",
            name, expected, actual,
        )
        _set(phase="error", error=(
            "Checksum mismatch - the downloaded file does not match the "
            "published release. It has been discarded."
        ))
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        return

    log.info(
        "Update %s downloaded and verified (sha256=%s).",
        info.get("latest_version"), actual,
    )
    _set(phase="ready", installer_path=str(dest))


def install_and_restart(app_exe_path: Optional[str] = None) -> dict:
    """Launch the verified installer silently, then relaunch the app.

    Refuses unless the current phase is "ready" with a file on disk -
    _download_and_verify() only ever reaches "ready" after the checksum
    matched, so this can never launch an unverified download.

    Hands off to a detached PowerShell helper (see module docstring for why
    PowerShell) that waits for THIS process's pid to exit, runs the
    installer with /VERYSILENT /SUPPRESSMSGBOXES /NORESTART, then relaunches
    app_exe_path. The caller is responsible for actually exiting this
    process afterwards (see quit_app_for_update()) - this function only
    launches the helper and marks the phase "installing".
    """
    with _lock:
        state = dict(_state)

    if state.get("phase") != "ready" or not state.get("installer_path"):
        return {"ok": False, "error": "No verified update is ready to install."}

    installer_path = state["installer_path"]
    if not Path(installer_path).is_file():
        _set(phase="error", error="Verified installer is missing from disk.")
        return {"ok": False, "error": "Verified installer is missing from disk."}

    if sys.platform != "win32":
        # Nothing Windows-specific to spawn on any other platform; surfaced
        # rather than pretending to succeed.
        return {"ok": False, "error": "Auto-install is only supported on Windows."}

    exe_path = app_exe_path
    if exe_path is None and getattr(sys, "frozen", False):
        exe_path = sys.executable

    pid = os.getpid()
    log_path = _staging_dir() / "install.log"
    restart_cmd = f'Start-Process -FilePath "{exe_path}"' if exe_path else ""

    # PowerShell here-string-free script: waits for our pid to exit (with a
    # timeout so the helper never hangs forever if this process fails to
    # exit), runs the installer silently and waits for it, then relaunches.
    script = (
        f'$ErrorActionPreference = "SilentlyContinue"\n'
        f'"$(Get-Date) waiting for pid {pid} to exit" | Out-File -Append "{log_path}"\n'
        f'$deadline = (Get-Date).AddSeconds({_INSTALL_WAIT_TIMEOUT_S})\n'
        f'while ((Get-Process -Id {pid} -ErrorAction SilentlyContinue) -and '
        f'((Get-Date) -lt $deadline)) {{ Start-Sleep -Milliseconds 300 }}\n'
        f'"$(Get-Date) running installer" | Out-File -Append "{log_path}"\n'
        f'Start-Process -FilePath "{installer_path}" '
        f'-ArgumentList "/VERYSILENT","/SUPPRESSMSGBOXES","/NORESTART" -Wait\n'
        f'"$(Get-Date) installer finished" | Out-File -Append "{log_path}"\n'
        f'{restart_cmd}\n'
    )

    try:
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(
            ["powershell", "-NoProfile", "-NonInteractive",
             "-WindowStyle", "Hidden", "-Command", script],
            creationflags=creationflags,
            close_fds=True,
        )
    except Exception as exc:  # noqa: BLE001
        log.error("Failed to launch update helper: %s", exc)
        _set(phase="error", error=f"Could not launch the installer: {exc}")
        return {"ok": False, "error": str(exc)}

    _set(phase="installing")
    log.info(
        "Update helper launched for %s; app will exit so it can run.",
        state.get("latest_version"),
    )
    return {"ok": True, "restarting": True}


def quit_app_for_update(delay_seconds: float = 1.0) -> None:
    """Exit THIS process shortly after returning.

    Runs the actual exit on a background thread so the caller (a Flask
    route) can return its HTTP response to the browser first; the delay
    gives that response time to actually flush before the process holding
    the installer's target files disappears.
    """
    def _delayed_exit() -> None:
        time.sleep(delay_seconds)
        os._exit(0)  # noqa: SLF001 - deliberate: skip cleanup, we're mid-update

    threading.Thread(target=_delayed_exit, daemon=True, name="svcs-update-exit").start()

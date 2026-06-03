"""
src/gui/services/cloud_detection.py

Cloud-sync root detection and default-output-dir resolution, extracted from
gui/app.py (TASK 1.2).

Priority for cloud roots: school OneDrive -> personal OneDrive -> Google Drive
-> local outputs/. OneDrive / Google Drive for Desktop sync a local folder
automatically, so no cloud API credentials are needed — we just locate the
local mount via the registry (Windows) or well-known home paths.

Imports gui.state (for the shared status dict + the _CLOUD_SUBFOLDER constant)
and utils.paths. `_ROOT` is computed locally from __file__ (repo root); it is
only used for the final dev fallback of _default_output_dir, which the GUI test
suite never exercises (it always sets an explicit output_dir).

Author: Bloodawn (KheivenD), 2026-06-02 (gui refactor — cloud-detection extraction).
"""

from pathlib import Path

try:
    from gui.state import _state_lock, _status, _CLOUD_SUBFOLDER
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.gui.state import _state_lock, _status, _CLOUD_SUBFOLDER

try:
    from utils import paths as _paths
except ModuleNotFoundError:                # pragma: no cover - import path shim
    from src.utils import paths as _paths

# Repo root (…/src/gui/services/cloud_detection.py -> parents[3]); used only for
# the final dev fallback below.
_ROOT = Path(__file__).resolve().parents[3]


def _default_output_dir() -> str:
    """Return the canonical default output directory.

    Resolution order (FIX 1, 2026-06-03 - no implicit cloud default):
      1. The user's explicitly chosen / persisted output_dir (loaded by
         _load_gui_state() at startup, or set during a run). If the user
         picked a cloud folder in Setup, that cloud path lives here, so a
         cloud destination is only ever returned when the user chose it.
      2. A NEUTRAL LOCAL folder from ``src.utils.paths.default_videos_dir()``
         (``~/Videos/SVCS`` on Windows / Linux, ``~/Movies/SVCS`` on macOS).
      3. Repo-relative ``outputs/`` for dev clones (final fallback).

    The app NEVER falls through to a OneDrive / Google Drive / iCloud root on
    its own. Cloud roots are only OFFERED in the Setup page; selecting one
    persists it as output_dir, which is then returned by branch (1).

    Returns an absolute string path so call sites can pass it straight to
    ``Path(...)``.

    Author: Bloodawn (KheivenD), 2026-06-03 (FIX 1: explicit destination only,
    local fallback, never an implicit cloud default).
    """
    # (1) The user's explicit choice (persisted) wins.
    with _state_lock:
        cfg = _status.get("config", {})
        persisted = (cfg.get("output_dir") or "").strip()
    if persisted and Path(persisted).is_absolute():
        return persisted

    # (2) Neutral LOCAL default. Deliberately not a cloud root.
    try:
        return str(_paths.default_videos_dir())
    except Exception:  # noqa: BLE001
        pass

    # (3) Last-resort dev fallback.
    return str(_ROOT / "outputs")


# Stable identifiers for the destination "kinds" the Setup page offers.
DEST_LOCAL = "local"
DEST_DRIVE = "drive"
DEST_ONEDRIVE = "onedrive"
DEST_GDRIVE = "gdrive"
DEST_ICLOUD = "icloud"
DEST_CUSTOM = "custom"


def _detect_icloud_root() -> "Path | None":
    """Return the local iCloud Drive root if present, else None.

    Best effort and OS-specific:
      * macOS: ``~/Library/Mobile Documents/com~apple~CloudDocs``
      * Windows: ``%USERPROFILE%\\iCloudDrive`` (iCloud for Windows)
    Detection varies by install; when it cannot be found the Setup page still
    offers a Custom path the user can point at iCloud manually.
    """
    home = Path.home()
    candidates = [
        home / "Library" / "Mobile Documents" / "com~apple~CloudDocs",  # macOS
        home / "iCloudDrive",                                            # Windows
        home / "iCloud Drive",
    ]
    for c in candidates:
        try:
            if c.is_dir():
                return c
        except OSError:
            continue
    return None


def _windows_drive_roots() -> "list[Path]":
    """Return existing drive roots on Windows (C:\\, D:\\, ...). Empty elsewhere."""
    import os as _os
    if _os.name != "nt":
        return []
    import string
    roots = []
    for letter in string.ascii_uppercase:
        p = Path(f"{letter}:\\")
        try:
            if p.exists():
                roots.append(p)
        except OSError:
            continue
    return roots


def list_destinations() -> "list[dict]":
    """Enumerate OFFERED output destinations. None is ever auto-selected.

    Returns a list of option dicts the Setup page renders. Each has:
      ``kind`` (one of DEST_*), ``label`` (human text), ``path`` (suggested
      absolute path or "" for a free-form custom entry), and ``available``
      (whether the underlying root was detected). Cloud roots appear only when
      detected; otherwise the user can still use the Custom path option.

    The first entry is always the neutral LOCAL default, but it is presented as
    an option, not pre-applied - the caller decides what (if anything) to use.
    """
    out: "list[dict]" = []

    # Neutral local default (Videos/SVCS or similar).
    try:
        local = str(_paths.default_videos_dir())
    except Exception:  # noqa: BLE001
        local = str(_ROOT / "outputs")
    out.append({
        "kind": DEST_LOCAL,
        "label": "Local folder (recommended)",
        "path": local,
        "available": True,
    })

    # Drive letters (Windows) so the user can target an external/secondary disk.
    for root in _windows_drive_roots():
        out.append({
            "kind": DEST_DRIVE,
            "label": f"Drive {root.drive or str(root)}",
            "path": str(root / "SVCS"),
            "available": True,
        })

    # OneDrive (business/school preferred, then personal), only if detected.
    try:
        od_root, od_label = _detect_onedrive_root(prefer_business=True)
    except Exception:  # noqa: BLE001
        od_root, od_label = None, None
    if od_root is not None:
        out.append({
            "kind": DEST_ONEDRIVE,
            "label": od_label or "OneDrive",
            "path": str(od_root / _CLOUD_SUBFOLDER),
            "available": True,
        })

    # Google Drive for Desktop, only if detected.
    try:
        gd_root = _detect_gdrive_root()
    except Exception:  # noqa: BLE001
        gd_root = None
    if gd_root is not None:
        out.append({
            "kind": DEST_GDRIVE,
            "label": "Google Drive",
            "path": str(gd_root / _CLOUD_SUBFOLDER),
            "available": True,
        })

    # iCloud Drive, only if detected.
    icloud = _detect_icloud_root()
    if icloud is not None:
        out.append({
            "kind": DEST_ICLOUD,
            "label": "iCloud Drive",
            "path": str(icloud / _CLOUD_SUBFOLDER),
            "available": True,
        })

    # Always offer a free-form custom path.
    out.append({
        "kind": DEST_CUSTOM,
        "label": "Custom path...",
        "path": "",
        "available": True,
    })
    return out


# ── Cloud storage helpers ─────────────────────────────────────────────────────
# Priority: school OneDrive → personal OneDrive → Google Drive → local outputs/
#
# OneDrive for Desktop syncs <UserFolder>\SVCS\ automatically.
# No API credentials needed — files saved to the local folder appear in the
# cloud within seconds, exactly like Google Drive for Desktop.


def _detect_onedrive_root(prefer_business: bool = True) -> tuple[Path, str] | tuple[None, None]:
    """Return (local_root, label) for the best available OneDrive folder, or (None, None).

    Checks (in order when prefer_business=True):
      1. Windows registry – OneDrive Business/School accounts (Business1, Business2, …)
      2. Windows registry – OneDrive Personal account
      3. Profile folder scan: any 'OneDrive - *' directory (school/org accounts)
      4. Profile folder: plain 'OneDrive' directory (personal)

    Returns a label like "OneDrive - Florida Atlantic University" or "OneDrive (Personal)".
    """
    home = Path.home()

    def _reg_path(account_key: str) -> Path | None:
        try:
            import winreg
            reg_path = rf"Software\Microsoft\OneDrive\Accounts\{account_key}"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, reg_path) as key:
                val, _ = winreg.QueryValueEx(key, "UserFolder")
                p = Path(val)
                return p if p.exists() else None
        except Exception:
            return None

    if prefer_business:
        # Try up to 5 business/school accounts (Business1 … Business5)
        for n in range(1, 6):
            p = _reg_path(f"Business{n}")
            if p:
                return p, p.name  # folder name is e.g. "OneDrive - Florida Atlantic University"
        p = _reg_path("Personal")
        if p:
            return p, "OneDrive (Personal)"
    else:
        p = _reg_path("Personal")
        if p:
            return p, "OneDrive (Personal)"
        for n in range(1, 6):
            p = _reg_path(f"Business{n}")
            if p:
                return p, p.name

    # Fallback: scan home directory for OneDrive folders
    import glob as _glob
    # School/org accounts: "OneDrive - OrgName"
    if prefer_business:
        for match in _glob.glob(str(home / "OneDrive - *")):
            p = Path(match)
            if p.is_dir():
                return p, p.name
    # Personal: plain "OneDrive"
    plain = home / "OneDrive"
    if plain.exists():
        return plain, "OneDrive (Personal)"
    # macOS / any remaining
    for match in _glob.glob(str(home / "OneDrive*")):
        p = Path(match)
        if p.is_dir():
            label = "OneDrive (Personal)" if p.name == "OneDrive" else p.name
            return p, label

    return None, None


def _detect_gdrive_root() -> Path | None:
    """Return the local Google Drive for Desktop 'My Drive' root, or None."""
    home = Path.home()

    try:
        import winreg
        for key_path in (
            r"Software\Google\DriveFS\PerAccountPreferences",
            r"Software\Google\Drive\PerAccountPreferences",
        ):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                    i = 0
                    while True:
                        try:
                            sub_name = winreg.EnumKey(key, i)
                            with winreg.OpenKey(key, sub_name) as sub:
                                for val_name in ("mount_point_path", "MountPointPath"):
                                    try:
                                        mount, _ = winreg.QueryValueEx(sub, val_name)
                                        p = Path(mount)
                                        for candidate in (p / "My Drive", p):
                                            if candidate.exists() and candidate.is_dir():
                                                return candidate
                                    except FileNotFoundError:
                                        pass
                            i += 1
                        except OSError:
                            break
            except FileNotFoundError:
                pass
    except Exception:
        pass

    import string
    for letter in string.ascii_uppercase:
        for sub in ("My Drive", ""):
            p = Path(f"{letter}:\\{sub}") if sub else Path(f"{letter}:\\")
            try:
                if p.exists() and p.is_dir():
                    # Confirm it's Google Drive by looking for 'Shared drives' sibling
                    parent = p.parent if sub else p
                    if (parent / "My Drive").exists() and (parent / "Shared drives").exists():
                        return parent / "My Drive"
                    if sub == "My Drive":
                        return p
            except (PermissionError, OSError):
                pass

    for p in (home / "Google Drive" / "My Drive", home / "Google Drive", home / "My Drive"):
        try:
            if p.exists():
                return p
        except (PermissionError, OSError):
            pass

    import glob as _glob
    for pattern in (str(home / "Library/CloudStorage/GoogleDrive-*/My Drive"),):
        matches = _glob.glob(pattern)
        if matches:
            return Path(matches[0])

    return None


def _detect_cloud_root() -> tuple[Path, str, str] | tuple[None, None, None]:
    """Return (local_root, provider_label, web_url) for the best cloud sync folder.

    Priority: school OneDrive → personal OneDrive → Google Drive.
    Returns (None, None, None) if nothing is found.
    """
    od_root, od_label = _detect_onedrive_root(prefer_business=True)
    if od_root:
        # Direct link to the shared SVCS folder in the school OneDrive
        web_url = (
            "https://fau-my.sharepoint.com/:f:/g/personal/kdhaiti2024_fau_edu"
            "/IgAq7qu600dkR57LsWrnNVvxAVt09vkarwuHEjxfcDwDF4w?e=kg15Bf"
            if "Personal" not in od_label
            else "https://onedrive.live.com"
        )
        return od_root, od_label, web_url

    gd_root = _detect_gdrive_root()
    if gd_root:
        return gd_root, "Google Drive", "https://drive.google.com/drive/folders/1r032XVGXJeUYDZrw4eDdyXwZYCsbiH99"

    return None, None, None

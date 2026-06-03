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

    Resolution order:
      1. Persisted output_dir from the last pipeline run (loaded by
         _load_gui_state() at startup from the platform state file).
      2. The user's videos folder discovered by
         ``src.utils.paths.default_videos_dir()`` (``~/Videos/SVCS`` on
         Windows / Linux, ``~/Movies/SVCS`` on macOS).
      3. Cloud sync root (OneDrive school / personal / Google Drive)
         ONLY when the user has explicitly opted in by toggling
         ``Prefer cloud output`` in the dashboard. This was previously
         baked in as the default, which surprised users who didn't
         have OneDrive and made the app harder to package as an
         installer. As of 2026-05-14 it's opt-in.
      4. Repo-relative ``outputs/`` for dev clones with no other
         signal (final fallback).

    Returns an absolute string path so call sites can pass it straight
    to ``Path(...)``.

    Author: Bloodawn (KheivenD), 2026-05-14 (productization: OneDrive
    no longer the implicit default).
    """
    # (1) Restore last-known output_dir from persistent state.
    with _state_lock:
        cfg = _status.get("config", {})
        persisted = (cfg.get("output_dir") or "").strip()
    if persisted and Path(persisted).is_absolute():
        return persisted

    # (3) Cloud sync, only when explicitly opted in.
    try:
        cfg_prefer_cloud = (cfg or {}).get("prefer_cloud_output", False)
    except Exception:  # noqa: BLE001
        cfg_prefer_cloud = False
    if cfg_prefer_cloud:
        try:
            cloud_root, _label, _url = _detect_cloud_root()
            if cloud_root is not None:
                return str(cloud_root / _CLOUD_SUBFOLDER)
        except Exception:  # noqa: BLE001
            pass

    # (2) Platform default (Videos / Movies / Videos folder + SVCS).
    try:
        return str(_paths.default_videos_dir())
    except Exception:  # noqa: BLE001
        pass

    # (4) Last-resort dev fallback.
    return str(_ROOT / "outputs")


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

#!/usr/bin/env python3
"""
run_gui.py  —  Launch the SVCS web dashboard.

Usage:
    python run_gui.py              # default: http://localhost:5000
    python run_gui.py --port 8080  # custom port
    python run_gui.py --host 0.0.0.0 --port 5000  # accessible over LAN

The dashboard opens in your browser at http://localhost:5000.
Drop your test videos into the data/ folder and click the ⟳ button
to find them automatically.

On first start (or whenever pyproject.toml has changed), this script
runs ``uv sync --extra enhance`` to install the Real-ESRGAN
super-resolution stack. The YOLO object filter is already in the core
deps; no extra needed.

The ``plates`` extra is premium-only and not pulled in by default. If
you're building the premium edition (or a developer who wants the
plate reader locally), add it manually:

    uv sync --extra enhance --extra plates

If ``uv`` isn't on PATH or the install fails, the dashboard still
launches — relevant features just degrade gracefully (Real-ESRGAN
falls back to bicubic, plate reader hides its UI when no backend is
installed, YOLO falls back to pass-through if ultralytics is missing).

Pass ``--no-sync`` to skip the dependency check entirely.

Author: Bloodawn (KheivenD)
"""

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from threading import Timer

# Make src/ importable regardless of working directory
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Note: do NOT import gui.app at module load time. We want the optional
# `enhance` and `plates` extras installed first (see _ensure_extras_installed
# below) so that gui.app's lazy imports of paddleocr / realesrgan find them
# on the first request after a fresh clone.
# Author: Bloodawn (KheivenD), 2026-05-03.

_REPO_ROOT = Path(__file__).parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_UV_LOCK   = _REPO_ROOT / "uv.lock"

# The uv sync stamp tracks whether pyproject.toml + uv.lock have changed
# since the last successful auto-install. It lives in the platform cache
# dir (e.g. %LOCALAPPDATA%\SVCS on Windows, ~/Library/Caches/SVCS on
# macOS) so the installed app can write it without needing access to
# the repo root. Importing src.utils.paths also kicks off a one-time
# migration of any pre-existing state files from the repo root to the
# new platform locations.
# Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).
try:
    sys.path.insert(0, str(_REPO_ROOT / "src"))
    from utils.paths import cache_dir as _cache_dir  # noqa: E402
    _SYNC_STAMP = _cache_dir() / "uv_sync_stamp"
except Exception:  # noqa: BLE001
    # If platformdirs isn't installed yet (very first launch on a fresh
    # clone, before uv sync has run), fall back to the old repo-root
    # location. After the first sync this path won't be hit again.
    _SYNC_STAMP = _REPO_ROOT / ".uv_sync_stamp"


def _pyproject_fingerprint() -> str:
    """Hash the inputs that would change what `uv sync` resolves.

    If pyproject.toml or uv.lock changes, we need to re-sync. Otherwise
    we can skip the sync entirely on subsequent launches.
    """
    h = hashlib.sha256()
    for f in (_PYPROJECT, _UV_LOCK):
        try:
            h.update(f.read_bytes())
        except FileNotFoundError:
            h.update(f"missing:{f.name}".encode())
    return h.hexdigest()


def _running_inside_uv() -> bool:
    """Best-effort detection of whether we were spawned by ``uv run``.

    When the user runs ``uv run python run_gui.py`` instead of plain
    ``python run_gui.py``, uv has already sync'd the venv before
    handing us control. Spawning *another* ``uv sync`` from inside
    that uv-managed process can:
      • print a redundant lock-acquired/released noise wall, or
      • on Windows, briefly fail with "the process cannot access the file
        because it is being used by another process" while uv still holds
        the project lock — which surfaces to the user as an error message
        even though the dashboard would otherwise start fine.

    uv exposes ``UV_PROJECT_ENVIRONMENT`` (and reliably sets ``VIRTUAL_ENV``
    + ``UV``) when invoking commands via ``uv run``. We treat presence of
    either as a strong hint and skip the recursive sync — uv has already
    installed whatever the lockfile says, including extras passed on the
    command line.

    Author: Bloodawn (KheivenD), 2026-05-03 (run_gui hardening).
    """
    if os.environ.get("UV_PROJECT_ENVIRONMENT"):
        return True
    # `uv run` exports its own binary path so children can invoke it back.
    if os.environ.get("UV"):
        return True
    # Fallback: if VIRTUAL_ENV points inside the repo's .venv AND the
    # parent process command line mentions uv. Cheap heuristic.
    venv = os.environ.get("VIRTUAL_ENV", "")
    if venv and Path(venv).resolve().parent == _REPO_ROOT:
        # We're already inside the project venv — running another sync
        # would just churn for nothing.
        return True
    return False


def _ensure_extras_installed(extras: list[str], skip: bool = False) -> None:
    """Run ``uv sync --extra X --extra Y`` once when inputs change.

    Idempotent: writes a stamp file with the pyproject+lock hash and
    skips on subsequent launches if nothing relevant changed. Best-effort
    — failures log a warning and never block dashboard startup.

    Skips entirely when invoked under ``uv run`` (see _running_inside_uv);
    that path expects extras to be passed on the uv-run command line, e.g.:
        uv run --extra enhance --extra plates python run_gui.py

    Author: Bloodawn (KheivenD)
    """
    if skip:
        print("  [skip] --no-sync passed, not running uv sync")
        return

    if _running_inside_uv():
        # uv already managed the venv — don't recurse. Print a hint about
        # how to pull in the AI extras under uv run.
        print("  [skip] running inside `uv run` — uv already sync'd the venv")
        print("         If AI features ('enhance', 'plates') are missing, exit and run:")
        print("           uv run --extra enhance --extra plates python run_gui.py")
        return

    fingerprint = _pyproject_fingerprint()
    last = _SYNC_STAMP.read_text().strip() if _SYNC_STAMP.exists() else ""
    if last == fingerprint:
        # Inputs unchanged since last successful sync — nothing to do.
        print(f"  [ok]   extras already in sync ({', '.join(extras)})")
        return

    uv = shutil.which("uv")
    if not uv:
        print("  [warn] 'uv' not on PATH; skipping auto-install of extras")
        print("         Install uv from https://astral.sh/uv to enable AI features,")
        print("         or run `pip install paddleocr realesrgan basicsr` manually.")
        return

    cmd = [uv, "sync"]
    for ex in extras:
        cmd.extend(["--extra", ex])
    print(f"  [sync] {' '.join(cmd)}")
    print( "         (one-time install — only re-runs when pyproject/uv.lock changes)")
    t0 = time.perf_counter()
    try:
        # Inherit stdout/stderr so the operator can see download progress.
        result = subprocess.run(cmd, cwd=_REPO_ROOT, check=False)
        dt = time.perf_counter() - t0
        if result.returncode == 0:
            _SYNC_STAMP.write_text(fingerprint)
            print(f"  [ok]   uv sync finished in {dt:.1f}s")
        else:
            print(f"  [warn] uv sync exited {result.returncode} after {dt:.1f}s — "
                  "extras may not be installed. Dashboard will start anyway.")
    except Exception as exc:  # noqa: BLE001
        print(f"  [warn] uv sync raised {type(exc).__name__}: {exc}")
        print(f"         Dashboard will start anyway with missing extras.")


def _open_browser(host: str, port: int):
    h = "localhost" if host == "0.0.0.0" else host
    webbrowser.open(f"http://{h}:{port}")


def main():
    """Entry point usable from a frozen launcher or `python -m run_gui`.

    Previously the entire startup sequence lived inside the
    ``if __name__ == "__main__":`` block. That worked for `python
    run_gui.py` but made it impossible for the PyInstaller launcher
    (installer/launcher.py) to call us without spawning a subprocess.
    Wrapping it in a function lets the frozen exe import and invoke
    main() directly, which is faster and gives us proper exception
    propagation back into the launcher's friendly error dialog.
    Behavior is unchanged for source-mode runs.
    Author: Bloodawn (KheivenD), 2026-05-14 (installer prep).
    """
    # Frozen Windows builds run with a hidden console whose default code page is
    # cp1252. Our banners and pipeline logs use box-drawing glyphs (━), which
    # raise UnicodeEncodeError on cp1252 and crash the app on launch (caught by
    # the installer smoke test). Force UTF-8 (best effort) before anything
    # prints — this also reconfigures the same sys.stderr object the logging
    # console handler binds to. Author: Bloodawn (KheivenD), 2026-06-02
    # (frozen-console encoding fix, surfaced by the M1 TASK 1.4 smoke test).
    for _stream in (sys.stdout, sys.stderr):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - older/odd streams may lack reconfigure
            pass

    parser = argparse.ArgumentParser(description="SVCS Web Dashboard")
    parser.add_argument("--host", default="0.0.0.0",
                        help="Bind address (default: 0.0.0.0, accessible on LAN). "
                             "Use 127.0.0.1 to restrict to this machine only.")
    parser.add_argument("--port", type=int, default=5000, help="Port (default: 5000)")
    parser.add_argument("--no-browser", action="store_true",
                        help="Don't auto-open browser")
    parser.add_argument("--no-sync", action="store_true",
                        help="Skip the auto `uv sync --extra enhance --extra plates` "
                             "check that runs when pyproject.toml has changed.")
    parser.add_argument("--username", default=None,
                        help="Dashboard Basic-Auth username (or set "
                             "SVCS_DASHBOARD_USER). Required for non-localhost binds.")
    parser.add_argument("--password", default=None,
                        help="Dashboard Basic-Auth password (or set "
                             "SVCS_DASHBOARD_PASSWORD).")
    parser.add_argument("--no-auth", action="store_true",
                        help="Allow a non-localhost bind WITHOUT authentication "
                             "(not recommended on an untrusted network).")
    args = parser.parse_args()

    # ── Build edition (R4 Phase 4) ──────────────────────────────────────
    # The "field" (offline, local-compression-only) build force-binds to
    # 127.0.0.1 - it has no server surface (no RTSP/HLS, TOOLS hidden) and must
    # never be exposed on the network - and turns telemetry off (offline).
    try:
        from gui.edition import get_edition, is_field
        _edition = get_edition()
    except Exception:  # noqa: BLE001
        _edition = "server"
        is_field = lambda e=None: False  # noqa: E731
    if is_field(_edition):
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print(f"  [field] offline build: overriding --host {args.host} -> 127.0.0.1 "
                  "(the field build is local-only and never binds the network).")
        args.host = "127.0.0.1"
        # Offline build: hard kill-switch on usage stats (utils.usage_stats
        # honours SVCS_DISABLE_USAGE_STATS even if consent was previously given).
        os.environ["SVCS_DISABLE_USAGE_STATS"] = "1"
        os.environ.setdefault("SVCS_EDITION", "field")

    # ── Crash reporting (opt-in) ────────────────────────────────────────
    # Wire Sentry BEFORE we import gui.app so unhandled errors during
    # Flask startup are also captured. The helper is a no-op unless the
    # user has both installed sentry-sdk (via the [crash-reporting] extra)
    # and set SVCS_ENABLE_SENTRY=1 with a valid SENTRY_DSN. The casual
    # install never phones home. See src/utils/crash_reporting.py for the
    # full PII / scrubbing policy.
    # Author: Bloodawn (KheivenD), 2026-05-14 (audit item: crash reporting).
    try:
        from utils.crash_reporting import init_crash_reporting
        init_crash_reporting()
    except Exception:  # noqa: BLE001
        # Crash reporting must NEVER block the app from launching. If
        # anything goes wrong here we silently fall back to no Sentry.
        pass

    print(f"\n{'━'*55}")
    print(f"  SVCS Dashboard")
    print(f"  http://{args.host}:{args.port}")
    print(f"{'━'*55}")
    # Make sure the AI extras are installed before we load the Flask app
    # (gui.app imports modules that lazily reference paddleocr/realesrgan).
    # First-run: ~1-3 minutes for the heavy installs; subsequent launches
    # are instant because the stamp file matches.
    # The casual / open-source edition only auto-installs `enhance`.
    # `plates` is premium-only and intentionally NOT pulled in here. If
    # you're building the premium edition, edit this list locally or
    # pass --extra plates to your launch wrapper before calling this
    # script. Author: Bloodawn (KheivenD), 2026-05-14 (premium split).
    _ensure_extras_installed(["enhance"], skip=args.no_sync)

    print(f"{'━'*55}")
    print(f"  Drop test videos into:  {Path('data').resolve()}")
    print(f"  Outputs written to:     {Path('outputs').resolve()}")
    print(f"  Press Ctrl+C to stop.")
    print(f"{'━'*55}\n")

    # Import the Flask app NOW (after extras are installed) so any
    # top-level imports inside gui.app see the new packages. Wrapped
    # with a friendly error message because a missing core dep here
    # used to surface as an opaque ImportError dump.
    # Author: Bloodawn (KheivenD), 2026-05-03 (run_gui hardening).
    try:
        # Use the app factory so the always-on hardware sampler starts (it is
        # no longer started at import time as of the TASK 1.2 gui refactor).
        from gui.app import create_app  # noqa: E402
        app = create_app()
    except ModuleNotFoundError as exc:
        missing = exc.name or str(exc)
        print(f"\n  [fatal] Could not import gui.app — missing module: {missing!r}")
        print( "          Most likely a core dependency wasn't installed in this venv.")
        print( "          Try one of:")
        print( "            • uv sync                                  (installs core deps)")
        print( "            • uv run --extra enhance --extra plates python run_gui.py")
        print( "            • pip install -e .                          (if not using uv)")
        print(f"          Full error: {exc}")
        sys.exit(2)
    except Exception as exc:  # noqa: BLE001
        print(f"\n  [fatal] Could not import gui.app — {type(exc).__name__}: {exc}")
        print( "          Run with PYTHONFAULTHANDLER=1 or python -X dev for more detail.")
        raise

    # ── Dashboard auth policy (TASK 4.4) ────────────────────────────────
    # A non-localhost bind exposes the dashboard on the network; require auth
    # (or an explicit --no-auth) before we ever call app.run().
    try:
        from gui.auth import (decide_auth, install_basic_auth, AuthConfigError,
                              bind_exposure_warning)
        decision = decide_auth(args.host, no_auth=args.no_auth,
                               username=args.username, password=args.password)
    except AuthConfigError as exc:
        print(f"\n  [fatal] {exc}")
        sys.exit(2)
    if decision.auth_enabled:
        install_basic_auth(app, decision.username, decision.password)
        print(f"  Dashboard auth:  ENABLED (user {decision.username!r})")
    elif decision.auth_required:
        print("  Dashboard auth:  DISABLED via --no-auth - exposed on the "
              f"network at {args.host} with NO login.")

    # M0.8: say it out loud when the bind reaches past the local machine.
    _exposure = bind_exposure_warning(args.host)
    if _exposure:
        print(f"\n  [warn] {_exposure}\n")

    if not args.no_browser:
        Timer(1.2, _open_browser, args=[args.host, args.port]).start()

    try:
        app.run(host=args.host, port=args.port, debug=False, threaded=True)
    except OSError as exc:
        # Port already in use is the most common Flask startup failure.
        # Win32 reports it as WinError 10048; Linux/macOS as EADDRINUSE.
        if "10048" in str(exc) or "Address already in use" in str(exc):
            print(f"\n  [fatal] Port {args.port} is already in use on {args.host}.")
            print( "          Either close the other process, or pass a different port:")
            print(f"            python run_gui.py --port {args.port + 1}")
            sys.exit(3)
        raise


if __name__ == "__main__":
    main()

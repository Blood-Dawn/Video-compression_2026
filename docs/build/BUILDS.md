# SVCS builds: Server vs Field (R4 Phase 4)

SVCS ships as two downloadable builds from one codebase. Which one runs is
decided by the `SVCS_EDITION` env var, or a bundled `edition.txt` marker the
PyInstaller spec writes into the frozen bundle, defaulting to **server**.

| | **SVCS (Server)** | **SVCS-Field (offline)** |
|---|---|---|
| Who it's for | Make a server: a shop / NAS / operator running a dashboard for others | A technician in the field compressing footage on a laptop, offline |
| Bind | localhost by default; can bind LAN (`--host 0.0.0.0`, auth required) | **forced 127.0.0.1** - never binds the network |
| Auth | Basic-Auth required for any non-localhost bind (`gui/auth.py`) | not needed (localhost-only) |
| RTSP server (MediaMTX) | yes (TOOLS tab) | **removed** (route not registered) |
| HLS live streaming | yes (TOOLS tab) | **removed** (route not registered) |
| TOOLS tab | shown | hidden |
| Telemetry | opt-in usage stats (off by default) | **hard kill-switch** (`SVCS_DISABLE_USAGE_STATS=1`) |
| Local compression, all modes/codecs (incl. NVENC) | yes | yes |
| Library, auto-compress (LOCAL folders), retention, encrypt, plates, metrics | yes | yes |
| Exe / folder | `dist/SVCS/SVCS.exe` | `dist/SVCS-Field/SVCS-Field.exe` |

The field build keeps auto-compress and retention on purpose: watching a local
folder and bounding its size is exactly a field technician's workflow. It drops
only the two genuine *server-making* surfaces (RTSP + HLS), so it has no network
server at all.

## How the edition is resolved (`src/gui/edition.py`)
1. `SVCS_EDITION` env var (`server` | `field`) - highest priority.
2. `edition.txt` marker at the frozen bundle root (via `sys._MEIPASS` /
   `SVCS_BUNDLE_ROOT`) - what the two builds ship.
3. default `server` - so source runs and the whole test suite are unchanged.

`register_blueprints(app, edition=...)` drops `rtsp_bp` + `hls_bp` in the field
edition; `ui_bp` injects the edition into the template (`server_features`), which
gates the TOOLS tab and sets `window.SVCS_SERVER_FEATURES`; `run_gui.main()`
force-binds localhost and sets the telemetry kill-switch when field.

## Building the two exes (owner-run)
PyInstaller is not part of the CI test run (like the winget/Inno steps - see
docs/BLOCKERS.md); build these on Windows with the venv active:

```powershell
# Server build -> dist/SVCS/SVCS.exe
pwsh installer/build.ps1

# Field build  -> dist/SVCS-Field/SVCS-Field.exe
pwsh installer/build.ps1 -Edition field
```

Both come from `installer/svcs.spec`, parameterized by `SVCS_BUILD_EDITION`
(the script sets it): the spec picks the exe name and writes the runtime
`edition.txt` marker into the bundle.

## Dev-testing an edition from source
```bash
# Field mode from source (forces localhost, hides TOOLS, no telemetry):
SVCS_EDITION=field python run_gui.py           # bash
$env:SVCS_EDITION='field'; python run_gui.py   # PowerShell
```
(Or drop a one-line `edition.txt` containing `field` at the repo root - it is
gitignored so it never leaks into a commit.)

## What is NOT split
- The **Docker image** stays the server scenario (Dockerfile / docker-compose).
- The **Inno Setup installer** (`svcs.iss`) currently packages the server build;
  a `SVCS-Field` installer is a straightforward copy with the field exe/name and
  no MediaMTX component - owner-gated alongside the existing installer work.

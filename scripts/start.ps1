# start.ps1 - launch the SVCS dashboard from source with the Real-ESRGAN
# enhancement extra (GPU super-resolution when CUDA torch is present).
# Usage (from anywhere):  .\scripts\start.ps1  [--port 8080 ...]
# Moved from the repo root to scripts/ on 2026-09-24; it now changes to the
# repo root itself so run_gui.py and pyproject.toml are found.

Push-Location (Join-Path $PSScriptRoot '..')
try {
    uv run --extra enhance python run_gui.py @args
} finally {
    Pop-Location
}

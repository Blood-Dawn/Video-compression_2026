# SVCS Linux AppImage

A single self-contained `SVCS-x86_64.AppImage` that runs the dashboard on a clean
Ubuntu (or most modern Linux) with **no Python, FFmpeg, or pip required**.

## What's inside

`installer/build.sh` assembles an AppDir and packages it with `appimagetool`:

- a **relocatable standalone CPython** (via `uv python`),
- the project on the **slim ONNX path** (no torch),
- the `yolov8n.onnx` detection model,
- a **static FFmpeg** (on PATH inside the image),
- `AppRun` (launches the bundled Python on `run_gui.py`) + a `.desktop` entry.

## Build

Linux only (needs `appimagetool`; runs in CI on `ubuntu-latest`):

```bash
./installer/build.sh
# -> dist/SVCS-x86_64.AppImage
```

CI builds and smoke-tests it on every `v*` tag and on manual dispatch
(`.github/workflows/appimage.yml`), then uploads it as an artifact. Publishing it
to a GitHub Release is the owner's gated step (see `docs/RELEASE-CHECKLIST.md`).

## Run

```bash
chmod +x SVCS-x86_64.AppImage
./SVCS-x86_64.AppImage              # dashboard at http://localhost:5000
```

Binding to a non-localhost address requires auth (see the dashboard auth policy
in `docs/deployment_packaging.md`).

## Notes

- The icon shipped by `build.sh` is a placeholder — replace `svcs.png` with real
  branding before GA.
- No code-signing is needed for AppImages (unlike the Windows installer).

*Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5b.2).*

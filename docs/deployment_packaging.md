# Deployment Packaging Research

**EGN 4950C Group 16**
**Date:** April 29, 2026

This document summarizes deployment packaging options for SVCS and their tradeoffs for DoD network environments. The sponsor (Cody Hayashi) identified two deployment scenarios in the April 15 meeting: a server-hosted web app (primary) and a standalone laptop app for field use with no network (secondary).

---

## Deployment scenarios

**Scenario A — Server deployment (primary)**
One machine runs the Flask server. Operators connect from any browser on the same network. Getting a web app on a standalone DoD server is generally easier than installing software on individual endpoints. Our current stack (Flask + vanilla HTML/JS, no React, no CDN dependencies) is already compliant with the restrictions Cody described.

**Scenario B — Field laptop (secondary)**
No network available. The operator plugs a laptop directly into the camera. Everything runs locally. Cody said this is a real scenario Geena described. In this case the user needs a single package they can install on a DoD laptop, which involves the DoD software approval process.

---

## Dashboard authentication (Scenario A — required before LAN exposure)

Scenario A serves the dashboard on the network (`--host 0.0.0.0`), so it must
not be open to everyone on that network. As of TASK 4.4 the server enforces a
bind-aware policy (`src/gui/auth.py`):

- **Localhost bind (`127.0.0.1`)** — no authentication required (the
  single-machine / field-laptop case, Scenario B). Auth is still enabled if you
  supply credentials.
- **Any other bind (`0.0.0.0`, a LAN IP, …)** — HTTP Basic Auth is **required**.
  The server **refuses to start** unless you either configure credentials or
  explicitly opt out.

Configure credentials with environment variables (preferred — keeps them out of
the process list) or CLI flags:

```bash
# Recommended: env vars
export SVCS_DASHBOARD_USER=operator
export SVCS_DASHBOARD_PASSWORD='a-long-random-passphrase'
python run_gui.py --host 0.0.0.0

# Or via flags
python run_gui.py --host 0.0.0.0 --username operator --password '…'

# Explicit, deliberate opt-out (NOT recommended on an untrusted network):
python run_gui.py --host 0.0.0.0 --no-auth
```

If you bind beyond localhost without credentials and without `--no-auth`, the
server prints a fatal message and exits (`exit 2`) rather than coming up
unprotected. Basic Auth is transport-plaintext, so terminate TLS at a reverse
proxy (nginx/Caddy) or the container ingress for anything beyond a trusted LAN.
The Docker image (below) should pass these env vars through.

## Option 1: Docker container (recommended for Scenario A)

Package the Flask app, uv environment, and FFmpeg into a Docker image. Run with:

```bash
docker run -p 5000:5000 -v /camera/output:/app/outputs svcs:latest
```

**Pros:**
- Reproducible environment — the exact Python version, dependencies, and FFmpeg binary are bundled
- Easy to update: push a new image, restart the container
- Works on any Linux host regardless of what the server has installed
- DoD has an approved container registry process (IronBank / Platform One)

**Cons:**
- Docker daemon itself must be approved on the target server
- IronBank hardened base images add build complexity

**Status: IMPLEMENTED** (TASK 4.2). The repo ships a `Dockerfile` and
`docker-compose.yml`. The image builds on the **slim ONNX path** (post-M2): object
detection runs on ONNX Runtime, not torch. The built image is ~2 GB (Debian +
apt ffmpeg with all codecs + onnxruntime + opencv and their transitive deps) —
still well under the 4 GB+ a torch/CUDA image would be, and it could be trimmed
further with a multi-stage build or ffmpeg's slimmer variants. FFmpeg comes from the distro
(`apt install ffmpeg`, on PATH — `utils.ffmpeg` resolves it). Dependencies install
from the committed `uv.lock` for reproducibility, and the `yolov8n.onnx` detection
model is baked in.

```bash
# Compose (recommended) — set a real password first:
SVCS_DASHBOARD_PASSWORD='a-long-passphrase' docker compose up --build
# open http://localhost:5000  (log in with operator / your-password)

# Or plain docker:
docker build -t svcs:latest .
docker run -p 5000:5000 \
  -e SVCS_DASHBOARD_USER=operator -e SVCS_DASHBOARD_PASSWORD='…' \
  -v "$PWD/outputs:/app/outputs" -v "$PWD/data:/app/data:ro" svcs:latest
```

Because the container binds `0.0.0.0`, the TASK 4.4 auth policy applies: pass the
`SVCS_DASHBOARD_USER` / `SVCS_DASHBOARD_PASSWORD` env vars (compose wires them
through) or the container exits rather than serving an unauthenticated dashboard.
Terminate TLS at a reverse proxy / ingress for anything past a trusted LAN. The
artifacts are guarded by `tests/test_docker_artifacts.py` (static checks always;
a real build+serve test under `SVCS_TEST_DOCKER=1`).

---

## Option 2: PyInstaller single-file executable (Scenario B)

Bundle the entire Python environment into a single `.exe` (Windows) or binary (Linux/macOS) that the user double-clicks.

**Pros:**
- No Python install required on the target machine
- One file to copy and approve
- Works offline

**Cons:**
- FFmpeg must still be installed separately (PyInstaller bundles Python, not system tools)
  - Alternative: bundle a static FFmpeg binary inside the PyInstaller package using `--add-binary`
- First run extracts files to a temp directory — can trigger antivirus on DoD machines
- Rebuilding requires the exact same OS target (Windows EXE built on Windows, etc.)
- cv2, torch, and realesrgan have complex binary dependencies that PyInstaller sometimes misses
- Build time is 5–15 minutes; the resulting bundle is 500 MB–1.5 GB

**Cody's guidance:** "If it takes an hour, go for it. If it's going to be a day or more, skip it." PyInstaller for a Flask + OpenCV + torch stack reliably takes more than a day to tune. The Electron wrapper below is lower risk.

**Status:** Not recommended as a primary path. Could work as a fallback if Electron is not viable.

---

## Option 3: Electron shell + Flask subprocess (Scenario B, recommended)

Package the Flask app as a Python subprocess launched by an Electron main process. Electron provides the UI shell (a browser window), and Flask handles all the logic.

```
Electron main.js  →  spawns:  uv run python src/gui/app.py
                  →  opens:   BrowserWindow(http://localhost:5000)
```

**Pros:**
- The existing GUI (Flask + HTML/JS) requires zero changes — Electron just wraps it
- Ships as a standard installer (.exe on Windows, .dmg on macOS, .deb/.rpm on Linux)
- Python environment handled by uv — bundled as a `dist/` folder alongside Electron
- FFmpeg can be bundled inside the Electron package (ffmpeg-static npm package)
- No React, no CDN — already compliant with the restriction Cody mentioned
- Cody explicitly called this out as a viable path: "Electron shell that launches the Flask backend as a subprocess would work"

**Cons:**
- Electron itself adds ~150 MB of Chromium to the package
- The DoD laptop approval process still applies (same process as any installer)
- Python must be bundled or pre-installed; bundling with pyinstaller --onedir inside Electron is the cleanest but adds size

**Implementation notes:**
```javascript
// Electron main.js sketch
const { app, BrowserWindow } = require('electron')
const { spawn } = require('child_process')
const path = require('path')

let flaskProcess = null

app.whenReady().then(() => {
  // Start Flask backend
  flaskProcess = spawn('uv', ['run', 'python', 'src/gui/app.py'], {
    cwd: path.join(__dirname, '..'),
    stdio: 'pipe',
  })

  // Wait for Flask to be ready, then open window
  setTimeout(() => {
    const win = new BrowserWindow({ width: 1280, height: 900 })
    win.loadURL('http://localhost:5000')
  }, 2000)
})

app.on('will-quit', () => {
  if (flaskProcess) flaskProcess.kill()
})
```

**Status:** Tracked as ROADMAP.md section 4.7 (stretch goal). Estimated effort: 2–4 hours for basic working version.

---

## Option 4: Tarball + setup script (lightweight server option)

A `tar.gz` archive with the source tree, `uv.lock`, a bundled static FFmpeg binary, and a `setup.sh` that runs `uv sync` and then `uv run python src/gui/app.py`. No container needed.

**Pros:**
- Smallest deliverable size
- Zero special tools required — just uv and bash
- Easiest to audit (plain source code, no compiled bundle)
- uv handles Python version isolation automatically

**Cons:**
- The target machine needs uv installed, and uv needs internet access for its first run (or you pre-bundle the cache)
- Not a user-friendly installer — operators need to know how to run a shell script
- FFmpeg still needs to be a compatible static binary for the target OS/architecture

**This is probably the best option for a DoD server handoff** where a sysadmin will do the install, not an operator.

**Rough structure:**
```
svcs-1.0.tar.gz
  ├── src/
  ├── pyproject.toml
  ├── uv.lock
  ├── bin/
  │   └── ffmpeg          (static Linux amd64 binary from https://johnvansickle.com/ffmpeg/)
  ├── setup.sh            (uv sync && echo "Run: uv run python src/gui/app.py")
  └── README.md
```

---

## NDAA compliance notes

Section 889 of the 2019 NDAA prohibits DoD procurement of systems using telecommunications equipment or services from five banned vendors (Huawei, ZTE, Hytera, Hikvision, Dahua). This affects hardware procurement but does not directly restrict our software stack.

What does matter for software on a DoD network:

1. **No banned country-of-origin components.** Our stack is: Python (PSF), Flask (Pallets Project), OpenCV (open source), FFmpeg (open source), PyTorch (Meta AI, open source). None of these are from the banned vendors.

2. **Section 889 cameras.** If SVCS is deployed with a Hikvision or Dahua camera, the camera hardware is the compliance problem, not our software. We read RTSP streams; we don't control what camera generates them.

3. **FOSS license review.** Flask (BSD-3), OpenCV (Apache 2.0), FFmpeg (LGPL/GPL depending on build), PyTorch (BSD-3), hls.js (Apache 2.0), video.js (Apache 2.0). The GPL components in FFmpeg require us to link dynamically or provide build instructions — we already do the latter (FFmpeg is a system install, not bundled).

4. **RealESRGAN / basicsr.** BSD-3 license. No compliance issue.

5. **uv (Astral).** Apache 2.0. Sean from NIWC specifically recommended this package manager; it is already approved in their workflow.

---

## Recommendation

| Scenario | Recommended packaging | Estimated effort |
|----------|----------------------|-----------------|
| DoD server (sysadmin install) | Tarball + uv + static FFmpeg | 2–3 hours |
| Field laptop (operator install) | Electron + Flask subprocess | 2–4 hours |
| Cloud/containerized deployment | Docker (IronBank base) | 4–8 hours |

For the May 6 deadline, the tarball approach is the most achievable and the most transparent for security review. The Electron wrapper is a stretch goal that would be high-value if we have time after the tarball works.

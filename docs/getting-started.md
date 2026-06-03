# Getting started with SVCS

SVCS shrinks surveillance footage by keeping what moves at full quality and
compressing the dead background hard. This guide takes you from install to your
first compressed clip in a few minutes.

---

## 1. Install

**Windows (easiest)**
1. Download the latest `SVCS-Setup-*.exe` from the
   [Releases page](https://github.com/Blood-Dawn/Video-compression_2026/releases/latest).
2. (Recommended) verify the download - see the
   [download page](site/index.html) for the SHA-256 steps.
3. Run the installer and launch **SVCS** from the Start menu. The dashboard opens
   in your browser at `http://localhost:5000`.

> The beta installer is **unsigned**, so Windows SmartScreen will warn you.
> Choose *More info → Run anyway*. A signed build is planned.

**Docker (server)**
```bash
SVCS_DASHBOARD_PASSWORD='a-long-passphrase' docker compose up --build
# then open http://localhost:5000  (log in: operator / your-password)
```
See [`deployment_packaging.md`](deployment_packaging.md).

**From source**
```bash
uv sync
uv run python run_gui.py
```

---

## 2. Point it at video

You can feed SVCS three ways - pick whichever matches your setup:

- **A folder of clips** (camera exports, microSD dumps, NVR exports). Use the
  watch-folder so new files are compressed automatically:
  ```bash
  python src/utils/watchfolder.py --watch-dir <folder> --output <out> --profile motion_events
  ```
- **A live camera** (RTSP/ONVIF). In the dashboard, open the source panel and
  click **Discover ONVIF cameras**, or paste the camera's `rtsp://…` URL.
- **A single file**, by dropping it into `data/` and selecting it in the
  dashboard.

See [`camera-ingestion.md`](camera-ingestion.md) for the full per-camera guide,
including cloud-locked cameras (Ring/Nest/Arlo).

---

## 3. Choose a preset and compress

You don't pick "Mode 0-3" - you pick **what the camera is watching**:

- **Continuous CCTV** - a 24/7 static camera; biggest storage win.
- **Motion-event cam / Doorbell** - mostly idle with occasional events.
- **Active scene** - a busy street/lobby with near-constant motion.
- **Archive** - evidence/retention where quality matters most.

Or let SVCS pick for you: content auto-detection analyzes the first ~30 seconds
and recommends a preset. Hit **Start** and watch the live size savings.

Compressed segments are written to your output folder (default `outputs/`, or a
detected OneDrive/Google Drive folder). Original files are never modified.

---

## 4. Where to go next

- **Cameras:** [`camera-ingestion.md`](camera-ingestion.md) - RTSP/ONVIF,
  watch-folder profiles, and the bridge path for cloud-locked cameras.
- **Server deployment & auth:** [`deployment_packaging.md`](deployment_packaging.md).
- **Privacy:** usage stats are **off by default** and never include footage,
  filenames, or paths - opt in from the first-run banner if you'd like to help.

---

*Author: Bloodawn (KheivenD), 2026-06-03 (TASK 5.3 - getting started).*

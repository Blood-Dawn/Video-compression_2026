# Camera ingestion

SVCS compresses footage from cameras three ways. Pick the one your camera
supports — there is no vendor-cloud scraping, ever.

| Path | Works for | How |
|------|-----------|-----|
| **1. Direct RTSP / ONVIF** | Cameras that expose an RTSP stream on your LAN (Reolink, Amcrest, Hikvision, Dahua, Axis, many Tapo/Wyze with RTSP firmware) | SVCS discovers the camera and pulls its live stream. |
| **2. Export / watch-folder** | *Any* camera that can write or export clips to a folder (microSD dumps, NVR exports, NAS sync, even Ring/Nest/Arlo via their **export** feature) | SVCS watches a folder and compresses new files automatically. **Universal.** |
| **3. Bridge** | Cloud-locked cameras (Ring/Nest/Arlo) with no RTSP and no usable export | A local bridge (Home Assistant / Scrypted / Frigate) re-exposes the camera as RTSP, which SVCS then ingests as path 1. *(See "Bridge ingestion" below.)* |

If your camera supports more than one, prefer **1 (direct RTSP)** for live
recording and **2 (export-folder)** for bulk/after-the-fact compression.

---

## 1. Direct RTSP / ONVIF

Use **Add camera → Discover ONVIF cameras** in the dashboard. SVCS sends a
WS-Discovery probe on your LAN, lists the cameras it finds, and fills in a
suggested RTSP URL (enter the camera's username/password first if it needs
them — credentials are sent only to your local SVCS server to build the URL and
are never logged).

If discovery finds nothing — Windows Firewall commonly blocks the multicast —
just paste the RTSP URL into the source field. Common patterns:

| Brand | Typical RTSP URL |
|-------|------------------|
| Reolink | `rtsp://user:pass@<ip>:554/h264Preview_01_main` |
| Amcrest / Dahua | `rtsp://user:pass@<ip>:554/cam/realmonitor?channel=1&subtype=0` |
| Hikvision / HiLook | `rtsp://user:pass@<ip>:554/Streaming/Channels/101` |
| Axis | `rtsp://user:pass@<ip>:554/axis-media/media.amp` |
| TP-Link / Tapo | `rtsp://user:pass@<ip>:554/stream1` |

The exact path varies by model and firmware — check your camera's manual or the
[community RTSP list](https://www.ispyconnect.com/cameras) if these don't work.

---

## 2. Export / watch-folder (universal)

Point SVCS at a folder; every new video that lands there is detected, compressed
with an auto-chosen preset, and written to your output tree. This works for
**any** camera that can get a file onto disk — including cloud cameras whose apps
let you *export* or *download* clips.

CLI:

```bash
python src/utils/watchfolder.py --watch-dir <folder> --output <out> --profile <profile>
```

### Profiles

A **profile** sets sensible defaults for a camera's export layout — whether to
scan subfolders, how patient to be about half-written files (a NAS sync is slow
and bursty; an SD-card copy is fast), and how to pick the encode preset. Profiles
are data-driven (`WATCHFOLDER_PROFILES` in `src/utils/watchfolder.py`), not
hard-coded per vendor, so adding a layout is one entry.

| Profile | For this layout | Recursive | Preset |
|---------|-----------------|-----------|--------|
| `continuous` | Timestamped back-to-back files (CCTV hourly clips, dashcam loops) | yes | Continuous CCTV (fixed) |
| `motion_events` | One short clip per motion event (most consumer cams) | yes | auto-detect per clip |
| `microsd_dump` | A card pulled from a camera and bulk-copied (DCIM trees) | yes | auto-detect per clip |
| `nas_sync` | Files arriving via NAS / cloud-sync clients (slow, can pause mid-copy) | yes | auto-detect per clip |
| `nvr_export` | An NVR export, nested per-camera / per-day | yes | auto-detect per clip |
| `generic` | A flat folder you drop files into | no | auto-detect per clip |

For the recursive profiles the **subfolder name becomes part of the camera ID**,
so an NVR tree like `export/cam7/2026-06-01/clip001.mp4` is tagged `nvr_cam7_…`
and stays distinct from `cam8`.

### Per-family setup

| Camera family | Recommended path | Profile |
|---------------|------------------|---------|
| Reolink / Amcrest / Hikvision / Dahua | RTSP (path 1); or export to NAS → `nas_sync` | `nas_sync` |
| Wyze (RTSP firmware) | RTSP (path 1); microSD → `microsd_dump` | `microsd_dump` |
| Body cameras (Axon, etc.) | Dock dumps a folder of clips → `microsd_dump` | `microsd_dump` |
| Standalone NVR / DVR | Export tree → `nvr_export` | `nvr_export` |
| Ring / Nest / Arlo | Export clips from the app to a folder → `motion_events`; or **bridge** (path 3) | `motion_events` |
| Dashcam | microSD loop files → `continuous` | `continuous` |

### Reliability

- **Partial writes** — a file is only ingested once its size is stable across
  several polls (`--stable-checks`, raised automatically by the `nas_sync`
  profile), so a half-copied file is never compressed.
- **Crash-resume** — if SVCS is killed mid-encode, the file is retried on the
  next scan; finished files are marked and never reprocessed.
- **Dedupe** — each ingested file gets a `.ingested` sentinel next to it.

---

## 3. Bridge ingestion (cloud-locked cameras)

*Documented in the next task (M-CAM.3).* Short version: for Ring/Nest/Arlo with
no RTSP and no useful export, run a local **bridge** — Home Assistant, Scrypted,
or Frigate — that re-exposes the camera as a local RTSP stream. SVCS then ingests
that stream exactly like any other RTSP camera (path 1). SVCS never talks to the
vendor cloud; the bridge does, on your hardware, under your control.

---

*Author: Bloodawn (KheivenD), 2026-06-03 (M-CAM TASK 2 — export-folder profiles).*

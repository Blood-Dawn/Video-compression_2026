# Technical Handoff - Video Compression Pipeline
**Project:** EGN 4950C Group 16 - Open Source Selective Video Compression  
**Sponsor:** DIU / NIWC Pacific (Cody Hayashi, Geena Wann-Kung)  
**Deadline:** May 6, 2026 (capstone presentation)  
**Repo root:** `Video-compression_2026/`  
**Written:** May 2, 2026

---

## How to start the app

```bash
# From repo root - uv is the primary package manager
uv sync                       # installs all deps from pyproject.toml / uv.lock
uv run python run_gui.py      # starts Flask on http://localhost:5000

# Enhancement (Real-ESRGAN) is optional
uv sync --extra enhance
```

If `uv` isn't available:
```bash
pip install -r requirements.txt
python run_gui.py
```

Flask server: `src/gui/app.py`, entry point: `run_gui.py` (just sets CWD and calls `app.run()`).

---

## Architecture overview

```
FrameSource (frame_source.py)
    ↓  frame-by-frame (numpy BGR)
BackgroundSubtractor (background_subtraction.py)
    ↓  ForegroundRegion list per frame
ObjectFilter (detection/object_filter.py)   ← YOLOv8-nano gate (optional)
    ↓  filtered regions + COCO class labels
pipeline.py → run_pipeline()
    ├─ mode0: all frames buffered
    ├─ mode1: only frames with detections buffered
    ├─ mode2: background keyframe + bbox patch compositing
    └─ mode3: object-only blackout
         ↓  per-segment: begin_segment() → write_frame()×N → finish_segment()
ROIEncoder (compression/roi_encoder.py)
    ↓  FFmpeg stdin pipe (rawvideo BGR24 → libx264 MP4)
insert_segment() → SQLite segments table (utils/db.py)
Flask dashboard (gui/app.py) ← serves index.html, 40+ API routes
```

Output files land in `OneDrive/<user>/SVCS/` by default (Windows), detected via registry. Falls back to `outputs/` in project root.

---

## Key files and what lives where

| File | Purpose |
|---|---|
| `src/pipeline/pipeline.py` | `run_pipeline()` - main loop, all 4 modes, segment flush, metadata accumulation |
| `src/compression/roi_encoder.py` | `ROIEncoder` - streaming FFmpeg encoder, dual-CRF, sharpness, encryption post-encode |
| `src/background_subtraction/background_subtraction.py` | `BackgroundSubtractor` wrapping MOG2/KNN, night mode, CLAHE, morphological cleanup |
| `src/detection/object_filter.py` | `ObjectFilter` (YOLOv8-nano), `detect_dominant_color()`, `detect_scene_type()`, `_VEHICLE_CLASSES`, `_PERSON_CLASSES` |
| `src/utils/db.py` | SQLite schema, `initialize_database()`, `insert_segment()`, all query functions |
| `src/utils/encryption.py` | AES-256-GCM encrypt/decrypt, PBKDF2 key derivation, nonce+salt+tag header format |
| `src/utils/frame_source.py` | `FrameSource` - unifies video files, webcam indices, CDnet image sequences |
| `src/utils/watchfolder.py` | Daemon that polls a folder and auto-processes dropped `.mp4/.avi/.mov/.mkv` files |
| `src/utils/multi_source.py` | `MultiFrameSource` - N parallel RTSP streams via daemon threads, 2-frame ring buffer |
| `src/enhancement/enhancer.py` | `Enhancer` - Real-ESRGAN / OpenCV DNN superres / bicubic fallback, GPU auto-select |
| `src/demo/run_demo.py` | `run_all_demos()` orchestrator, `manifest.json` writer |
| `src/demo/demo.py` | `render_demo()` - annotated video renderer (standard + roi_tint views) |
| `src/demo/split_screen.py` | `build_split_screen_from_manifest()` - side-by-side mode comparison video |
| `src/demo/video_writer.py` | `H264Writer` - FFmpeg stdin pipe for browser-compatible H.264 MP4 |
| `src/gui/app.py` | Flask server, 40+ API routes, pipeline thread management, HLS server |
| `src/gui/templates/index.html` | Entire frontend: ~5750 lines, 4 tabs (HOME/METRICS/SEARCH/ENCRYPT), all JS inline |
| `src/pipeline/modes.py` | `ModeDecision`, `validate_mode()`, `get_mode_decision()` |
| `tests/` | 307 tests collected; 265 pass without hardware/slow marks |

---

## SQLite segments schema (current)

Table: `segments` in `{output_dir}/metadata.db`. One row per encoded segment.

```sql
CREATE TABLE segments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT,           -- UTC ISO e.g. "20260502T143000Z"
    camera_id       TEXT,           -- from run_pipeline(camera_id=)
    target_detected INTEGER,        -- 1 if any foreground detected this segment
    roi_count       INTEGER,        -- total bounding boxes written across all frames
    file_size       INTEGER,        -- bytes on disk (.mp4 or .mp4.enc)
    duration        REAL,           -- seconds (frame_count / fps)
    file_path       TEXT,           -- absolute path; ends in .mp4.enc if encrypted
    object_type     TEXT,           -- "vehicle"|"person"|"person+vehicle"|"unknown"|etc.
    avg_sharpness   REAL,           -- Laplacian variance avg over ROI crops (NULL if no targets)
    sharpness_label TEXT,           -- "HD"|"SD"|"Low" from estimate_perceptual_resolution()
    hidden          INTEGER,        -- soft-delete flag (0=visible, 1=hidden)
    object_classes  TEXT,           -- JSON array: ["car","person"] - COCO class union for segment
    dominant_color  TEXT,           -- most common color label across all ROI HSV histograms
    scene_type      TEXT,           -- "highway"|"intersection"|"parking"|"street"|"unknown"
    time_of_day     TEXT,           -- "day"|"night"|"dusk_dawn"
    vehicle_count   INTEGER,        -- count of UNIQUE vehicle class types seen (NOT instance count)
    person_count    INTEGER         -- count of UNIQUE person class types seen
)
```

**Important known issue with `vehicle_count` / `person_count`:** These count unique COCO class types seen in `_seg_all_classes`, not actual vehicle instances. Max possible value is 8 (number of entries in `_VEHICLE_CLASSES`). Old segments encoded before this column existed have `DEFAULT 0` from the `ALTER TABLE` migration. The UI now shows `+` when `vehicle_count == 0` but `object_type` indicates a vehicle, to signal legacy data. If you need real instance counts, you'd need to accumulate per-frame region counts separately in pipeline.py.

Index: `idx_cam_time ON segments(camera_id, timestamp)` - keeps `query_recent_targets()` fast.

DB path: passed as `db_path` to `ROIEncoder(db_path=...)` and `initialize_database(db_path=...)`. Each pipeline run writes to `{output_dir}/metadata.db`. The GUI reads from multiple DB files found by scanning known output roots.

---

## run_pipeline() signature

```python
run_pipeline(
    input_source,           # int (webcam) or str (file path / CDnet scene dir / RTSP URL)
    camera_id="cam_00",
    output_dir="outputs/",
    segment_seconds=60,
    bg_method="MOG2",       # "MOG2" | "KNN"
    show_preview=False,
    warmup_frames=120,      # frames to discard while BG model builds; CDnet overrides this
    enhance=False,
    enhance_scale=4,
    mode="mode0",           # "mode0" | "mode1" | "mode2" | "mode3"
    demo=False,
    enhance_model="bicubic",
    encrypt=False,
    encrypt_password=None,
    encrypt_key_file=None,
    mode2_clean_seconds=2.0,
    enhance_every_n=5,
    enhance_max_roi_px=200,
    enhance_device="auto",
    upscale_output=False,
    object_filter=False,    # enables YOLO gate; needs ultralytics installed + yolov8n.pt
    filter_confidence=0.30, # YOLO confidence threshold (use 0.10 at night)
    stop_event=None,        # threading.Event; set it to stop the loop cleanly
)
```

The loop runs until `FrameSource.read()` returns `(False, None)` or `stop_event.is_set()`. Clean stop: `abort_segment()` is called so FFmpeg doesn't wait 30s.

---

## ROIEncoder streaming API

Every pipeline segment goes through this sequence:

```python
encoder = ROIEncoder(
    output_dir=output_dir,
    foreground_crf=18,      # quality for frames with detections
    background_crf=45,      # heavy compression for no-detection frames
    preset="ultrafast",
    db_path=db_path,
)

encoder.begin_segment(
    frame_shape=(h, w, 3),
    fps=30.0,
    camera_id="cam_01",
    has_targets=True,
    object_type="vehicle",
    source_path="/path/to/input.mp4",  # for audio mux; None disables AAC pass-through
    encrypt=False,
    encrypt_password=None,
    encrypt_key_file=None,
)

encoder.write_frame(
    frame,                  # BGR numpy array
    boxes=[(x, y, w, h)],  # list of bounding box tuples
    background_frame=None,  # mode2: clean background frame to composite over
    object_only=False,      # mode3: True to black out non-ROI pixels
    mode_label="MODE 0",    # burned into corner overlay
    measure_sharpness=True,
)

result = encoder.finish_segment(
    timeout=30.0,
    object_classes='["car","truck"]',   # JSON string or None
    dominant_color="blue",
    scene_type="highway",
    time_of_day="day",
    vehicle_count=2,
    person_count=0,
)
# result = {"file_path": "...", "avg_sharpness": 312.4, "sharpness_label": "HD", "encrypted": False}
```

`finish_segment()` closes the FFmpeg stdin pipe, waits up to `timeout` seconds for FFmpeg to exit, muxes audio (if `source_path` was set), optionally encrypts the `.mp4`, then calls `insert_segment()`. The encrypted file replaces the plaintext; DB `file_path` stores the `.mp4.enc` path.

`abort_segment()` kills FFmpeg immediately - used by the stop handler so the pipeline thread can exit without waiting for a 60-second segment to flush.

---

## ObjectFilter (YOLO gate)

`src/detection/object_filter.py`

```python
obj_filter = ObjectFilter(
    model_path="yolov8n.pt",      # auto-downloaded by ultralytics if missing
    confidence=0.30,
    target_classes=None,          # defaults to _TARGET_CLASSES (vehicles + people + animals)
)

filtered_regions = obj_filter.filter(frame, raw_regions)
# After this call:
obj_filter.last_detected_classes   # dict: region_idx → set of COCO class names
obj_filter.classify_detected_objects()  # → "vehicle" | "person" | "person+vehicle" | ...
```

The 32-px static suppression grid (`_suppress_grid`) is a `np.int16` array. Each grid cell counts consecutive frames where YOLO found no target in that area. When a cell hits `_SUPPRESS_THRESHOLD = 30`, that zone is masked out of future detections. Reset with `obj_filter.reset_suppression()` when the source changes.

Class sets:
```python
_VEHICLE_CLASSES = {"bicycle","car","motorcycle","bus","truck","train","boat","airplane"}
_PERSON_CLASSES  = {"person"}
_ANIMAL_CLASSES  = {"bird","cat","dog","horse","sheep","cow","elephant","bear","zebra","giraffe"}
```

`detect_dominant_color(frame, x, y, w, h)` takes the center 50% of a bounding box, converts to HSV, builds a hue histogram, and maps the dominant hue to a label ("red", "blue", "green", "white", "black", "gray", "yellow", "orange").

`detect_scene_type(motion_vectors, roi_count, frame_area)` uses centroid-delta vectors accumulated across the segment. High unidirectional motion → "highway". High bidirectional motion → "intersection". Low motion, high ROI count → "parking".

---

## Flask API - complete route list

**Pipeline control:**
- `POST /api/start` - body: JSON config object (see `api_start()` around line 601 in app.py). Starts `run_pipeline()` in a daemon thread.
- `POST /api/stop` - sets `_stop_event`; calls `abort_segment()` on the encoder.
- `GET /api/status` - returns `{running, frame_count, segment_count, fps, progress_pct, config, error}`.

**Segments / storage:**
- `GET /api/segments` - multi-DB query, returns last 200-500 segments with all metadata columns as JSON array under `"segments"`.
- `GET /api/storage` - aggregate stats from DB.
- `GET /api/query_segments` - filtered search: `?camera=&type=&color=&scene=&tod=&start=&end=&min_rois=&enc_only=`.
- `POST /api/segments/clear` - soft-deletes segments (sets `hidden=1`) or hard-deletes files + rows depending on body.
- `GET /api/daily_summary`, `GET /api/busiest`.

**Media:**
- `GET /api/media?path=<absolute_path>` - serves any local video file with HTTP range request support (byte-range headers for in-browser `<video>`). No path traversal restriction - any absolute path is served.
- `GET /media/<rel_path>` - serves from project root (legacy).

**File system:**
- `GET /api/browse` - spawns a tkinter file dialog in a subprocess (Windows-compatible); returns selected path.
- `POST /api/upload` - saves a browser-uploaded file to OneDrive uploads folder.
- `POST /api/open_folder` - opens a folder in OS file manager (Explorer/Finder).
- `GET /api/scan_videos` - finds all `.mp4` files under known output roots.

**Encryption:**
- `POST /api/encrypt` - body: `{file_path, password, key_file}`. Now accepts any file path (output-dir restriction removed May 2). Calls `encrypt_file(src, delete_original=True)`.
- `POST /api/decrypt` - decrypts to a temp file, returns base64-encoded blob for in-browser playback.
- `POST /api/keygen` - generates a 32-byte random key file, saves to output dir.

**HLS streaming:**
- `POST /api/hls/start` - body: `{rtsp_url, camera_id}`. Starts annotator thread + FFmpeg HLS pipeline. Output chunks land in `outputs/hls/<camera_id>/`.
- `POST /api/hls/stop`, `GET /api/hls/status`, `GET /api/hls/latency`.
- `GET /api/hls/<camera_id>/playlist.m3u8` - serves the HLS playlist.
- `GET /api/hls/<camera_id>/<seg.ts>` - serves individual TS chunks.

**RTSP server (MediaMTX):**
- `POST /api/rtsp/start`, `POST /api/rtsp/stop`, `GET /api/rtsp/status`.
- `POST /api/rtsp/push` - pushes a local file to the RTSP server for testing.

**Demo:**
- `POST /api/demo` - body: `{input_source, output_root, modes, camera_id}`. Runs `run_all_demos()` in a thread.
- `GET /api/demo/status` - polls manifest.json and returns rendered video URLs.
- `GET /api/demo/history` - lists past demo runs.

**Misc:**
- `GET /api/gpu_info` - CUDA/MPS/CPU detection via `detect_gpu()`.
- `GET /api/network_info` - LAN IP for remote browser access.
- `GET /api/gdrive/detect` - detects OneDrive/GDrive mount path from Windows registry.
- `GET /api/system_metrics` - CPU%, RAM%, battery from psutil.
- `POST /api/config/import`, `GET /api/config/export`.

---

## Frontend: index.html (~5750 lines)

All HTML, CSS, and JavaScript in one file at `src/gui/templates/index.html`. No build step. No separate CSS/JS files.

**4 tabs:**
- `#tab-home` - live stats grid, hardware strip, mode chips, status message, progress bar, HLS player, inline clip player (`#home-preview-wrap`), recent recordings table, live SSE log.
- `#tab-metrics` - segment table (filterable), floating preview player, library summary.
- `#tab-search` - full filter form (camera, type, color, scene, time-of-day, ROI count, date range, enc-only), VEHICLES/PERSONS count columns, inline player.
- `#tab-encrypt` - Encrypt A Segment panel (left), Decrypt & View panel (right), key generator strip.

**Key JS functions:**
- `run_pipeline()` - `POST /api/start` with form values.
- `loadSegments()` - `GET /api/segments`; populates both METRICS table and HOME recent recordings.
- `playSegment(url, path)` - detects active tab, plays inline on HOME (`#home-preview-video`) or SEARCH (`#search-preview-video`); falls back to METRICS floating preview.
- `pushNotif(title, msg, type, actions, autoDismissMs)` - dismissable toast cards rendered in `#notif-dock`.
- `pollStatus()` - polls `/api/status` every 1.2s; fires `pushNotif('SEGMENT SAVED', ...)` when `segment_count` increases while pipeline is running.
- `doEncryptFile()` - `POST /api/encrypt`; fires `pushNotif('ENCRYPTED', ...)` on success.
- `doDecryptPanel()` / `doDecrypt()` - decrypt flows for the tab panel and the modal respectively.
- `switchTab(name)` - hides all `.tab-page`, shows `#tab-{name}`.
- `startSSE()` / `stopSSE()` - `EventSource('/api/logs')` with reconnect on error.
- `_updateHomeRecent(segments)` - renders the last 8 segments in the HOME table; play button calls `playSegment()` inline.
- `_updateLibrarySummary(segments)` - updates the 5 mlib-* cells in the METRICS sidebar.

**CSS variables (`:root`):**
```css
--surface1/2/3, --border, --border-bright
--amber: #ffb900    (primary button color, btn-primary)
--yellow: #ffc800   (encrypt accent, FIXED May 2 - was undefined)
--teal: #1fd4c8     (search/metrics accent)
--red: #ff5555
--green: #2dd6a0
--text, --text-dim, --mono
```

`--yellow` was undefined until May 2. Everything using `var(--yellow)` was invisible - including the ENCRYPT FILE button (black text on transparent background). Now defined as `#ffc800`.

---

## Test suite state (May 2, 2026)

```
307 tests collected
265 pass on every run (no hardware, no network)
42 skipped / hardware-gated:
  - tests/test_webcam_cpu.py   (needs real webcam at index 0)
  - tests/test_hls_streaming.py (needs network / RTSP)
  - tests/test_pipeline_stress.py (marked @slow; set STRESS_DURATION_S=30 for quick smoke)
```

Run the safe subset:
```bash
uv run pytest --ignore=tests/test_pipeline_stress.py \
              --ignore=tests/test_webcam_cpu.py \
              --ignore=tests/test_hls_streaming.py -q
# → 265 passed
```

Run everything including slow:
```bash
STRESS_DURATION_S=60 uv run pytest -q -m "slow"
```

**Test file → what it covers:**
| File | What it tests |
|---|---|
| `test_background_subtraction.py` | MOG2/KNN mask, night mode, CLAHE, morphological cleanup |
| `test_database.py` | Schema creation, WAL mode, `insert_segment()`, multi-camera queries |
| `test_roi_encoder.py` | `encode_segment()` dict return, dual-CRF, DB row written |
| `test_pipeline.py` | EOF boundary (exact segment), mode1 frame gating, mode2 background, mode3 object-only |
| `test_encryption.py` | AES-256-GCM round-trips at 1 KB / 1 MB, tamper detection raises `InvalidTag` |
| `test_enhancer.py` | Upscale dims, ROI paste, bicubic fallback |
| `test_detection_accuracy.py` | FP/FN rates on real CDnet clips in `data/samples/cdnet_mp4/` |
| `test_gui_api.py` | Flask routes: start/stop/status/segments/storage HTTP shape and state |
| `test_data_integrity.py` | Pixel-level round-trip: encode → decode → per-region comparison |
| `test_modes.py` | `validate_mode()`, `get_mode_decision()` |
| `test_watchfolder.py` | File stability check, `.ingested` sentinel, double-process guard |
| `test_multi_source.py` | Multi-RTSP threading, ring buffer, stall timeout |
| `test_layer_encoder.py` | `LayerSegmentEncoder` (mode2 artifact writer) |
| `test_object_type_queries.py` | `query_by_type()` with union types, `min_roi_count` filter |
| `test_frame_source.py` | Video file, webcam index, CDnet image sequence |
| `test_metrics.py` | PSNR, SSIM, compression ratio, `compute_sharpness()` |
| `test_hls_streaming.py` | HLS start/stop/status (needs network, marked integration) |
| `test_pipeline_stress.py` | 1-hour synthetic run, tracemalloc peak, storage extrapolation (marked slow) |
| `test_webcam_cpu.py` | Physical webcam, CPU-only pipeline (marked hardware) |

---

## Bugs fixed in this session (May 2, 2026)

### 1. ENCRYPT FILE button was invisible
**Root cause:** `var(--yellow)` was referenced everywhere but never defined in `:root`. `background: var(--yellow)` resolved to `transparent`, `color: #000` made text invisible on dark background.  
**Fix:** Added `--yellow: #ffc800` and `--yellow-dim: rgba(255,200,0,0.12)` to `:root` in `index.html`.  
**Affected:** ENCRYPT tab button, tab nav active color, all yellow accent elements throughout the UI.

### 2. HOME tab play button navigated to METRICS instead of playing inline
**Root cause:** `_updateHomeRecent()` in `index.html` was calling `switchTab('metrics'); setTimeout(()=>_metricsRowClick(...), 50)` instead of using `playSegment()`.  
**Fix:** Changed home-rec play button to call `playSegment(s.playable_url, s.file_path)`. Extended `playSegment()` to detect `tab-home` and play in the new `#home-preview-wrap` / `#home-preview-video` element added just above the HLS section.

### 3. VEHICLES column always showed 0 in SEARCH tab
**Root cause:** Old segments were encoded before `vehicle_count` existed; `ALTER TABLE ... ADD COLUMN vehicle_count INTEGER DEFAULT 0` back-filled them all with 0. `vehicle_count` also counts unique class types, not instances - so a video full of cars still shows 1, not N.  
**Fix:** UI now shows `+` (with tooltip "Detected (legacy segment)") when `vehicle_count == 0` but `object_type` includes "vehicle" or "person". New segments with YOLO running show the real count.

### 4. API rejected encrypting files outside output directory
**Root cause:** `api_encrypt()` in `app.py` checked `if output_dir not in src_path.parents` and returned 403 if the file was anywhere else (e.g., `data/samples/`).  
**Fix:** Removed the output-dir restriction entirely. Now accepts any absolute path the user provides. Key file restriction also removed. File must exist and must not already be `.enc`.

### 5. Toast notifications missing
**Root cause:** No notification fired when a segment was saved or when encryption succeeded.  
**Fix:** `doEncryptFile()` now calls `pushNotif('ENCRYPTED', ...)` on success. `pollStatus()` now tracks `_lastSegmentCount` and calls `pushNotif('SEGMENT SAVED', ...)` when `segment_count` increases while the pipeline is running. `setPipelineRunning(false)` resets `_lastSegmentCount = 0` so the next run starts clean.

### 6. Test suite: 6 failures before this session → 0 failures after
All fixed in the previous session (commit history). Key fixes:
- All 4 encoder mocks in `test_pipeline.py` were missing `**kwargs` on `begin_segment()` - pipeline added `encrypt=` kwarg.
- `DummyRegion` was missing `.x/.y/.w/.h` attributes - pipeline added `r.x / r.y` centroid accesses.
- `test_pipeline_stress.py`: `encode_segment()` returns `dict`, not string - tests extracted `["file_path"]`.
- `split_screen.py`: `resolve_mode_videos()` crashed when a mode had multiple views - now prefers `"standard"`, falls back to first.
- `H264Writer.release()`: no timeout on `proc.wait()` - could hang indefinitely. Fixed with 30s timeout + kill fallback.
- `pipeline.py`: ZeroDivisionError on `fps=0` in warmup log. Fixed with `if fps > 0` guard.

---

## What's left to do - prioritized for May 6 deadline

### P0 - Must do before presentation

**1. Capstone slide deck** (`3.8`)  
All team members. Template should match Progress Reports 1-3 (`.docx` in repo root). Sections Cody expects: storage problem, our approach, 4-mode system, benchmark numbers (16.6x compression, PSNR 41.2 dB, SSIM 0.9783), live demo clip, sponsor logo.

**2. Send Cody the May 6 invite** (`5.6`)  
`src/gui/app.py` has his email in the meeting notes. He confirmed remote attendance. Do this immediately.

**3. Per-mode CPU benchmark table** (`4.6` / `5.1` - Jorge)  
Use `psutil.cpu_percent(interval=None)` sampled every 500ms during pipeline run. Same 60-sec clip, all 4 modes. Report: avg CPU%, peak CPU%, encode time, output file size, estimated battery drain (`3h × idle_pct / mode_pct`). Cody's single biggest data ask.

**4. Demo output viewable in-browser** (`5.3` - Riley)  
`run_all_demos()` writes to `{output_root}/stitched/demo_splitscreen.mp4`. This file is already served by `/api/media?path=...`. The issue: the demo result URLs in `manifest.json` are absolute local paths that the GUI needs to convert to `/api/media?path=` URLs. See `api_demo_status()` in `app.py` around line 1504 - it already does this for individual mode clips but the split-screen URL may be missing.

### P1 - Important before May 6

**5. Object type split in DB** (`5.2` - Ashleyn)  
The pipeline calls `obj_filter.classify_detected_objects()` which already emits "vehicle", "person", "person+vehicle", "animal", "mixed", or "unknown". This is stored correctly in the `object_type` DB column. The issue is older segments from before YOLO was wired show "unknown". The query UI (`/api/query_segments?type=vehicle`) does work. What's likely missing is that the SEARCH tab's type dropdown doesn't list all `object_type` values from the DB - it may be hard-coded. Check the `<select id="arc-type-filter">` in `index.html` around the SEARCH tab.

**6. Latency measurement ingest → HLS** (`5.1` - KD)  
In `api_hls_start()` (app.py line 1928), the annotator thread reads RTSP frames and timestamps them. Add a `time.time()` at frame receipt and at HLS chunk write, compute rolling average, expose at `GET /api/hls/latency`. Front-end already has a latency display element (search for `hls-latency` in `index.html`).

**7. Extend `test_pipeline.py`** (`2.6` - Riley)  
Three missing test cases:
- `--enhance` bicubic path: monkeypatch `Enhancer` to return a known output; verify pipeline calls it.
- `--encrypt` round-trip: run pipeline with `encrypt=True`, verify `.mp4.enc` exists and `.mp4` is gone.
- `stop_event` mid-loop: set `stop_event` after N frames; verify clean exit with no lingering FFmpeg process.

**8. `run_demo.py` end-to-end** (`2.6` - Riley)  
```bash
python -m src.demo.run_demo \
  --input data/samples/cdnet_mp4/cameraJitter/cameraJitter.mp4 \
  --output outputs/demo_test/ \
  --camera-id cam_test \
  --modes mode0 mode1
```
Verify `manifest.json` is written and `demo_splitscreen.mp4` is playable.

### P2 - Stretch before May 6

**9. uv on Windows/Linux verify** (`4.5`)  
`pyproject.toml` is in the repo. `uv sync` on a clean Windows machine with Python 3.11 or 3.12. Main risk: `basicsr` (Real-ESRGAN) is an optional extra; without `--extra enhance` it should skip. Document any issues in `DEV.md`.

**10. Config JSON export button** (`4.1`)  
`GET /api/config/export` exists. There should be a "Save Config" button wired in the sidebar. Search `index.html` for `config/export` - the route exists but the button may not be wired.

**11. AV1 codec check** (`4.2` - Jorge)  
```bash
ffmpeg -encoders | grep av1
```
Just document whether `libsvtav1` is available. No need to implement; just report to Cody.

---

## Milestone 6 - Post-capstone future work (per Cody's May 1 feedback)

Both items are in ROADMAP.md under `## Milestone 6`. Assigned to KD.

### 6.1 - Reference-object height/weight estimation
The system already detects vehicles via YOLO and stores `object_classes` (COCO class names). The pipeline needed:

1. A lookup table: `{"car": (4.5, 1.8, 1.5), "truck": (8.0, 2.5, 3.0), ...}` meters (L×W×H).
2. For each segment where a vehicle bbox is detected: compute pixel-per-meter scale using the known vehicle height vs bbox height.
3. For nearby person bboxes in the same frame: multiply bbox height in pixels by the px/m scale.
4. Store as `estimated_height_m REAL` in a new `object_tracks` table (not `segments` - you'd need per-detection rows).

Key constraint: only works for cameras with a reasonable viewing angle (side or slight elevation). Overhead cameras don't expose height. You'd want to expose a `camera_tilt_deg` config parameter or detect the ground plane automatically.

### 6.2 - Parked/stationary object dwell tracker
Design:
```sql
CREATE TABLE object_tracks (
    id          INTEGER PRIMARY KEY,
    camera_id   TEXT,
    first_seen  TEXT,       -- UTC timestamp of first detection
    last_seen   TEXT,       -- UTC timestamp most recent detection
    centroid_x  REAL,       -- average centroid X across all detections
    centroid_y  REAL,
    object_class TEXT,      -- COCO class label
    dwell_s     REAL        -- last_seen - first_seen in seconds
);
```

Called from pipeline.py after `_close_segment()`. Match centroids within `TOLERANCE_PX = 50` pixels. Upsert: update `last_seen` and `dwell_s` if match found; insert new row otherwise.

Critical design note: MOG2 will **absorb** a stationary object into the background after ~300 frames at typical settings (controlled by `history` param, default 500). Once absorbed, it stops appearing in `raw_regions`, so the dwell tracker stops seeing updates. The tracker should flag an alert when `last_seen` is far from `first_seen` AND the object hasn't been updated recently (i.e., it's been absorbed). That absence of update is itself the signal.

---

## Data in the repo

```
data/
  samples/
    cdnet_mp4/        # 52 CDnet test clips across 11 categories (cameraJitter, badWeather, etc.)
    uploads/          # 11 real-world test videos (traffic cams, gookami.org)
  test_frames/        # synthetic frames for unit tests

models/
  yolov8n.pt          # YOLOv8-nano weights (~6 MB) - already present in repo root
```

The 52 CDnet clips are used by `test_detection_accuracy.py`. The `data/uploads/` videos include rush-hour footage from the Pearl City intersection camera (gookami.org) requested by Geena.

---

## OneDrive output path detection

`src/gui/app.py` around line 2406:

```python
_CLOUD_SUBFOLDER = "SVCS"
```

Detection priority:
1. Windows registry `HKCU\Software\Microsoft\OneDrive\Accounts\Business1` (school OneDrive)
2. Windows registry `Business2`, `Personal`
3. Returns `(None, None, None)` on macOS/Linux or if no OneDrive mount found

When found: default output dir is `<OneDrive root>/SVCS/`. The GUI pre-fills the output dir input on page load via `_initGDriveOutput()` in `index.html`. Demo output follows the same logic.

**Server-side default (added 2026-05-02):** the front-end pre-fill is async, so a fast click on Start used to land segments in `<repo>/outputs/` instead of OneDrive. Three Flask routes (`api_start`, `api_hls_start`, `api_demo`) now resolve any empty `output_dir` through `_default_output_dir()` in `src/gui/app.py`, which calls `_detect_cloud_root()` server-side and returns `<cloud>/SVCS` when found, falling back to `<repo>/outputs/` only when no sync is detected. Watchfolder CLI does NOT auto-detect - pass `--output "$HOME/OneDrive - Florida Atlantic University/SVCS"` explicitly. Two regression tests in `tests/test_gui_api.py::TestDefaultOutputDir` lock both branches.

---

## How to switch to Claude Opus

To use Claude Opus instead of Sonnet:
1. In the Cowork desktop app, click the model selector (usually in the top bar or sidebar).
2. Select "claude-opus-4" or "claude-opus-4-5".
3. Start a new session - the handoff document you're reading now gives the new session full codebase context.

When starting the new session, paste this prompt to orient the Opus model instantly:

> "Read `docs/project-records/handoff_may2026.md` in full. This is a video compression pipeline project for FAU capstone (EGN 4950C). The Flask app is at `src/gui/app.py`, main loop at `src/pipeline/pipeline.py`, encoder at `src/compression/roi_encoder.py`, DB at `src/utils/db.py`, frontend at `src/gui/templates/index.html`. Test suite: 265 passing (run with `uv run pytest --ignore=tests/test_pipeline_stress.py --ignore=tests/test_webcam_cpu.py --ignore=tests/test_hls_streaming.py -q`). Continue working on the open tasks in ROADMAP.md."

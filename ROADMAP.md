# Project Roadmap
## EGN 4950C Group 16 - Open Source Selective Video Compression
**Florida Atlantic University · Spring 2026 · Sponsor: Defense Innovation Unit (DIU) / NIWC Pacific**
**Hard deadline:** May 6, 2026

---

## Who owns what

### Kheiven D'Haiti (KD)

**Done:** Repo scaffold + project setup (Phase 0) · Background subtraction tuning - MOG2/KNN, night mode, CLAHE, morphological cleanup, min-area filter, 29 unit tests (M1) · CDnet foreground coverage benchmark across 46 scenes (M1) · Enhancement module - Real-ESRGAN / dnn_superres / bicubic fallback, upscale_frame, upscale_roi, --enhance pipeline integration, M2 benchmark notebook (M2) · Flask web dashboard - SSE live log, 16 API routes, file browser, demo runner, query archive sidebar, inline video player, segment preview (M2) · HLS streaming - 5 routes, hls.js integration, RTSP URL input, annotator thread, ultrafast FFmpeg HLS, VLC end-to-end test (M2/M3) · YOLO filter gate - YOLOv8-nano on MOG2 crops, 32-px suppression grid, night calibration conf=0.10 (PR #31, M3) · GPU acceleration for enhancer - CUDA/MPS/CPU auto-select, detect_gpu(), /api/gpu_info (M3) · Mode label + elapsed timer overlay (M3) · Double-compositing fix in encode_segment (M3) · Test suite repair - all four streaming encoder mocks, finish_segment dict fixes, schema index fix, 274 passing (M3) · Session log (M3) · uv migration - pyproject.toml, uv.lock, README/DEV.md (M3) · AES-256-CBC initial encryption implementation (M2) · GUI redesign - preset cards, 3-step flow, human-readable status, storage savings display (M2) · AI compression research doc

**Open:** Deployment packaging research (Docker/PyInstaller/tarball for COTS x86) · Webcam/IP camera real-time test (no frame drops, no GPU) · final_results.ipynb (reproducible end-to-end benchmark) · README.md and DEV.md final pass · Adaptive mode controller (activity-rate-based auto-switching) · AV1 codec selector in GUI · Color search dropdown in GUI · Config JSON export · Electron packaging research · Compression literature review · v1.0.0 tag · Slide deck

---

### Riley Roberts (RR)

**Done:** Mode dispatch - modes.py, ModeDecision, validate_mode, get_mode_decision, Mode 1 frame-gating tests (M2) · Demo system - DemoMetadataWriter + JSONL sidecar, render_demo() annotated video renderer, build_split_screen_from_manifest(), run_all_demos() orchestrator + manifest.json (M2) · Mode 2 - background keyframe capture, per-frame object patch compositing, GUI selectors (M3, PR #11) · Mode 3 - object-only blackout via object_only=True in ROIEncoder, GUI selectors (M3, PR #11) · Mode system repair - fixed mode dispatch broken by streaming encoder refactor; split raw_regions from regions for correct Mode 2 background selection (M3)

**Open:** Demo/concat mode (stitch all session segments into one reviewable file) · Extend test_pipeline.py (enhance bicubic path, encrypt round-trip, stop_event mid-loop) · run_demo.py end-to-end on real test clip · Live demo segment for capstone presentation · Slide deck

---

### Victor De Souza Teixeira (VT)

**Done:** metrics.py scaffold - compute_psnr(), compute_ssim(), compute_compression_ratio() (Phase 0/M1) · milestone1_benchmark.ipynb - pipeline on test clip, PSNR/SSIM/compression ratio (M1) · milestone1_results.md (M1) · AES-256-GCM upgrade - authenticated encryption, new file format (nonce+salt+tag+ciphertext), encrypt_bytes()/decrypt_bytes() for in-memory use, 24 unit tests including tamper detection (PR #12, M3) · GPU device detection utilities - detect_gpu(), best_device() exposed via /api/gpu_info (M3)

**Open:** Store IV + salt in DB per segment (for per-segment decryption) · Password-protected incident clip export · Slide deck

---

### Ashleyn Montano (AM)

**Done:** SQLite segments schema - WAL mode, idx_cam_time index, SegmentRow alias, 20 unit tests (M1) · DB writes integrated into pipeline - insert_segment() per encoded segment (M1) · query_recent_targets() (M1) · object_type column - ALTER TABLE migration, default 'unknown' (M2) · query_by_type(), query_segments_by_target_count(), query_daily_storage_summary() (M2) · CLI db_query.py with --camera/--last-hours/--type flags (M2) · test_object_type_queries.py (M2) · Multi-type query + ROI count filter - query_by_type() accepts Union[str, List[str]], parameterized IN placeholders, min_roi_count param, CLI rewritten with --min-roi and timezone-aware --last-hours (branch m3-metadata-query-fix, M3) · Detection accuracy calibration - co-owned with JS; varThreshold tuning, FP/FN measurements across lighting conditions, test_detection_accuracy.py (M2)

**Open:** Color detection - detect_dominant_color() via HSV histogram on center 50% of bbox, dominant_color DB column, object_confidence column, color filter in /api/query_segments · Contour-based object classifier rewrite (replace heuristic with aspect ratio + area) · Full-text / multi-tag search in GUI query sidebar · Unit tests for color detection · Slide deck

---

### Jorge Sanchez (JS)

**Done:** ROIEncoder skeleton + FFmpeg integration (Phase 0) · encode_segment() via FFmpeg stdin, dual-CRF (foreground CRF 18, background CRF 45), playable MP4 validation, get_file_size(), 18 integration tests (M1) · Algorithm comparison notebook (MOG2 vs KNN side-by-side, 46 CDnet scenes, 30 param combinations) + docs/algorithm_comparison.md (M2, PR #9) · Stress test - test_pipeline_stress.py, 1-hour simulated footage, tracemalloc memory verification, 60-day storage extrapolation, stress_test_results.md (M2, PR #9) · Detection accuracy calibration - co-owned with AM; varThreshold tuning, FP/FN table across lighting conditions (M2) · Watchfolder daemon - src/utils/watchfolder.py, 5s poll, size-stability check, .ingested sentinel, 22 unit tests (PR #13, M3) · MultiFrameSource - N parallel RTSP streams via daemon threads, 2-frame ring buffer, 5s stall timeout, threading.Event racy-test fix (PR #13, M3)

**Open:** Per-mode CPU and battery benchmarks (avg CPU%, encode time, estimated battery drain per mode on 60-sec clip) · AV1 encoder feasibility - check libaom-av1/libsvtav1 availability, add codec param to ROIEncoder, benchmark AV1 vs H.264 on CPU · Per-mode compute table in stress_test_results.md · Slide deck

---

## Project goals

The end deliverable is a working, open-source pipeline that:

1. Ingests a static camera feed (USB, IP camera, or pre-recorded test video)
2. Separates foreground objects from the static background using background subtraction
3. Encodes foreground regions at high quality and background at heavy compression via FFmpeg + libx264
4. Indexes every video segment in a SQLite metadata database for fast retrieval
5. Stores footage locally with optional AES-256 encryption
6. Enhances compressed footage post-offload using CPU-based super-resolution
7. Delivers measurable storage savings, target 6× vs naive full-frame H.264

All components must be open source, royalty-free, and run on CPU-only hardware.

---

## Phase 0 - Project setup (completed Jan 13, 2026)

Initial repo scaffolding done before the semester sprint. No owner tracking needed - all complete.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Repo scaffold + directory structure | KD | 2026-01-13 | Urgent | Done | Initial commit to `main` |
| `requirements.txt` - all Python dependencies | KD | 2026-01-13 | Important | Done | opencv, ffmpeg-python, Flask, pytest, etc. |
| `.gitignore` for Python, video files, model weights | KD | 2026-01-13 | Medium | Done | Excludes `outputs/`, `models/`, `*.mp4` |
| `BackgroundSubtractor` class skeleton | KD | 2026-01-13 | Important | Done | MOG2 / KNN / GMG |
| `ROIEncoder` skeleton + FFmpeg integration | JS | 2026-01-13 | Important | Done | Stub for dual-CRF encoding |
| `Pipeline` orchestrator skeleton | KD | 2026-01-13 | Important | Done | Frame loop + segment flush structure |
| `metrics.py` utility skeleton (PSNR, SSIM) | VT | 2026-01-13 | Medium | Done | Scaffold only |
| Unit test file scaffolded | KD | 2026-01-13 | Medium | Done | `tests/test_background_subtraction.py` |

---

## Milestone 1 - Core pipeline functional (completed Mar 31, 2026)
**Branch:** `dev` merged to `main` · tagged `v0.1.0` on 2026-03-29

The goal for M1 was a working end-to-end pipeline on a real test clip with measurable, verifiable compression results. Every task below was completed and verified before the March 31 deadline.

### 1.1 - Background subtraction tuning

MOG2 and KNN were both tuned against 46 CDnet scenes. MOG2 came out ahead on false-positive rate across edge-case categories (night, shadow, dynamic background) and was adopted as the primary algorithm. The night_mode flag and morphological cleanup were added after the initial CDnet sweep revealed noise in low-light masks.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Tune MOG2 params - night_mode, CLAHE, varThreshold | KD | 2026-03-29 | Important | Done | `night_mode` flag; `VAR_THRESHOLD_DAY=16` / `NIGHT=30`; CLAHE preprocessing |
| Tune KNN params; compare with MOG2 on 46 CDnet scenes | KD | 2026-03-29 | Important | Done | Full CDnet sweep; MOG2 recommended; results in `outputs/cdnet_batch_results.log` |
| Morphological cleanup (erosion/dilation) to remove mask noise | KD | 2026-03-29 | Medium | Done | `MORPH_CLOSE` + `MORPH_OPEN` with elliptical kernel; `morph_kernel_size` param exposed |
| Minimum contour area filter for small detections | KD | 2026-03-29 | Medium | Done | `min_area` param (default 500 px); 1500-2000 px recommended for HD footage |
| Unit tests for background subtraction (29 tests) | KD | 2026-03-29 | Important | Done | `tests/test_background_subtraction.py` - mask gen, edge cases, night mode |

### 1.2 - ROI encoding pipeline

The encoder pipes raw numpy frames directly to FFmpeg via stdin, bypassing the lossy XVID intermediate that was used in early prototypes. Dual-CRF encoding - CRF 18 for foreground, CRF 45 for background - was validated against 18 integration tests.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Implement `encode_segment()` - pipe numpy frames to FFmpeg via stdin | JS | 2026-03-29 | Urgent | Done | `src/compression/roi_encoder.py`; uses `communicate()` to avoid pipe deadlock |
| Dual-pass CRF encoding: foreground CRF 18, background CRF 45 | JS | 2026-03-29 | Urgent | Done | `has_targets` flag selects `foreground_crf` vs `background_crf` per segment |
| Validate output is a playable MP4 | JS | 2026-03-29 | Important | Done | Raises `RuntimeError` if output missing or zero bytes after FFmpeg |
| Implement `get_file_size()` and log pre/post compression sizes | JS | 2026-03-29 | Medium | Done | Returns bytes or 0 for missing file; logged per segment |
| Integration tests for ROI encoder (18 tests) | JS | 2026-03-29 | Important | Done | `tests/test_roi_encoder.py` - encode, CRF, DB row, error handling |

### 1.3 - Metrics and benchmarking

Victor implemented PSNR, SSIM, and compression ratio in `metrics.py` and built the benchmark notebook. Kheiven ran the full 46-scene CDnet sweep to establish foreground coverage baselines.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Implement `compute_psnr()` and `compute_ssim()` | VT | 2026-03-29 | Important | Done | `src/utils/metrics.py`; verified against known reference values |
| Implement `compute_compression_ratio()` | VT | 2026-03-29 | Medium | Done | Handles zero/negative inputs |
| CDnet foreground coverage benchmark across all 46 scenes | KD | 2026-03-29 | Important | Done | `scripts/run_all_cdnet.py`; per-category avg FG% in `outputs/cdnet_batch_results.log` |
| Create `notebooks/milestone1_benchmark.ipynb` | VT | 2026-03-29 | Important | Done | Runs pipeline on test clip; reports PSNR, SSIM, compression ratio |
| Document results in `docs/milestone1_results.md` | VT | 2026-03-29 | Medium | Done | Compression ratio, PSNR, SSIM results documented |

### 1.4 - Metadata database

Ashleyn built the SQLite schema with WAL mode and an index on `(camera_id, timestamp)`. This made it possible to later extend the schema for `object_type` without a migration headache.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Create SQLite `segments` schema (`db.py`) with WAL mode and index | AM | 2026-03-29 | Important | Done | WAL mode, `idx_cam_time` index, type hints, `SegmentRow` alias |
| Integrate DB writes into pipeline - one row per encoded segment | AM | 2026-03-29 | Important | Done | `insert_segment()` called in `encode_segment()` after every successful encode |
| Query: all segments from camera X with targets in last N hours | AM | 2026-03-29 | Important | Done | `query_recent_targets(camera_id, hours, db_path)` - ORDER BY timestamp DESC |
| Unit tests for database (20 tests - WAL, index, multi-camera, edge cases) | AM | 2026-03-29 | Important | Done | `tests/test_database.py` - expanded from 2 to 20 tests |

---

## Milestone 2 - Enhancement + stress testing (completed Apr 18, 2026)
**Branch:** `dev` - merge to `main` when all tests pass

M2 added three sponsor-requested features: super-resolution enhancement for post-offload analysis, a full algorithm comparison between MOG2 and KNN, and stress testing to validate the pipeline under continuous load. The GUI dashboard and demo rendering system were also built in this milestone. Requirements came from Sponsor Meeting 2 (Apr 1, 2026).

### 2.1 - Super-resolution enhancement module

Victor built the Enhancer class with three backends: Real-ESRGAN, OpenCV DNN super-res, and bicubic (always available as fallback). The `--enhance` flag runs the enhancement in-place on foreground ROIs before encoding each segment.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research Real-ESRGAN CPU inference; document model download in DEV.md | KD | 2026-04-09 | Important | Done | DEV.md updated; `models/` gitignored; basicsr build issues on Py 3.14 noted |
| Implement `Enhancer.upscale_frame()` - Real-ESRGAN / dnn_superres / bicubic | KD | 2026-04-09 | Urgent | Done | `src/enhancement/enhancer.py`; three backends; bicubic always available |
| Implement `Enhancer.upscale_roi(frame, bbox)` - upscale only bounding region | KD | 2026-04-09 | Important | Done | Crops ROI, upscales, resizes back to original bbox dims, pastes in-place |
| Integrate enhancement into pipeline as optional pass (`--enhance` flag) | KD | 2026-04-09 | Urgent | Done | `--enhance / --enhance-model / --enhance-scale`; bicubic fallback if model unavailable |
| Benchmark enhancement processing time per frame on CPU hardware | KD | 2026-04-09 | Medium | Done | `notebooks/milestone2_enhancer_benchmark.ipynb` |
| Unit tests for Enhancer (output dims, bbox validation, `is_available()`) | KD | 2026-04-09 | Important | Done | `tests/test_enhancer.py` - upscale x2/x4, ROI paste, enhance_batch, graceful unavailable |

### 2.2 - Mode dispatch system

Riley built the mode dispatch layer in `modes.py` and integrated it into the pipeline. Mode 0 and Mode 1 are live. Mode 2 and Mode 3 are the next open implementation tasks - they were scoped in the sponsor meeting but not yet built.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Mode dispatch: `modes.py` - ModeDecision, validate_mode, get_mode_decision | RR | 2026-04-09 | Urgent | Done | PR #6 `feat/mode-system` merged; fully tested; pipeline uses `get_mode_decision()` per frame |
| Mode 1 frame-gating unit tests (`test_pipeline.py`) | RR | 2026-04-09 | Important | Done | 2/2 passing; covers exact-segment-boundary EOF and mode1 frame selection |
| Implement Mode 2: one background keyframe + per-frame object patches | RR | 2026-04-11 | Urgent | Done | Merged 2026-04-20. `pipeline.py`: tracks clean frame streak, captures background keyframe, composites bbox patches over it. `layer_encoder.py`: `LayerSegmentEncoder` writes sparse artifacts (crop PNGs + mask PNGs + metadata.json + preview.mp4). GUI selectors wired in `index.html`. |
| Implement Mode 3: object-only forensic mode - padded crop, no background | RR | 2026-04-11 | Urgent | Done | Merged 2026-04-20. `pipeline.py`: passes `object_only=True` to `ROIEncoder.encode_segment()`, which blacks out all pixels outside detected bounding boxes before piping to FFmpeg. Mode chip shown in GUI. Tests in `test_layer_encoder.py`, `test_modes.py`, `test_pipeline.py`. |
| Demo/concat mode: stitch all output segments into one playback file | RR | 2026-04-10 | Important | Not Started | Proposed by Riley in Apr 1 sponsor meeting. Lets you review a full session without opening each 60-second clip. |

### 2.3 - Metadata query interface

Ashleyn extended the DB schema with `object_type` and added three new query functions exposed through both a CLI tool and the GUI's Query Archive sidebar.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Add `object_type` tag to DB schema (person, vehicle, cyclist, unknown) | AM | 2026-04-10 | Important | Done | ALTER TABLE migration in `initialize_database()`; default `'unknown'`; `SegmentRow` extended |
| Implement `query_by_type(object_type, camera_id, start_time, end_time)` | AM | 2026-04-13 | Urgent | Done | Parameterized SQL; optional camera + time range filters; exposed via `/api/query_segments` |
| Implement `query_segments_by_target_count()` - busiest segments | AM | 2026-04-13 | Important | Done | Orders by `roi_count DESC`; exposed via `/api/busiest` in GUI |
| Implement `query_daily_storage_summary()` - daily storage by camera | AM | 2026-04-13 | Important | Done | Groups by date + camera_id; exposed via `/api/daily_summary` in GUI |
| CLI query tool: `db_query.py --camera cam_01 --last-hours 24 --type person` | AM | 2026-04-13 | Medium | Done | Supports `--camera`, `--last-hours`, `--type` flags |
| Unit tests for object_type queries | AM | 2026-04-13 | Important | Done | `tests/test_object_type_queries.py` |

### 2.4 - Data integrity validation

A frame-level pixel comparison test was added to catch any silent corruption in the ROI encode/decode cycle. The sponsor was explicit that foreground data loss is unacceptable even at 5%.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Frame-level comparison test: verify ROI pixels survive the encode/decode cycle | KD | 2026-04-09 | Urgent | Done | `tests/test_data_integrity.py` - per-region pixel comparison; pass/fail logged |
| CI integration for `test_data_integrity.py` | KD | 2026-04-18 | Medium | Not Started | Wire into CI so this runs on every PR to `dev`. |

### 2.5 - Algorithm comparison and stress testing

Jorge ran the full algorithm comparison and the 1-hour stress test. Both are done and documented. The stress test uses `tracemalloc` so transient memory spikes get caught, not just endpoint comparisons.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Create `notebooks/algorithm_comparison.ipynb` with side-by-side visualizations | JS | 2026-04-08 | Important | Done | PR #9 - 2026-04-11; MOG2 vs KNN side-by-side; data from `cdnet_batch_results.log` |
| Write `docs/algorithm_comparison.md` - production recommendation | JS | 2026-04-08 | Medium | Done | PR #9 - 2026-04-11; MOG2 recommended as primary; KNN viable for high-motion scenes |
| Write `tests/test_pipeline_stress.py` - 1 hour simulated footage | JS | 2026-04-09 | Important | Done | PR #9; loops test clip; no memory leak; configurable via `STRESS_DURATION_S` env var |
| Verify memory does not grow unbounded over 1 hour of operation | JS | 2026-04-09 | Important | Done | `tracemalloc` peak used (not just endpoints); results in `docs/stress_test_results.md` |
| Extrapolate 1-hour results to estimate storage for 60-day retention (100 cameras) | JS | 2026-04-10 | Medium | Done | Sponsor requirement: 60 days on 100+ camera systems |
| Document stress test findings in `docs/stress_test_results.md` | JS | 2026-04-11 | Medium | Done | Runtime, peak memory, projected weekly/60-day storage, Mode 0 vs Mode 1 |

### 2.6 - Demo rendering system + web dashboard GUI

Kheiven built the Flask dashboard and wired in Riley's demo rendering system. The GUI had several regressions during the env migration that required fixing - path traversal sanitization, the tkinter file picker workaround, and per-run database isolation are all covered.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Build `DemoMetadataWriter` + JSONL sidecar per buffered frame | RR | 2026-04-09 | Important | Done | `src/demo/demo_metadata.py`; context manager; writes frame index, time, mode, segment, regions |
| Build `render_demo()` + annotated video renderer | RR | 2026-04-09 | Urgent | Done | `src/demo/demo.py`; supports `standard` and `roi_tint` views; `draw_boxes` flag |
| Build `build_split_screen_from_manifest()` - side-by-side mode comparison | RR | 2026-04-09 | Important | Done | `src/demo/split_screen.py`; auto-detects 2-4 mode outputs from `manifest.json` |
| Build `run_all_demos()` orchestrator + `manifest.json` writer | RR | 2026-04-09 | Urgent | Done | `src/demo/run_demo.py`; supports `--modes`, `--view`, `--no-boxes` CLI flags |
| Build Flask dashboard - SSE live log, start/stop/status/segments/storage routes | KD | 2026-04-09 | Urgent | Done | `src/gui/app.py`; SSE with `Last-Event-ID` backlog replay; 16 API routes total |
| Add `/api/browse` - native OS file picker via subprocess (Windows-safe) | KD | 2026-04-09 | Important | Done | tkinter dialog spawned in subprocess; avoids main-thread restriction on Windows |
| Add `/api/media` - serve any local video by absolute path | KD | 2026-04-09 | Important | Done | Fixes segment playback when output dir is outside project root |
| Add `/api/demo` + `/api/demo/status` - background demo runner | KD | 2026-04-18 | Important | Done | Background thread calls `run_all_demos()`; polls `manifest.json` to build playable URLs |
| Add multi-mode comparison UI (Mode 0/1 checkboxes, demo output panel) | KD | 2026-04-18 | Important | Done | Spinner during render; video player with mode tabs; auto-loads first result |
| Add segment inline preview player in output segments table | KD | 2026-04-18 | Important | Done | Clicking play in table loads clip in inline player below the table |
| Add Query Archive sidebar - type/camera/time filters, SEARCH/BUSIEST/DAILY | KD | 2026-04-18 | Important | Done | Calls `/api/query_segments`, `/api/busiest`, `/api/daily_summary`; inline results with play |
| Fix `initialize_database()` - pass `db_path` arg so each run gets isolated DB | KD | 2026-04-18 | Urgent | Done | Was defaulting to `metadata.db` in CWD; now writes to per-run output directory |
| Fix `ROIEncoder` - pass `db_path` to constructor (was hardcoded `outputs/`) | KD | 2026-04-18 | Urgent | Done | Encoder now writes to correct per-run DB |
| SSE Last-Event-ID resume + deque log history | KD | 2026-04-09 | Medium | Done | Monotonic event IDs; `collections.deque(maxlen=300)`; no duplicate lines on reconnect |
| GUI regression tests: `/api/start` `/api/stop` `/api/status` `/api/segments` `/api/storage` | KD | 2026-04-18 | Important | Done | `tests/test_gui_api.py` - 24 tests; covers HTTP status, JSON shape, state transitions, DB-backed responses. |
| Extend `test_pipeline.py`: `--enhance` bicubic path, `--encrypt` round-trip, stop_event | RR | 2026-04-18 | Important | Not Started | Bicubic test needs no SR weights. Encrypt test: verify `.enc` written, `.mp4` deleted. Stop-event: break mid-loop. |
| Run `run_demo.py` end-to-end on a real test clip - verify split-screen output | RR | 2026-04-18 | Important | Not Started | `python -m src.demo.run_demo --input data/test.mp4 --output outputs/ --camera-id cam_test` |

### 2.7 - Detection tuning

Calibrated MOG2 and KNN parameters across three lighting conditions (day, night, mixed) on synthetic test footage. The tuned defaults (varThreshold=50, detectShadows=False) cut false positives to zero on static scenes while keeping detection latency under 3 frames.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research + calibrate MOG2/KNN params - day, night, gate, walkway footage | AM, JS | 2026-04-18 | Important | Done | Results in `docs/detection_tuning.md`; varThreshold=50, detectShadows=False as tuned defaults |
| Measure FP/FN rates across lighting conditions | AM, JS | 2026-04-18 | Important | Done | Full FP/FN table in `docs/detection_tuning_results.md` (Jorge); all conditions FP < 2% |
| Update BackgroundSubtractor defaults + write detection accuracy unit tests | AM, JS | 2026-04-18 | Medium | Done | `tests/test_detection_accuracy.py`; tuned params committed to `background_subtraction.py` |

---

## Milestone 3 - Final demo + deliverables (due May 6, 2026)
**Branch:** `dev` merged to `main` after final review

M3 is everything needed to ship: encryption hardening, polished metadata search, a working demo on target hardware, a complete final report, and the capstone presentation. Most tasks here are Not Started - this is the sprint for the last two weeks.

### 3.1 - Security and encryption

Victor - the AES-256-CBC implementation is in `src/utils/encryption.py` and works. The GCM upgrade is the open task: CBC has no authentication tag, so bit-flip attacks pass silently. GCM is a drop-in replacement via the `cryptography` lib and should not take more than a day.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| AES-256-CBC encryption for output video files (`--encrypt` flag) | KD | 2026-04-09 | Urgent | Done | `src/utils/encryption.py`; PBKDF2 600k iters; password or raw-key mode; IV+salt in header |
| Upgrade AES-256-CBC to AES-256-GCM (authenticated encryption) | VT | 2026-04-18 | Important | Done | Merged via PR #12 on 2026-04-20. New header: nonce(12)+salt(16)+tag(16)+ciphertext. `InvalidTag` raised on any tamper. PKCS7 padding removed (GCM is stream mode). 24 unit tests in `tests/test_encryption.py`. |
| Store IV + salt in DB per segment | VT | 2026-04-25 | Medium | Not Started | Required for per-segment decryption without re-prompting the user for their password. |
| Password-protected incident clip export | VT | 2026-04-25 | Important | Not Started | Sponsor showed commercial systems charge extra for this. Include by default. |
| Encrypt/decrypt round-trip unit tests | VT | 2026-04-25 | Important | Done | 24 tests in `tests/test_encryption.py`. Round-trips at 1 KB, 1 MB, and multi-chunk; tamper detection test (ciphertext modification raises `InvalidTag`). Shipped in PR #12. |

### 3.1b - Detection hardening and pipeline fixes

Work landed April 20-24 as part of the M3 sprint. Not in the original roadmap - added retrospectively.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| YOLO object classification gate | KD | 2026-04-24 | Important | Done | PR #31 merged 2026-04-24. `src/detection/object_filter.py`. YOLOv8-nano on each MOG2 bbox crop. 32-px static suppression grid (int16 counters, threshold=30 consecutive FP frames). Conf default 0.30 (use 0.10 for night). Optional: pipeline falls back gracefully if `ultralytics` not installed. |
| GPU acceleration for enhancer (CUDA / MPS) | KD | 2026-04-22 | Medium | Done | `src/enhancement/enhancer.py`. Device selection: CUDA → MPS → CPU. `detect_gpu()` returns backend, device name, VRAM, `will_work`. Exposed via `/api/gpu_info`. M2 MPS: ~95 ms/frame vs ~420 ms CPU. COTS CPU-only deployments unaffected. |
| Mode label + elapsed timer overlay | KD | 2026-04-20 | Medium | Done | `src/compression/roi_encoder.py` commit `5547564`. `cv2.putText` burns `MODE N \| HH:MM:SS` into top-left corner of every frame before FFmpeg pipe. Appeared in segments and HLS stream. Requested after April 22 sponsor test where mode was unidentifiable from thumbnails. |
| Double-compositing fix in encode_segment | KD | 2026-04-20 | Important | Done | `src/compression/roi_encoder.py`, `src/pipeline/pipeline.py` commit `39fef25`. Background composite was applied twice per frame (once in `write_frame()`, once in outer loop). Removed outer composite. Mode 2 washed-out artifact eliminated. |
| Test suite repair - streaming encoder API | KD | 2026-04-24 | Urgent | Done | All four dummy/recording encoder classes in `tests/test_pipeline.py` rewritten from old `encode_segment(frames, bboxes_per_frame)` API to `begin_segment()` → `write_frame()` × N → `finish_segment()` returning `dict`. Also fixed: `test_roi_encoder.py` (`out.endswith` → `out["file_path"].endswith`), `test_data_integrity.py` (same return value), `test_object_type_queries.py` (`_OBJECT_TYPE_COL = 8` constant replaces broken index). Final result: **274 passed, 0 failed**. |
| Session log `docs/session_log_2026-04-26.md` | KD | 2026-04-26 | Medium | Done | Written and committed. Covers all M3 work April 20-26. Commit `61b1e75` (corrected `4ef6d0d`). |

### 3.2 - Searchable metadata index

Ashleyn - the query functions exist in `db.py` and are wired into the GUI. The open tasks are stabilizing the API shape and adding documentation so the sponsor can rely on it.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Stable query API with full filtering (type, camera, time range) | AM | 2026-04-22 | Urgent | Done | `query_by_type(object_type, camera_id, start_time, end_time)` returns matching segment paths |
| Multi-type query + ROI count filter | AM | 2026-04-22 | Important | Done | Branch `m3-metadata-query-fix` merged 2026-04-22. `query_by_type()` now accepts `Union[str, List[str]]` with parameterized `IN (?, ?, ...)` placeholders. New `min_roi_count` parameter filters low-confidence detections. CLI `db_query.py` rewritten: `--type vehicle person`, `--min-roi 5`, `--last-hours 12`, `--start-time`/`--end-time`. |
| Full-text / tag search + README docs | AM | 2026-04-25 | Medium | Not Started | Extend query interface to support multi-tag filtering; document in README. |

### 3.3 - External input and ingestion

Jorge - these came from the sponsor's request to accept footage from body cameras and other external sources, not just the live pipeline output.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Watchfolder daemon / drag-and-drop video import for external footage | JS | 2026-04-26 | Medium | Done | PR #13 merged 2026-04-24. `src/utils/watchfolder.py`. Polls drop folder every 5 s. Waits for file to stop growing (`_is_fully_written()`). Calls `run_pipeline()` per file. `.ingested` sentinel prevents double-processing on restart. Supports `.mp4 / .avi / .mov / .mkv / .ts / .mts / .m2ts`. `tests/test_watchfolder.py` included. |
| Multi-source input support | JS | 2026-04-26 | Medium | Done | PR #13 merged 2026-04-24. `src/utils/multi_source.py`. `MultiFrameSource` manages N parallel RTSP streams via `_StreamReader` daemon threads. 2-frame ring buffer, 5 s stall timeout. API: `open()`, `read_all()`, `any_alive()`, `active_count()`, `get_metadata()`, `release()`, context manager. Racy test fixed with `threading.Event` gate. 22 tests total across both modules. |

### 3.4 - Deployment packaging

Kheiven - deployment packaging research and the AI compression research doc are both in scope here. The packaging question came from Riley in the Apr 1 meeting; Cody asked the team to follow up with the sponsor on COTS hardware compatibility.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research AI-based compression alternative; benchmark vs MOG2 approach | KD | 2026-04-09 | Medium | Done | `docs/ai_compression_research.md`; YOLO detection overhead vs MOG2; NDAA note on neural codecs; MOG2 recommended |
| Research deployment packaging for government COTS deployment | KD | 2026-04-20 | Important | Not Started | Options: Docker, PyInstaller, OS package, source tarball. Must run on COTS x86. Check NDAA compliance for each. |

### 3.5 - Live demo preparation

Kheiven - the goal is a working demo on a laptop with no GPU. Cody confirmed government hardware is low-spec. `demo.sh` is done. The open tasks are confirming the webcam input path and the no-GPU test.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Create `demo.sh` - one-click pipeline launch with sensible defaults | KD | 2026-04-09 | Medium | Done | Launches `run_gui.py` with default port 5000; works headless or with browser auto-open |
| Confirm pipeline runs on USB or IP camera input in real time | KD | 2026-04-14 | Urgent | Not Started | Test with `--input 0` (webcam) on target hardware; verify no frame drops. |
| Test demo on laptop with no GPU (simulate target hardware) | KD | 2026-04-17 | Urgent | Not Started | Set `CUDA_VISIBLE_DEVICES=""` or use a CPU-only machine. Enhancer falls back to bicubic automatically. |

### 3.6 - Final report and results

Kheiven - `docs/final_report.md` exists and the abstract has real benchmark numbers (16.6x compression, PSNR 41.2 dB, SSIM 0.9783 on CDnet footage). The open task is the reproducible notebook.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Create `docs/final_report.md` - architecture, results, limitations | KD | 2026-04-18 | Urgent | Done | File exists; 13 sections including mode descriptions, benchmark results, encryption design |
| Populate final numbers table: compression ratio, PSNR, SSIM, storage/day/camera | KD | 2026-04-19 | Urgent | Done | Numbers in report abstract: 16.6x compression, PSNR 41.2 dB, SSIM 0.9783 |
| Create `notebooks/final_results.ipynb` - re-run all benchmarks from scratch | KD | 2026-04-20 | Important | Not Started | Must run end-to-end without errors on the final codebase. |
| Include side-by-side figure: original vs Mode 0 vs Mode 1 compressed frame | KD | 2026-04-21 | Medium | Not Started | Add to `final_report.md` and `final_results.ipynb`. |

### 3.7 - Repository polish and documentation

Kheiven - this is the final cleanup pass before tagging v1.0.0. The goal is that a new team member can clone the repo, run `pip install -r requirements.txt`, and have the pipeline running in under 15 minutes using only README.md and DEV.md.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Add docstrings to all public modules | KD | 2026-04-22 | Medium | Not Started | Check: `pipeline.py`, `roi_encoder.py`, `db.py`, `frame_source.py`, `metrics.py`, `enhancer.py` |
| Update README.md - final architecture and all four modes | KD | 2026-04-23 | Important | Not Started | Include: quick-start, mode descriptions, install steps. |
| Update DEV.md with any new setup steps | KD | 2026-04-24 | Medium | Not Started | Include: Real-ESRGAN model download, ffmpeg-python install, CDnet setup, encryption deps. |
| Cross-check `requirements.txt` via `pip freeze` | KD | 2026-04-25 | Medium | Not Started | `pip freeze > requirements_check.txt` and diff. |
| Tag final commit as `v1.0.0` | KD | 2026-04-26 | Important | Not Started | `git tag v1.0.0 && git push origin v1.0.0` |
| Verify repo clones cleanly on a fresh machine | KD | 2026-04-27 | Urgent | Not Started | New team member should be up and running in under 15 minutes. |

### 3.8 - Capstone presentation

All team members - deadline is May 1 for submission, May 6 for the presentation.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Create slide deck: problem, approach, 4-mode system, results, demo footage | All | 2026-04-28 | Urgent | Not Started | Sections: Cody's storage challenge, our approach, benchmark numbers, live demo clip |
| Prepare 2-minute live demo segment | KD, RR | 2026-04-29 | Urgent | Not Started | Show: camera feed, foreground mask, Mode 0/1 output, storage stats, metadata query |
| Rehearse full presentation as a team | All | 2026-04-30 | Important | Not Started | All team members present. |
| Submit final deliverable to course portal | All | 2026-05-01 | Urgent | Not Started | Hard deadline: May 6, 2026. |

---

## Milestone 4 - Sponsor meeting (Apr 15) - new requirements
**Added:** Apr 18, 2026 · **Due:** May 6, 2026
**Source:** NIWC/DIU weekly sync - Cody Hayashi, Geena Wann-Kung, and Sean (new NIWC contact)

These tasks come directly from the Apr 15 meeting. Assign owners this week - same hard deadline as M3.

### 4.1 - HLS live streaming integration

Cody recommended HLS (HTTP Live Streaming) as the browser delivery protocol, with hls.js (https://github.com/video-dev/hls.js/) for playback - MIT-licensed and fully open source. For camera-to-server transport, RTSP is the right choice because most cameras already speak it. The recommended architecture: camera sends RTSP → pipeline server → FFmpeg transcodes to HLS → hls.js plays in browser. Cody also mentioned the Hawaii state traffic cams at gookami.org as a free RTSP test source.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research HLS pipeline: FFmpeg outputs .m3u8 + .ts chunks, Flask serves them | KD | 2026-04-25 | Urgent | Done | Implemented in `src/gui/app.py` - 5 routes: `/api/hls/start`, `/api/hls/stop`, `/api/hls/status`, `/api/hls/<cam>/playlist.m3u8`, `/api/hls/<cam>/<seg.ts>`. |
| Integrate hls.js into index.html for browser-based HLS playback | KD | 2026-04-25 | Urgent | Done | CDN: `https://cdn.jsdelivr.net/npm/hls.js@latest`. `Hls.isSupported()` check with native HLS fallback for Safari. Inline player with 4s startup wait. |
| Add RTSP URL input to GUI + validate with `ffprobe` before starting pipeline | KD | 2026-04-26 | Important | Done | RTSP URL / webcam index / file path input in "Live Stream" sidebar section. Camera ID field, start/stop buttons, status message, inline `<video>` player. |
| Flask HLS segment server: generate + serve playlist and .ts chunks as pipeline runs | KD | 2026-04-26 | Important | Done | Python annotator thread (ROI boxes + corner overlay) pipes rawvideo to FFmpeg stdin. FFmpeg: `-preset ultrafast -tune zerolatency -hls_time 2 -hls_list_size 5 -hls_flags delete_segments`. Stale `.ts`/`.m3u8` cleared on start. Cache-bust `?t=` on playlist URL. |
| Test HLS end-to-end: RTSP in → pipeline → HLS out → hls.js in browser | KD, RR | 2026-04-28 | Important | Done | Tested 2026-04-20 with VLC re-streaming `cameraJitter_traffic.mp4` via `rtsp://localhost:8554/live`. Two vehicle segments captured with green ROI boxes. Fixed stale segment caching (delete .ts/.m3u8 on start, remove `append_list`, cache-bust playlist URL). |
| Export working stream config as JSON (codec, CRF, resolution, mode) | KD | 2026-04-29 | Medium | Not Started | Cody asked for a "save config" button that exports known-working stream parameters so they can be reproduced on DoD hardware without guessing. |

### 4.2 - AV1 codec support (royalty-free)

AV1 is from the Alliance for Open Media (Apple, Google, Microsoft, Netflix, Amazon) and is 100% royalty-free. FFmpeg supports it via `libaom-av1` (reference encoder, very slow) and `libsvtav1` (SVT-AV1, much faster). Use SVT-AV1 for anything real-time. The tradeoff: AV1 encoding is roughly 3-5× slower than H.264 on CPU, so it suits post-offload enhancement more than live recording. Still a strong talking point with the sponsor - zero licensing cost for government deployment.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Check AV1 encoder availability in deployed FFmpeg builds | JS | 2026-04-22 | Important | Not Started | Run: `ffmpeg -encoders \| grep av1`. Check for `libaom-av1` and `libsvtav1`. Document in DEV.md. |
| Add `codec` parameter to `ROIEncoder.encode_segment()` - support `libx264` and `libsvtav1` | JS | 2026-04-23 | Important | Not Started | Default stays `libx264`. AV1 CRF scale differs: ~35 foreground, ~55 background (equivalent quality to H.264 CRF 18/45). |
| Add codec selector dropdown to GUI (H.264 / AV1) | KD | 2026-04-24 | Medium | Not Started | AV1 option disabled if encoder not detected at startup. Show warning: "AV1 is ~3× slower to encode on CPU." |
| Benchmark AV1 vs H.264 encode time and output file size on CPU hardware | JS | 2026-04-25 | Important | Not Started | Same test clip, both codecs. Report: encode time (sec), output size (MB), PSNR. Document in `docs/av1_benchmark.md`. |
| Add AV1 section to `docs/final_report.md` | KD | 2026-04-26 | Medium | Not Started | Highlight for sponsor: AV1 = zero licensing cost. Note real-time encoding trade-off vs H.264. |

### 4.3 - Rich metadata: color detection + robust object classification

Geena asked about searching by vehicle color ("do you think we could try by color?"). Cody built on that: take the center 50% of each bounding box, build a color histogram in HSV space, find the dominant hue, and store it as a label. This is low-effort relative to the value - you already have the bounding boxes and the frame. The current `classify_object()` function uses only `roi_count` to guess vehicle vs person, which is not reliable. This task replaces it with a contour-based classifier using aspect ratio and area.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Implement `detect_dominant_color(frame, bbox)` - HSV histogram on center 50% of ROI | AM | 2026-04-23 | Important | Not Started | `cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)`. Build H histogram. Map peak hue to label: red, orange, yellow, green, blue, purple, white, black, gray. |
| Add `dominant_color` column to `segments` DB schema | AM | 2026-04-23 | Important | Not Started | ALTER TABLE migration in `initialize_database()`. One color label per segment (majority color across all ROIs). |
| Replace `classify_object()` heuristic with contour-based size classifier | AM | 2026-04-23 | Important | Not Started | Current: `roi_count > 10 → vehicle`. Replace with: bbox aspect ratio + area. Tall+narrow = person. Wide+long = vehicle. Large = truck/bus. |
| Add `object_confidence` column to DB (float 0.0-1.0) | AM | 2026-04-24 | Medium | Not Started | Low-confidence segments tagged `unknown`. Filter by confidence threshold in query UI. |
| Add `?color=blue` filter to `/api/query_segments` | AM | 2026-04-24 | Important | Not Started | `query_by_type()` extended to accept optional `color` param. SQL: `WHERE dominant_color = ?` |
| Add color search dropdown to Query Archive sidebar in GUI | KD | 2026-04-25 | Important | Not Started | Options: All / Red / Blue / Green / White / Black / Gray / Yellow / Orange. Wire to `/api/query_segments?color=`. |
| Unit tests for color detection and updated classifier | AM | 2026-04-25 | Important | Not Started | Tests: known-color synthetic ROIs, edge cases - very dark, overexposed, gray background. |

### 4.4 - Adaptive mode switching

Riley proposed a context switch between modes based on traffic density and time of day - Mode 0 when traffic is constant (background can't refresh), Mode 2 when the scene is sparse. Cody and Geena approved. Cody also asked specifically about background refresh interval for Mode 2: "is there value in updating the background once every half hour?" The answer is yes - the `bg_refresh_interval` parameter handles forced refreshes.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Implement `AdaptiveModeController` - switch modes based on traffic density | KD | 2026-04-26 | Important | Not Started | Configurable thresholds: `activity_rate` (ROIs/sec) and `background_staleness` (seconds since last clean frame). High activity → Mode 0. Low activity → Mode 1 or 2. |
| Background staleness tracking for Mode 2 - refresh keyframe if >N seconds | KD | 2026-04-26 | Important | Not Started | `bg_refresh_interval` param (default 1800s). Capture new keyframe when the scene is empty long enough to refresh. |
| Expose adaptive mode toggle and thresholds in GUI | KD | 2026-04-27 | Medium | Not Started | Checkbox: "Auto mode switching". Sliders for activity threshold and background refresh interval. |
| Unit tests for `AdaptiveModeController` transitions | KD | 2026-04-27 | Medium | Not Started | Test: mode changes at threshold crossing; mode stays stable below threshold; correct fallback when background is stale. |

### 4.5 - uv package manager migration

Sean (NIWC) explicitly asked for this: migrate from `pip` to `uv` (from Astral, https://astral.sh/uv). uv manages virtualenvs, locks the Python version, and avoids system package conflicts. DoD security teams prefer it because it eliminates dependency drift between machines.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Migrate to `uv` - create `pyproject.toml` and `uv.lock` | KD | 2026-04-22 | Urgent | Done | `pyproject.toml` created with all deps; `basicsr`/`realesrgan` moved to optional `[enhance]` extra. Run `uv lock` on a real machine to generate `uv.lock`. |
| Update README.md install instructions - `uv sync` as primary method | KD | 2026-04-23 | Important | Done | Primary: `uv sync`. Secondary: `pip install -r requirements.txt`. Note FFmpeg still needs system install. |
| Update DEV.md with `uv` setup steps | KD | 2026-04-23 | Medium | Done | Option A (uv) and Option B (pip) both documented. `uv run pytest` added to test section. Enhancement install updated to `uv sync --extra enhance`. |
| Verify `uv` install works on Windows, macOS, and Linux | KD | 2026-04-24 | Important | Not Started | Test on at least two platforms. Document any platform-specific issues (Windows path separators, FFmpeg detection). |

### 4.6 - CPU compute benchmarks per mode

Geena: "Knowing how much power is consumed is helpful - we want to bring this out in the field." Cody: "How much compute does each mode take, and how long on a typical laptop?" This is a required deliverable for field deployment planning - without numbers, the sponsor can't decide whether to run this on a Raspberry Pi, an old x86 box, or something else.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Benchmark CPU usage and encode time per mode (0, 1, 2, 3) on a standard laptop | JS | 2026-04-26 | Important | Not Started | Use `psutil` for CPU%. Same 60-sec test clip for all modes. Report: avg CPU%, peak CPU%, encode time, output file size, storage/hr. |
| Add per-mode compute table to `docs/stress_test_results.md` | JS | 2026-04-27 | Important | Not Started | Table: Mode → avg CPU% → encode time → storage/hr → estimated battery drain. |
| Estimate field battery life per mode (3-hour laptop battery as baseline) | JS | 2026-04-27 | Medium | Not Started | Formula: `battery_hours = 3h × (idle_CPU% / mode_CPU%)`. |

### 4.7 - Electron desktop app (stretch goal)

Cody: "Web app is number one, but if you can also bundle as Electron, that's great for field testing with no network." Geena agreed it's useful for bandwidth-constrained DoD environments. Cody was clear: "If it takes a day or days, skip it." Do this only if packaging is straightforward. No React - use vanilla HTML/JS (already compliant with DoD network restrictions).

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research Electron packaging for Flask+Python app | KD | 2026-04-24 | Medium | Not Started | Option A: Electron shell that launches Flask subprocess, opens `localhost:5000`. Option B: PyInstaller bundle + Electron wrapper. Estimate time cost first. |
| Package app as Electron desktop app (if feasible) | KD | 2026-04-27 | Medium | Not Started | Only do this if research shows it takes under one day. No React - vanilla HTML/JS already compliant. |

### 4.8 - Compression method literature review

Cody asked: "Are there research papers for lossy compression that selectively drops data like ours?" Riley pointed out it's not apples-to-apples - traditional compression encodes everything, ours selectively discards. Cody said a literature review finding similar approaches would be valuable, especially if there's prior work on ROI-based or event-driven compression for surveillance.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Search for papers on background-subtraction-based selective video compression | KD | 2026-04-24 | Medium | Not Started | Search: IEEE Xplore, arXiv. Terms: "selective video compression", "ROI-based video compression surveillance", "event-driven video encoding static camera". |
| Write `docs/compression_comparison.md` - 1-page comparison summary | KD | 2026-04-26 | Medium | Not Started | Compare our approach to: naive H.264, HEVC, motion-JPEG, and any similar selective systems found. Note intentional asymmetry - we trade data for storage. |

---

## Milestone 5 - Sponsor meeting Apr 22 - new requirements
**Added:** Apr 27, 2026 · **Due:** May 6, 2026
**Source:** NIWC/DIU weekly sync - Cody Hayashi, Geena Wann-Kung (Riley presented; Kheiven not present)

These tasks come directly from the Apr 22 meeting. Cody's closing: metrics are the single biggest gap - without per-mode CPU and latency numbers, operators can't make hardware decisions and the project doesn't have publishable data.

### 5.1 - Per-mode metrics display in GUI

Cody: "Good metrics could lead to publishing after the class ends." He wants CPU%, encode time, compression ratio, and latency from ingest to HLS - all broken out by mode and shown in the GUI at the end of a demo run.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Benchmark CPU% and encode time per mode on laptop hardware | JS | 2026-05-04 | Urgent | Not Started | Same 60-sec test clip, all four modes. Use `psutil`. Report avg CPU%, peak CPU%, encode time, output size. Already tracked in 4.6 - this is the same task. |
| Measure latency from ingest to HLS output in browser | KD | 2026-05-04 | Urgent | Not Started | Timestamp at RTSP frame receipt and at HLS chunk delivery. Report avg end-to-end latency per mode. |
| Run all benchmarks on Raspberry Pi or equivalent low-power hardware | KD, JS | 2026-05-04 | Important | Not Started | Cody was explicit: operators use low-power COTS hardware in the field. Pi or similar. |
| Add per-mode metrics display to demo end screen in GUI | RR | 2026-05-05 | Important | Not Started | Show after demo completes: CPU%, compression ratio, storage savings per mode. Cody asked for this at end of April 22 meeting. |

### 5.2 - Object type separation in DB and query UI

Everything is currently classified as "vehicle." Cody and Geena both want operators to be able to distinguish people, vehicles, and unknown objects in the query interface before May 6.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Separate people / vehicle / unknown in DB classification | AM | 2026-05-03 | Urgent | Not Started | Pipeline already passes `object_type` to `insert_segment()` but the classifier only ever writes "vehicle". Fix `classify_object()` to emit "person", "vehicle", or "unknown" based on bbox size/aspect ratio. |
| Surface people / vehicle / unknown as distinct options in query UI | AM | 2026-05-03 | Important | Not Started | Query Archive sidebar dropdown should list Person / Vehicle / Unknown as separate filter options, not just a single "vehicle" default. |

### 5.3 - Demo output viewable in GUI

Cody noted in the April 22 demo that watching the output still required opening a file locally. Riley flagged it. Needs to be fixed before May 6.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Make demo output viewable in-browser (not just local file) | RR | 2026-05-03 | Urgent | Not Started | Processed clips should be playable directly in the GUI via the existing `/api/media` route. Should require no local file system access from the operator. |

### 5.4 - Super-resolution honest test

Cody: "I want to see where the tech actually is - not a demo optimized for the best case. A real test on footage where a person is small in the background."

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Run super-resolution on real low-res footage with a small person in frame | KD | 2026-05-04 | Medium | Not Started | Use gookami.org footage or equivalent. Compare bicubic fallback vs SR model output on a genuinely small/blurry detection. Document result honestly - including if the enhancer doesn't recover enough detail. |

### 5.5 - Diverse test footage

Geena: use a camera with oncoming traffic, not a side view. Oncoming vehicles show varied sizes, colors, and speeds, which exercises the detector more. She pointed to a Pearl City intersection specifically.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Pull rush hour + 2am footage from gookami.org (same camera) | KD, RR | 2026-05-03 | Important | Not Started | Same camera, two time windows. Oncoming traffic view near Pearl City shopping center. Shows Mode 1 storage advantage on a real scene vs synthetic benchmark. |

### 5.6 - May 6 presentation logistics

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Send Cody invite for May 6 capstone presentation | KD | 2026-04-28 | Urgent | Not Started | He confirmed he can attend remotely. Use email from meeting notes. Get representative camera data ready before then so he can share context with colleagues. |

### 5.7 - Compression literature review

Cody flagged that if there's prior academic work on ROI-based or event-driven video compression for surveillance, citing it strengthens the report. If there isn't, that's worth stating too.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Search IEEE Xplore + arXiv for selective/ROI video compression papers | KD | 2026-05-02 | Medium | Not Started | Already tracked in 4.8. Terms: "selective video compression surveillance", "ROI-based video compression static camera", "event-driven video encoding". |

---

## Milestone 6 - Sponsor feedback May 1 - future directions
**Added:** May 1, 2026
**Source:** NIWC security personnel review forwarded by Cody Hayashi - three operators who view this footage daily. Overall reaction: strongly positive. These are the two actionable feature requests from their feedback.

### 6.1 - Reference-object height/weight estimation

The request: once the system can tell a green car from a red car, use objects with known real-world dimensions (a Honda Civic is ~4.5 m long, ~1.8 m wide) as an in-scene ruler to calibrate pixel-to-meter scale. Apply that scale to estimate the height - and, roughly, the weight - of a nearby person. Operators want this for characterizing persons of interest: if there's a confirmed threat, being able to say "approximately 5'10\", stocky build" without footage that's clear enough to run facial recognition is a significant capability.

Implementation sketch:
- Maintain a lookup table of known vehicle make/model dimensions
- When a vehicle is classified with high confidence and the scene has a calibration reference, compute pixels-per-meter from the bounding box
- Use that scale on nearby person bounding boxes to estimate standing height
- Weight estimation from height uses population-average BMI (rough, statistical, explicitly flagged as estimate)
- Store estimate + confidence in DB; surface in segment detail view

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research pixel-to-real-world calibration from bounding boxes for static cameras | KD | TBD | Important | Not Started | Homography or simple perspective divide depending on camera angle. Needs camera height/tilt metadata or auto-calibration from ground-plane assumption. |
| Build reference-object dimension lookup table (vehicle make/model → L×W×H in meters) | KD | TBD | Important | Not Started | Start with common COTS vehicles: sedan ~4.5 m, SUV ~4.8 m, pickup ~5.8 m. Lookup by YOLO class label (car, truck, bus). |
| Implement `estimate_person_dimensions(frame, person_bbox, reference_bbox, reference_class)` | KD | TBD | Important | Not Started | Returns estimated height in meters + confidence score. Weight from height via population-average BMI range. Flag all outputs as statistical estimates. |
| Add `estimated_height_m`, `estimated_weight_kg_range` columns to DB | KD | TBD | Medium | Not Started | ALTER TABLE migration. NULL when no calibration reference visible in segment. |
| Surface height/weight estimate in segment detail view in GUI | KD | TBD | Medium | Not Started | Show in metadata card alongside object_type. Display confidence and "statistical estimate" disclaimer. |
| Unit tests for calibration and estimation functions | KD | TBD | Medium | Not Started | Synthetic test: known bbox sizes at known scale → verify output is within 10% of ground truth. |

### 6.2 - Parked / stationary object alert (configurable dwell time)

The request: detect when an object (vehicle in particular) has been stationary in the scene for longer than a user-configured threshold. A car parked in a lot for months is potentially suspicious. Operators want to set a dwell-time alarm - e.g., alert if any vehicle hasn't moved in 48 hours, or flag a frame as "long-term stationary" in the DB.

Implementation sketch:
- Track object centroids across segments using camera_id + approximate spatial position
- When a new segment is written, check whether a same-class object appeared in the same bounding-box region in all prior segments back to the configurable window
- If yes and elapsed time ≥ threshold → write a `stationary_alert` record to DB and optionally push a notification
- Background: this is different from background subtraction - MOG2 will eventually absorb a stationary object into the background and stop detecting it. The dwell tracker needs to work from the DB record of when the object was last detected moving, not from live mask output

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Design `stationary_object_tracker` schema - what to store per detection to enable retrospective dwell queries | KD | TBD | Important | Not Started | Proposed: `object_tracks` table with `(camera_id, first_seen, last_seen, bbox_centroid_x, bbox_centroid_y, object_class, dwell_s)`. Upsert on each segment write when centroid matches within N px tolerance. |
| Implement `update_object_tracks(camera_id, segment_timestamp, detections)` - upsert centroid-matched tracks | KD | TBD | Important | Not Started | Called from pipeline after each `finish_segment()`. Spatial match: centroid within configurable px radius (default 50 px for 640×480). |
| Implement `query_stationary_alerts(camera_id, dwell_threshold_s)` - return objects dwell > threshold | KD | TBD | Important | Not Started | SQL: `SELECT * FROM object_tracks WHERE dwell_s >= ? AND camera_id = ? ORDER BY dwell_s DESC`. |
| Expose dwell threshold as user-configurable parameter in GUI (sidebar or settings) | KD | TBD | Medium | Not Started | Input: dwell threshold (hours). Default: 24 h. "Check for parked objects" button triggers `query_stationary_alerts()` and shows results in panel. |
| Push GUI notification when a stationary alert fires during a live pipeline run | KD | TBD | Medium | Not Started | Use existing `pushNotif()` system. Fire when `dwell_s` crosses threshold mid-run. Dismiss-able card with centroid thumbnail. |
| Unit tests for track upsert, spatial matching, and dwell query | KD | TBD | Medium | Not Started | Tests: same centroid across 10 segments → single track, correct dwell_s; centroid drift > tolerance → new track; threshold query returns correct rows. |

---

## Team assignments

### Kheiven D'Haiti (KD) - kdhaiti2024@fau.edu

| Section | Area | Status |
|---|---|---|
| 1.1 | Background subtraction tuning | Done ✅ |
| 1.3 | CDnet foreground coverage benchmark | Done ✅ |
| 2.1 | Super-resolution enhancement module | Done ✅ |
| 2.4 | Data integrity validation | Done ✅ |
| 2.4 | CI integration for test_data_integrity.py | Open 🔲 |
| 2.6 | GUI dashboard - Flask app, SSE, all API endpoints | Done ✅ |
| 2.6 | GUI regression tests + API integration tests | Done ✅ |
| 3.1 | AES-256 encryption - initial CBC implementation | Done ✅ |
| 3.1b | YOLO object classification gate (PR #31) | Done ✅ |
| 3.1b | GPU acceleration for enhancer (CUDA/MPS) | Done ✅ |
| 3.1b | Mode label + timer overlay in segments | Done ✅ |
| 3.1b | Double-compositing fix in encode_segment | Done ✅ |
| 3.1b | Test suite repair - streaming encoder API (274 passing) | Done ✅ |
| 3.1b | Session log `docs/session_log_2026-04-26.md` | Done ✅ |
| 3.4 | AI compression research | Done ✅ |
| 3.4 | Deployment packaging research | Open 🔲 |
| 3.5 | demo.sh one-click launcher | Done ✅ |
| 3.5 | Confirm webcam / IP camera real-time input | Open 🔲 |
| 3.5 | No-GPU laptop test | Open 🔲 |
| 3.6 | Final report (`docs/final_report.md`) | Done ✅ |
| 3.6 | Final results notebook (`final_results.ipynb`) | Open 🔲 |
| 3.7 | Repository polish + documentation | Open 🔲 |
| 3.8 | Capstone presentation (team lead) | Open 🔲 |
| 4.1 | HLS streaming + hls.js integration | Done ✅ |
| 4.1 | HLS end-to-end test (RTSP → pipeline → browser) | Done ✅ |
| 4.2 | AV1 codec GUI selector | Open 🔲 |
| 4.3 | Color search dropdown in GUI | Open 🔲 |
| 4.4 | Adaptive mode switching + GUI controls | Open 🔲 |
| 4.5 | uv migration + README/DEV.md updates | Done ✅ |
| 4.7 | Electron desktop app (if feasible) | Open 🔲 |
| 4.8 | Compression literature review | Open 🔲 |
| 5.1 | Latency measurement (ingest → HLS output) | Open 🔲 |
| 5.1 | Run benchmarks on Raspberry Pi / low-power hardware | Open 🔲 |
| 5.4 | Super-resolution honest test on real low-res footage | Open 🔲 |
| 5.5 | Pull diverse footage from gookami.org (rush hour + 2am) | Open 🔲 |
| 5.6 | Send Cody invite for May 6 presentation | Open 🔲 |
| 5.7 | Literature review on selective compression (same as 4.8) | Open 🔲 |
| 6.1 | Reference-object calibration + person height/weight estimation | Open 🔲 |
| 6.2 | Stationary object / parked-car dwell tracker + alert system | Open 🔲 |

### Riley Roberts (RR) - robertsr2022@fau.edu

| Section | Area | Status |
|---|---|---|
| 2.2 | ModeDecision dispatch + mode1 gating (modes.py) | Done ✅ |
| 2.2 | Mode 2 implementation | Done ✅ |
| 2.2 | Mode 3 implementation | Done ✅ |
| 2.6 | DemoMetadataWriter + renderer + split-screen | Done ✅ |
| 2.6 | Extend `test_pipeline.py` (enhance / encrypt / stop) | Open 🔲 |
| 2.6 | `run_demo.py` end-to-end on real footage | Open 🔲 |
| 4.1 | HLS end-to-end test | Open 🔲 |
| 5.1 | Add per-mode metrics display to demo end screen | Open 🔲 |
| 5.3 | Make demo output viewable in-browser | Open 🔲 |
| 5.5 | Pull diverse footage from gookami.org (rush hour + 2am) | Open 🔲 |

### Victor Teixeira (VT) - vdesouzateix2023@fau.edu

| Section | Area | Status |
|---|---|---|
| 1.3 | PSNR, SSIM, compression ratio metrics | Done ✅ |
| 1.3 | `milestone1_benchmark.ipynb` | Done ✅ |
| 3.1 | Upgrade AES-256-CBC to AES-256-GCM | Done ✅ |
| 3.1 | Encrypt/decrypt round-trip unit tests (24 tests) | Done ✅ |
| 3.1 | IV + salt storage in DB per segment | Open 🔲 |
| 3.1 | Password-protected incident clip export | Open 🔲 |

### Ashleyn Montano (AM) - amontano2023@fau.edu

| Section | Area | Status |
|---|---|---|
| 1.4 | SQLite schema, WAL mode, `idx_cam_time` index | Done ✅ |
| 1.4 | `insert_segment()` + camera / time queries | Done ✅ |
| 1.4 | Unit tests: database (20 tests) | Done ✅ |
| 2.3 | Add `object_type` field + extend `insert_segment()` | Done ✅ |
| 2.3 | `query_by_type()` + daily storage summary + busiest CLI | Done ✅ |
| 2.3 | Unit tests for new queries and CLI tool | Done ✅ |
| 2.7 | Detection tuning - calibration research (w/ JS) | Done ✅ |
| 3.2 | Multi-type query + `min_roi_count` filter (`m3-metadata-query-fix`) | Done ✅ |
| 3.2 | Full-text / multi-tag search + README docs | Open 🔲 |
| 4.3 | Color detection + DB column + updated object classifier | Open 🔲 |
| 5.2 | Separate people / vehicle / unknown in DB and query UI | Open 🔲 |

### Jorge Sanchez (JS) - jorgesanchez2022@fau.edu

| Section | Area | Status |
|---|---|---|
| 1.2 | ROI encoding - FFmpeg stdin pipe, dual-CRF | Done ✅ |
| 1.2 | Integration tests for ROI encoder (18 tests) | Done ✅ |
| 2.5 | Algorithm comparison notebook + recommendation doc | Done ✅ |
| 2.5 | Stress test + memory bounds + storage extrapolation | Done ✅ |
| 2.7 | Detection tuning - calibration research (w/ AM) | Done ✅ |
| 3.3 | Watchfolder daemon (`watchfolder.py`) | Done ✅ |
| 3.3 | Multi-source RTSP input (`multi_source.py`) | Done ✅ |
| 4.2 | AV1 encoder check + `ROIEncoder` codec param | Open 🔲 |
| 4.2 | AV1 vs H.264 benchmark | Open 🔲 |
| 4.6 | CPU compute benchmarks per mode | Open 🔲 |
| 5.1 | Run benchmarks on Raspberry Pi / low-power hardware | Open 🔲 |

---

## Branch and PR strategy

```
main          ← stable, always working, tagged at each milestone
  └── dev     ← integration branch (all features merge here first)
        ├── feature/background-subtraction-tuning
        ├── feature/roi-ffmpeg-encoding
        ├── feature/benchmarking-milestone1
        ├── feature/metadata-database
        ├── feature/enhancement-superresolution
        ├── feature/benchmarking-visdrone
        ├── feature/stress-test
        ├── feature/mode-system
        ├── feature/demo-prep
        ├── feature/hls-streaming
        ├── feature/av1-codec
        ├── feature/color-metadata
        ├── feature/final-report
        └── feature/docs-cleanup
```

Rules: never commit directly to `main`. Always branch from `dev`. Every PR into `dev` needs at least one reviewer. Merge `dev` into `main` only at milestone completions.

---

## Timeline

| Milestone | Description | Target | Status |
|---|---|---|---|
| Phase 0 | Repo scaffold, initial code | Jan 13, 2026 | ✅ Complete |
| Milestone 1 | Core pipeline + metrics + database | Mar 31, 2026 | ✅ Complete · tagged v0.1.0 |
| Milestone 2 | Enhancement + stress test + algorithm comparison + GUI | Apr 18, 2026 | ✅ Complete |
| Milestone 3 | Encryption, watchfolder, multi-source, YOLO gate, test repair | Apr 26, 2026 | ✅ Complete |
| Milestone 4 (Apr 15 meeting) | HLS streaming, uv migration, color detection, benchmarks | May 6, 2026 | In Progress |
| Milestone 5 (Apr 22 meeting) | Per-mode metrics, object type split, GUI demo viewer, benchmarks, footage | May 6, 2026 | In Progress |
| Milestone 6 (May 1 feedback) | Reference-object height estimation, parked-car dwell alert | Post-M3 / TBD | Not Started |
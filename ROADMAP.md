# Project Roadmap
## EGN 4950C Group 16 — Open Source Selective Video Compression
**Florida Atlantic University · Spring 2026 · Sponsor: Defense Innovation Unit (DIU) / NIWC Pacific**
**Hard deadline:** May 6, 2026

---

## Who owns what

| Member | Sections | Key open tasks |
|---|---|---|
| **Kheiven D'Haiti (KD)** | 2.4, 2.6, 3.4, 3.5, 3.6, 4.4, 4.5, 4.8 | GUI regression tests, HLS streaming, uv migration, final report numbers, demo prep, adaptive mode |
| **Riley Roberts (RR)** | 2.2 (Mode 2/3), 2.5, 2.6 (partial) | Mode 2, Mode 3, extend test_pipeline.py, run_demo.py end-to-end, final benchmarks notebook |
| **Victor Teixeira (VT)** | 3.1 | AES-256-GCM upgrade, IV/salt in DB, password export, encrypt/decrypt tests |
| **Ashleyn Montano (AM)** | 3.2, 4.3 | Color detection + DB column, object classifier rewrite, full-text search, stable query API |
| **Jorge Sanchez (JS)** | 2.5, 4.6 | CPU benchmark per mode, detection tuning (done), watchfolder ingestion |

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

## Phase 0 — Project setup (completed Jan 13, 2026)

Initial repo scaffolding done before the semester sprint. No owner tracking needed — all complete.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Repo scaffold + directory structure | KD | 2026-01-13 | Urgent | Done | Initial commit to `main` |
| `requirements.txt` — all Python dependencies | KD | 2026-01-13 | Important | Done | opencv, ffmpeg-python, Flask, pytest, etc. |
| `.gitignore` for Python, video files, model weights | KD | 2026-01-13 | Medium | Done | Excludes `outputs/`, `models/`, `*.mp4` |
| `BackgroundSubtractor` class skeleton | KD | 2026-01-13 | Important | Done | MOG2 / KNN / GMG |
| `ROIEncoder` skeleton + FFmpeg integration | JS | 2026-01-13 | Important | Done | Stub for dual-CRF encoding |
| `Pipeline` orchestrator skeleton | KD | 2026-01-13 | Important | Done | Frame loop + segment flush structure |
| `metrics.py` utility skeleton (PSNR, SSIM) | VT | 2026-01-13 | Medium | Done | Scaffold only |
| Unit test file scaffolded | KD | 2026-01-13 | Medium | Done | `tests/test_background_subtraction.py` |

---

## Milestone 1 — Core pipeline functional (completed Mar 31, 2026)
**Branch:** `dev` merged to `main` · tagged `v0.1.0` on 2026-03-29

The goal for M1 was a working end-to-end pipeline on a real test clip with measurable, verifiable compression results. Every task below was completed and verified before the March 31 deadline.

### 1.1 — Background subtraction tuning

MOG2 and KNN were both tuned against 46 CDnet scenes. MOG2 came out ahead on false-positive rate across edge-case categories (night, shadow, dynamic background) and was adopted as the primary algorithm. The night_mode flag and morphological cleanup were added after the initial CDnet sweep revealed noise in low-light masks.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Tune MOG2 params — night_mode, CLAHE, varThreshold | KD | 2026-03-29 | Important | Done | `night_mode` flag; `VAR_THRESHOLD_DAY=16` / `NIGHT=30`; CLAHE preprocessing |
| Tune KNN params; compare with MOG2 on 46 CDnet scenes | KD | 2026-03-29 | Important | Done | Full CDnet sweep; MOG2 recommended; results in `outputs/cdnet_batch_results.log` |
| Morphological cleanup (erosion/dilation) to remove mask noise | KD | 2026-03-29 | Medium | Done | `MORPH_CLOSE` + `MORPH_OPEN` with elliptical kernel; `morph_kernel_size` param exposed |
| Minimum contour area filter for small detections | KD | 2026-03-29 | Medium | Done | `min_area` param (default 500 px); 1500–2000 px recommended for HD footage |
| Unit tests for background subtraction (29 tests) | KD | 2026-03-29 | Important | Done | `tests/test_background_subtraction.py` — mask gen, edge cases, night mode |

### 1.2 — ROI encoding pipeline

The encoder pipes raw numpy frames directly to FFmpeg via stdin, bypassing the lossy XVID intermediate that was used in early prototypes. Dual-CRF encoding — CRF 18 for foreground, CRF 45 for background — was validated against 18 integration tests.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Implement `encode_segment()` — pipe numpy frames to FFmpeg via stdin | JS | 2026-03-29 | Urgent | Done | `src/compression/roi_encoder.py`; uses `communicate()` to avoid pipe deadlock |
| Dual-pass CRF encoding: foreground CRF 18, background CRF 45 | JS | 2026-03-29 | Urgent | Done | `has_targets` flag selects `foreground_crf` vs `background_crf` per segment |
| Validate output is a playable MP4 | JS | 2026-03-29 | Important | Done | Raises `RuntimeError` if output missing or zero bytes after FFmpeg |
| Implement `get_file_size()` and log pre/post compression sizes | JS | 2026-03-29 | Medium | Done | Returns bytes or 0 for missing file; logged per segment |
| Integration tests for ROI encoder (18 tests) | JS | 2026-03-29 | Important | Done | `tests/test_roi_encoder.py` — encode, CRF, DB row, error handling |

### 1.3 — Metrics and benchmarking

Victor implemented PSNR, SSIM, and compression ratio in `metrics.py` and built the benchmark notebook. Kheiven ran the full 46-scene CDnet sweep to establish foreground coverage baselines.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Implement `compute_psnr()` and `compute_ssim()` | VT | 2026-03-29 | Important | Done | `src/utils/metrics.py`; verified against known reference values |
| Implement `compute_compression_ratio()` | VT | 2026-03-29 | Medium | Done | Handles zero/negative inputs |
| CDnet foreground coverage benchmark across all 46 scenes | KD | 2026-03-29 | Important | Done | `scripts/run_all_cdnet.py`; per-category avg FG% in `outputs/cdnet_batch_results.log` |
| Create `notebooks/milestone1_benchmark.ipynb` | VT | 2026-03-29 | Important | Done | Runs pipeline on test clip; reports PSNR, SSIM, compression ratio |
| Document results in `docs/milestone1_results.md` | VT | 2026-03-29 | Medium | Done | Compression ratio, PSNR, SSIM results documented |

### 1.4 — Metadata database

Ashleyn built the SQLite schema with WAL mode and an index on `(camera_id, timestamp)`. This made it possible to later extend the schema for `object_type` without a migration headache.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Create SQLite `segments` schema (`db.py`) with WAL mode and index | AM | 2026-03-29 | Important | Done | WAL mode, `idx_cam_time` index, type hints, `SegmentRow` alias |
| Integrate DB writes into pipeline — one row per encoded segment | AM | 2026-03-29 | Important | Done | `insert_segment()` called in `encode_segment()` after every successful encode |
| Query: all segments from camera X with targets in last N hours | AM | 2026-03-29 | Important | Done | `query_recent_targets(camera_id, hours, db_path)` — ORDER BY timestamp DESC |
| Unit tests for database (20 tests — WAL, index, multi-camera, edge cases) | AM | 2026-03-29 | Important | Done | `tests/test_database.py` — expanded from 2 to 20 tests |

---

## Milestone 2 — Enhancement + stress testing (completed Apr 18, 2026)
**Branch:** `dev` — merge to `main` when all tests pass

M2 added three sponsor-requested features: super-resolution enhancement for post-offload analysis, a full algorithm comparison between MOG2 and KNN, and stress testing to validate the pipeline under continuous load. The GUI dashboard and demo rendering system were also built in this milestone. Requirements came from Sponsor Meeting 2 (Apr 1, 2026).

### 2.1 — Super-resolution enhancement module

Victor built the Enhancer class with three backends: Real-ESRGAN, OpenCV DNN super-res, and bicubic (always available as fallback). The `--enhance` flag runs the enhancement in-place on foreground ROIs before encoding each segment.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research Real-ESRGAN CPU inference; document model download in DEV.md | KD | 2026-04-09 | Important | Done | DEV.md updated; `models/` gitignored; basicsr build issues on Py 3.14 noted |
| Implement `Enhancer.upscale_frame()` — Real-ESRGAN / dnn_superres / bicubic | KD | 2026-04-09 | Urgent | Done | `src/enhancement/enhancer.py`; three backends; bicubic always available |
| Implement `Enhancer.upscale_roi(frame, bbox)` — upscale only bounding region | KD | 2026-04-09 | Important | Done | Crops ROI, upscales, resizes back to original bbox dims, pastes in-place |
| Integrate enhancement into pipeline as optional pass (`--enhance` flag) | KD | 2026-04-09 | Urgent | Done | `--enhance / --enhance-model / --enhance-scale`; bicubic fallback if model unavailable |
| Benchmark enhancement processing time per frame on CPU hardware | KD | 2026-04-09 | Medium | Done | `notebooks/milestone2_enhancer_benchmark.ipynb` |
| Unit tests for Enhancer (output dims, bbox validation, `is_available()`) | KD | 2026-04-09 | Important | Done | `tests/test_enhancer.py` — upscale x2/x4, ROI paste, enhance_batch, graceful unavailable |

### 2.2 — Mode dispatch system

Riley built the mode dispatch layer in `modes.py` and integrated it into the pipeline. Mode 0 and Mode 1 are live. Mode 2 and Mode 3 are the next open implementation tasks — they were scoped in the sponsor meeting but not yet built.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Mode dispatch: `modes.py` — ModeDecision, validate_mode, get_mode_decision | RR | 2026-04-09 | Urgent | Done | PR #6 `feat/mode-system` merged; fully tested; pipeline uses `get_mode_decision()` per frame |
| Mode 1 frame-gating unit tests (`test_pipeline.py`) | RR | 2026-04-09 | Important | Done | 2/2 passing; covers exact-segment-boundary EOF and mode1 frame selection |
| Implement Mode 2: one background keyframe + per-frame object patches | RR | 2026-04-11 | Urgent | Not Started | Background frame captured right before motion; only moving-object bbox crops saved per frame. Best for low-traffic scenes. Degrades gracefully to Mode 0 when traffic is constant (background never refreshes). |
| Implement Mode 3: object-only forensic mode — padded crop, no background | RR | 2026-04-11 | Urgent | Not Started | Most aggressive mode — saves only padded bbox crop around detected subject, zero background. Intended for facial recognition and forensic pipelines. |
| Demo/concat mode: stitch all output segments into one playback file | RR | 2026-04-10 | Important | Not Started | Proposed by Riley in Apr 1 sponsor meeting. Lets you review a full session without opening each 60-second clip. |

### 2.3 — Metadata query interface

Ashleyn extended the DB schema with `object_type` and added three new query functions exposed through both a CLI tool and the GUI's Query Archive sidebar.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Add `object_type` tag to DB schema (person, vehicle, cyclist, unknown) | AM | 2026-04-10 | Important | Done | ALTER TABLE migration in `initialize_database()`; default `'unknown'`; `SegmentRow` extended |
| Implement `query_by_type(object_type, camera_id, start_time, end_time)` | AM | 2026-04-13 | Urgent | Done | Parameterized SQL; optional camera + time range filters; exposed via `/api/query_segments` |
| Implement `query_segments_by_target_count()` — busiest segments | AM | 2026-04-13 | Important | Done | Orders by `roi_count DESC`; exposed via `/api/busiest` in GUI |
| Implement `query_daily_storage_summary()` — daily storage by camera | AM | 2026-04-13 | Important | Done | Groups by date + camera_id; exposed via `/api/daily_summary` in GUI |
| CLI query tool: `db_query.py --camera cam_01 --last-hours 24 --type person` | AM | 2026-04-13 | Medium | Done | Supports `--camera`, `--last-hours`, `--type` flags |
| Unit tests for object_type queries | AM | 2026-04-13 | Important | Done | `tests/test_object_type_queries.py` |

### 2.4 — Data integrity validation

A frame-level pixel comparison test was added to catch any silent corruption in the ROI encode/decode cycle. The sponsor was explicit that foreground data loss is unacceptable even at 5%.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Frame-level comparison test: verify ROI pixels survive the encode/decode cycle | KD | 2026-04-09 | Urgent | Done | `tests/test_data_integrity.py` — per-region pixel comparison; pass/fail logged |
| CI integration for `test_data_integrity.py` | KD | 2026-04-18 | Medium | Not Started | Wire into CI so this runs on every PR to `dev`. |

### 2.5 — Algorithm comparison and stress testing

Jorge ran the full algorithm comparison and the 1-hour stress test. Both are done and documented. The stress test uses `tracemalloc` so transient memory spikes get caught, not just endpoint comparisons.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Create `notebooks/algorithm_comparison.ipynb` with side-by-side visualizations | JS | 2026-04-08 | Important | Done | PR #9 — 2026-04-11; MOG2 vs KNN side-by-side; data from `cdnet_batch_results.log` |
| Write `docs/algorithm_comparison.md` — production recommendation | JS | 2026-04-08 | Medium | Done | PR #9 — 2026-04-11; MOG2 recommended as primary; KNN viable for high-motion scenes |
| Write `tests/test_pipeline_stress.py` — 1 hour simulated footage | JS | 2026-04-09 | Important | Done | PR #9; loops test clip; no memory leak; configurable via `STRESS_DURATION_S` env var |
| Verify memory does not grow unbounded over 1 hour of operation | JS | 2026-04-09 | Important | Done | `tracemalloc` peak used (not just endpoints); results in `docs/stress_test_results.md` |
| Extrapolate 1-hour results to estimate storage for 60-day retention (100 cameras) | JS | 2026-04-10 | Medium | Done | Sponsor requirement: 60 days on 100+ camera systems |
| Document stress test findings in `docs/stress_test_results.md` | JS | 2026-04-11 | Medium | Done | Runtime, peak memory, projected weekly/60-day storage, Mode 0 vs Mode 1 |

### 2.6 — Demo rendering system + web dashboard GUI

Kheiven built the Flask dashboard and wired in Riley's demo rendering system. The GUI had several regressions during the env migration that required fixing — path traversal sanitization, the tkinter file picker workaround, and per-run database isolation are all covered.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Build `DemoMetadataWriter` + JSONL sidecar per buffered frame | RR | 2026-04-09 | Important | Done | `src/demo/demo_metadata.py`; context manager; writes frame index, time, mode, segment, regions |
| Build `render_demo()` + annotated video renderer | RR | 2026-04-09 | Urgent | Done | `src/demo/demo.py`; supports `standard` and `roi_tint` views; `draw_boxes` flag |
| Build `build_split_screen_from_manifest()` — side-by-side mode comparison | RR | 2026-04-09 | Important | Done | `src/demo/split_screen.py`; auto-detects 2–4 mode outputs from `manifest.json` |
| Build `run_all_demos()` orchestrator + `manifest.json` writer | RR | 2026-04-09 | Urgent | Done | `src/demo/run_demo.py`; supports `--modes`, `--view`, `--no-boxes` CLI flags |
| Build Flask dashboard — SSE live log, start/stop/status/segments/storage routes | KD | 2026-04-09 | Urgent | Done | `src/gui/app.py`; SSE with `Last-Event-ID` backlog replay; 16 API routes total |
| Add `/api/browse` — native OS file picker via subprocess (Windows-safe) | KD | 2026-04-09 | Important | Done | tkinter dialog spawned in subprocess; avoids main-thread restriction on Windows |
| Add `/api/media` — serve any local video by absolute path | KD | 2026-04-09 | Important | Done | Fixes segment playback when output dir is outside project root |
| Add `/api/demo` + `/api/demo/status` — background demo runner | KD | 2026-04-18 | Important | Done | Background thread calls `run_all_demos()`; polls `manifest.json` to build playable URLs |
| Add multi-mode comparison UI (Mode 0/1 checkboxes, demo output panel) | KD | 2026-04-18 | Important | Done | Spinner during render; video player with mode tabs; auto-loads first result |
| Add segment inline preview player in output segments table | KD | 2026-04-18 | Important | Done | Clicking play in table loads clip in inline player below the table |
| Add Query Archive sidebar — type/camera/time filters, SEARCH/BUSIEST/DAILY | KD | 2026-04-18 | Important | Done | Calls `/api/query_segments`, `/api/busiest`, `/api/daily_summary`; inline results with play |
| Fix `initialize_database()` — pass `db_path` arg so each run gets isolated DB | KD | 2026-04-18 | Urgent | Done | Was defaulting to `metadata.db` in CWD; now writes to per-run output directory |
| Fix `ROIEncoder` — pass `db_path` to constructor (was hardcoded `outputs/`) | KD | 2026-04-18 | Urgent | Done | Encoder now writes to correct per-run DB |
| SSE Last-Event-ID resume + deque log history | KD | 2026-04-09 | Medium | Done | Monotonic event IDs; `collections.deque(maxlen=300)`; no duplicate lines on reconnect |
| GUI regression tests: `/api/start` `/api/stop` `/api/status` `/api/segments` `/api/storage` | KD | 2026-04-18 | Important | Done | `tests/test_gui_api.py` — 24 tests; covers HTTP status, JSON shape, state transitions, DB-backed responses. |
| Extend `test_pipeline.py`: `--enhance` bicubic path, `--encrypt` round-trip, stop_event | RR | 2026-04-18 | Important | Not Started | Bicubic test needs no SR weights. Encrypt test: verify `.enc` written, `.mp4` deleted. Stop-event: break mid-loop. |
| Run `run_demo.py` end-to-end on a real test clip — verify split-screen output | RR | 2026-04-18 | Important | Not Started | `python -m src.demo.run_demo --input data/test.mp4 --output outputs/ --camera-id cam_test` |

### 2.7 — Detection tuning

Calibrated MOG2 and KNN parameters across three lighting conditions (day, night, mixed) on synthetic test footage. The tuned defaults (varThreshold=50, detectShadows=False) cut false positives to zero on static scenes while keeping detection latency under 3 frames.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research + calibrate MOG2/KNN params — day, night, gate, walkway footage | AM, JS | 2026-04-18 | Important | Done | Results in `docs/detection_tuning.md`; varThreshold=50, detectShadows=False as tuned defaults |
| Measure FP/FN rates across lighting conditions | AM, JS | 2026-04-18 | Important | Done | Full FP/FN table in `docs/detection_tuning_results.md` (Jorge); all conditions FP < 2% |
| Update BackgroundSubtractor defaults + write detection accuracy unit tests | AM, JS | 2026-04-18 | Medium | Done | `tests/test_detection_accuracy.py`; tuned params committed to `background_subtraction.py` |

---

## Milestone 3 — Final demo + deliverables (due May 6, 2026)
**Branch:** `dev` merged to `main` after final review

M3 is everything needed to ship: encryption hardening, polished metadata search, a working demo on target hardware, a complete final report, and the capstone presentation. Most tasks here are Not Started — this is the sprint for the last two weeks.

### 3.1 — Security and encryption

Victor — the AES-256-CBC implementation is in `src/utils/encryption.py` and works. The GCM upgrade is the open task: CBC has no authentication tag, so bit-flip attacks pass silently. GCM is a drop-in replacement via the `cryptography` lib and should not take more than a day.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| AES-256-CBC encryption for output video files (`--encrypt` flag) | KD | 2026-04-09 | Urgent | Done | `src/utils/encryption.py`; PBKDF2 600k iters; password or raw-key mode; IV+salt in header |
| Upgrade AES-256-CBC to AES-256-GCM (authenticated encryption) | VT | 2026-04-18 | Important | Not Started | CBC has no auth tag — bit-flip attacks pass silently. GCM is a drop-in via `cryptography` lib. |
| Store IV + salt in DB per segment | VT | 2026-04-25 | Medium | Not Started | Required for per-segment decryption without re-prompting the user for their password. |
| Password-protected incident clip export | VT | 2026-04-25 | Important | Not Started | Sponsor showed commercial systems charge extra for this. Include by default. |
| Encrypt/decrypt round-trip unit tests | VT | 2026-04-25 | Important | Not Started | Verify `.enc` written; decryption recovers original bytes exactly; test both password and raw-key paths. |

### 3.2 — Searchable metadata index

Ashleyn — the query functions exist in `db.py` and are wired into the GUI. The open tasks are stabilizing the API shape and adding documentation so the sponsor can rely on it.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Stable query API with full filtering (type, camera, time range) | AM | 2026-04-22 | Urgent | Done | `query_by_type(object_type, camera_id, start_time, end_time)` returns matching segment paths |
| Full-text / tag search + README docs | AM | 2026-04-25 | Medium | Not Started | Extend query interface to support multi-tag filtering; document in README. |

### 3.3 — External input and ingestion

Jorge — these came from the sponsor's request to accept footage from body cameras and other external sources, not just the live pipeline output.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Watchfolder daemon / drag-and-drop video import for external footage | JS | 2026-04-26 | Medium | Not Started | Watch a drop folder and auto-ingest new video files into the pipeline. Body camera support. |
| Multi-source input support | JS | 2026-04-26 | Medium | Not Started | Extend `FrameSource` to handle multiple simultaneous RTSP inputs. |

### 3.4 — Deployment packaging

Kheiven — deployment packaging research and the AI compression research doc are both in scope here. The packaging question came from Riley in the Apr 1 meeting; Cody asked the team to follow up with the sponsor on COTS hardware compatibility.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research AI-based compression alternative; benchmark vs MOG2 approach | KD | 2026-04-09 | Medium | Done | `docs/ai_compression_research.md`; YOLO detection overhead vs MOG2; NDAA note on neural codecs; MOG2 recommended |
| Research deployment packaging for government COTS deployment | KD | 2026-04-20 | Important | Not Started | Options: Docker, PyInstaller, OS package, source tarball. Must run on COTS x86. Check NDAA compliance for each. |

### 3.5 — Live demo preparation

Kheiven — the goal is a working demo on a laptop with no GPU. Cody confirmed government hardware is low-spec. `demo.sh` is done. The open tasks are confirming the webcam input path and the no-GPU test.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Create `demo.sh` — one-click pipeline launch with sensible defaults | KD | 2026-04-09 | Medium | Done | Launches `run_gui.py` with default port 5000; works headless or with browser auto-open |
| Confirm pipeline runs on USB or IP camera input in real time | KD | 2026-04-14 | Urgent | Not Started | Test with `--input 0` (webcam) on target hardware; verify no frame drops. |
| Test demo on laptop with no GPU (simulate target hardware) | KD | 2026-04-17 | Urgent | Not Started | Set `CUDA_VISIBLE_DEVICES=""` or use a CPU-only machine. Enhancer falls back to bicubic automatically. |

### 3.6 — Final report and results

Kheiven — `docs/final_report.md` exists and the abstract has real benchmark numbers (16.6x compression, PSNR 41.2 dB, SSIM 0.9783 on CDnet footage). The open task is the reproducible notebook.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Create `docs/final_report.md` — architecture, results, limitations | KD | 2026-04-18 | Urgent | Done | File exists; 13 sections including mode descriptions, benchmark results, encryption design |
| Populate final numbers table: compression ratio, PSNR, SSIM, storage/day/camera | KD | 2026-04-19 | Urgent | Done | Numbers in report abstract: 16.6x compression, PSNR 41.2 dB, SSIM 0.9783 |
| Create `notebooks/final_results.ipynb` — re-run all benchmarks from scratch | KD | 2026-04-20 | Important | Not Started | Must run end-to-end without errors on the final codebase. |
| Include side-by-side figure: original vs Mode 0 vs Mode 1 compressed frame | KD | 2026-04-21 | Medium | Not Started | Add to `final_report.md` and `final_results.ipynb`. |

### 3.7 — Repository polish and documentation

Kheiven — this is the final cleanup pass before tagging v1.0.0. The goal is that a new team member can clone the repo, run `pip install -r requirements.txt`, and have the pipeline running in under 15 minutes using only README.md and DEV.md.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Add docstrings to all public modules | KD | 2026-04-22 | Medium | Not Started | Check: `pipeline.py`, `roi_encoder.py`, `db.py`, `frame_source.py`, `metrics.py`, `enhancer.py` |
| Update README.md — final architecture and all four modes | KD | 2026-04-23 | Important | Not Started | Include: quick-start, mode descriptions, install steps. |
| Update DEV.md with any new setup steps | KD | 2026-04-24 | Medium | Not Started | Include: Real-ESRGAN model download, ffmpeg-python install, CDnet setup, encryption deps. |
| Cross-check `requirements.txt` via `pip freeze` | KD | 2026-04-25 | Medium | Not Started | `pip freeze > requirements_check.txt` and diff. |
| Tag final commit as `v1.0.0` | KD | 2026-04-26 | Important | Not Started | `git tag v1.0.0 && git push origin v1.0.0` |
| Verify repo clones cleanly on a fresh machine | KD | 2026-04-27 | Urgent | Not Started | New team member should be up and running in under 15 minutes. |

### 3.8 — Capstone presentation

All team members — deadline is May 1 for submission, May 6 for the presentation.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Create slide deck: problem, approach, 4-mode system, results, demo footage | All | 2026-04-28 | Urgent | Not Started | Sections: Cody's storage challenge, our approach, benchmark numbers, live demo clip |
| Prepare 2-minute live demo segment | KD, RR | 2026-04-29 | Urgent | Not Started | Show: camera feed, foreground mask, Mode 0/1 output, storage stats, metadata query |
| Rehearse full presentation as a team | All | 2026-04-30 | Important | Not Started | All team members present. |
| Submit final deliverable to course portal | All | 2026-05-01 | Urgent | Not Started | Hard deadline: May 6, 2026. |

---

## Milestone 4 — Sponsor meeting (Apr 15) — new requirements
**Added:** Apr 18, 2026 · **Due:** May 6, 2026
**Source:** NIWC/DIU weekly sync — Cody Hayashi, Geena Wann-Kung, and Sean (new NIWC contact)

These tasks come directly from the Apr 15 meeting. Assign owners this week — same hard deadline as M3.

### 4.1 — HLS live streaming integration

Cody recommended HLS (HTTP Live Streaming) as the browser delivery protocol, with hls.js (https://github.com/video-dev/hls.js/) for playback — MIT-licensed and fully open source. For camera-to-server transport, RTSP is the right choice because most cameras already speak it. The recommended architecture: camera sends RTSP → pipeline server → FFmpeg transcodes to HLS → hls.js plays in browser. Cody also mentioned the Hawaii state traffic cams at gookami.org as a free RTSP test source.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research HLS pipeline: FFmpeg outputs .m3u8 + .ts chunks, Flask serves them | KD | 2026-04-25 | Urgent | Done | Implemented in `src/gui/app.py` — 5 routes: `/api/hls/start`, `/api/hls/stop`, `/api/hls/status`, `/api/hls/<cam>/playlist.m3u8`, `/api/hls/<cam>/<seg.ts>`. |
| Integrate hls.js into index.html for browser-based HLS playback | KD | 2026-04-25 | Urgent | Done | CDN: `https://cdn.jsdelivr.net/npm/hls.js@latest`. `Hls.isSupported()` check with native HLS fallback for Safari. Inline player with 4s startup wait. |
| Add RTSP URL input to GUI + validate with `ffprobe` before starting pipeline | KD | 2026-04-26 | Important | Done | RTSP URL / webcam index / file path input in "Live Stream" sidebar section. Camera ID field, start/stop buttons, status message, inline `<video>` player. |
| Flask HLS segment server: generate + serve playlist and .ts chunks as pipeline runs | KD | 2026-04-26 | Important | Done | FFmpeg: `-preset ultrafast -tune zerolatency -hls_time 2 -hls_list_size 5 -hls_flags delete_segments+append_list`. Serves at `/api/hls/<cam>/`. |
| Test HLS end-to-end: RTSP in → pipeline → HLS out → hls.js in browser | KD, RR | 2026-04-28 | Important | Not Started | Test with webcam (index 0) or VLC RTSP server. Hawaii traffic cams (gookami.org) are a free RTSP target. Target latency under 5 seconds. |
| Export working stream config as JSON (codec, CRF, resolution, mode) | KD | 2026-04-29 | Medium | Not Started | Cody asked for a "save config" button that exports known-working stream parameters so they can be reproduced on DoD hardware without guessing. |

### 4.2 — AV1 codec support (royalty-free)

AV1 is from the Alliance for Open Media (Apple, Google, Microsoft, Netflix, Amazon) and is 100% royalty-free. FFmpeg supports it via `libaom-av1` (reference encoder, very slow) and `libsvtav1` (SVT-AV1, much faster). Use SVT-AV1 for anything real-time. The tradeoff: AV1 encoding is roughly 3–5× slower than H.264 on CPU, so it suits post-offload enhancement more than live recording. Still a strong talking point with the sponsor — zero licensing cost for government deployment.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Check AV1 encoder availability in deployed FFmpeg builds | JS | 2026-04-22 | Important | Not Started | Run: `ffmpeg -encoders \| grep av1`. Check for `libaom-av1` and `libsvtav1`. Document in DEV.md. |
| Add `codec` parameter to `ROIEncoder.encode_segment()` — support `libx264` and `libsvtav1` | JS | 2026-04-23 | Important | Not Started | Default stays `libx264`. AV1 CRF scale differs: ~35 foreground, ~55 background (equivalent quality to H.264 CRF 18/45). |
| Add codec selector dropdown to GUI (H.264 / AV1) | KD | 2026-04-24 | Medium | Not Started | AV1 option disabled if encoder not detected at startup. Show warning: "AV1 is ~3× slower to encode on CPU." |
| Benchmark AV1 vs H.264 encode time and output file size on CPU hardware | JS | 2026-04-25 | Important | Not Started | Same test clip, both codecs. Report: encode time (sec), output size (MB), PSNR. Document in `docs/av1_benchmark.md`. |
| Add AV1 section to `docs/final_report.md` | KD | 2026-04-26 | Medium | Not Started | Highlight for sponsor: AV1 = zero licensing cost. Note real-time encoding trade-off vs H.264. |

### 4.3 — Rich metadata: color detection + robust object classification

Geena asked about searching by vehicle color ("do you think we could try by color?"). Cody built on that: take the center 50% of each bounding box, build a color histogram in HSV space, find the dominant hue, and store it as a label. This is low-effort relative to the value — you already have the bounding boxes and the frame. The current `classify_object()` function uses only `roi_count` to guess vehicle vs person, which is not reliable. This task replaces it with a contour-based classifier using aspect ratio and area.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Implement `detect_dominant_color(frame, bbox)` — HSV histogram on center 50% of ROI | AM | 2026-04-23 | Important | Not Started | `cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)`. Build H histogram. Map peak hue to label: red, orange, yellow, green, blue, purple, white, black, gray. |
| Add `dominant_color` column to `segments` DB schema | AM | 2026-04-23 | Important | Not Started | ALTER TABLE migration in `initialize_database()`. One color label per segment (majority color across all ROIs). |
| Replace `classify_object()` heuristic with contour-based size classifier | AM | 2026-04-23 | Important | Not Started | Current: `roi_count > 10 → vehicle`. Replace with: bbox aspect ratio + area. Tall+narrow = person. Wide+long = vehicle. Large = truck/bus. |
| Add `object_confidence` column to DB (float 0.0–1.0) | AM | 2026-04-24 | Medium | Not Started | Low-confidence segments tagged `unknown`. Filter by confidence threshold in query UI. |
| Add `?color=blue` filter to `/api/query_segments` | AM | 2026-04-24 | Important | Not Started | `query_by_type()` extended to accept optional `color` param. SQL: `WHERE dominant_color = ?` |
| Add color search dropdown to Query Archive sidebar in GUI | KD | 2026-04-25 | Important | Not Started | Options: All / Red / Blue / Green / White / Black / Gray / Yellow / Orange. Wire to `/api/query_segments?color=`. |
| Unit tests for color detection and updated classifier | AM | 2026-04-25 | Important | Not Started | Tests: known-color synthetic ROIs, edge cases — very dark, overexposed, gray background. |

### 4.4 — Adaptive mode switching

Riley proposed a context switch between modes based on traffic density and time of day — Mode 0 when traffic is constant (background can't refresh), Mode 2 when the scene is sparse. Cody and Geena approved. Cody also asked specifically about background refresh interval for Mode 2: "is there value in updating the background once every half hour?" The answer is yes — the `bg_refresh_interval` parameter handles forced refreshes.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Implement `AdaptiveModeController` — switch modes based on traffic density | KD | 2026-04-26 | Important | Not Started | Configurable thresholds: `activity_rate` (ROIs/sec) and `background_staleness` (seconds since last clean frame). High activity → Mode 0. Low activity → Mode 1 or 2. |
| Background staleness tracking for Mode 2 — refresh keyframe if >N seconds | KD | 2026-04-26 | Important | Not Started | `bg_refresh_interval` param (default 1800s). Capture new keyframe when the scene is empty long enough to refresh. |
| Expose adaptive mode toggle and thresholds in GUI | KD | 2026-04-27 | Medium | Not Started | Checkbox: "Auto mode switching". Sliders for activity threshold and background refresh interval. |
| Unit tests for `AdaptiveModeController` transitions | KD | 2026-04-27 | Medium | Not Started | Test: mode changes at threshold crossing; mode stays stable below threshold; correct fallback when background is stale. |

### 4.5 — uv package manager migration

Sean (NIWC) explicitly asked for this: migrate from `pip` to `uv` (from Astral, https://astral.sh/uv). uv manages virtualenvs, locks the Python version, and avoids system package conflicts. DoD security teams prefer it because it eliminates dependency drift between machines.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Migrate to `uv` — create `pyproject.toml` and `uv.lock` | KD | 2026-04-22 | Urgent | Done | `pyproject.toml` created with all deps; `basicsr`/`realesrgan` moved to optional `[enhance]` extra. Run `uv lock` on a real machine to generate `uv.lock`. |
| Update README.md install instructions — `uv sync` as primary method | KD | 2026-04-23 | Important | Done | Primary: `uv sync`. Secondary: `pip install -r requirements.txt`. Note FFmpeg still needs system install. |
| Update DEV.md with `uv` setup steps | KD | 2026-04-23 | Medium | Done | Option A (uv) and Option B (pip) both documented. `uv run pytest` added to test section. Enhancement install updated to `uv sync --extra enhance`. |
| Verify `uv` install works on Windows, macOS, and Linux | KD | 2026-04-24 | Important | Not Started | Test on at least two platforms. Document any platform-specific issues (Windows path separators, FFmpeg detection). |

### 4.6 — CPU compute benchmarks per mode

Geena: "Knowing how much power is consumed is helpful — we want to bring this out in the field." Cody: "How much compute does each mode take, and how long on a typical laptop?" This is a required deliverable for field deployment planning — without numbers, the sponsor can't decide whether to run this on a Raspberry Pi, an old x86 box, or something else.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Benchmark CPU usage and encode time per mode (0, 1, 2, 3) on a standard laptop | JS | 2026-04-26 | Important | Not Started | Use `psutil` for CPU%. Same 60-sec test clip for all modes. Report: avg CPU%, peak CPU%, encode time, output file size, storage/hr. |
| Add per-mode compute table to `docs/stress_test_results.md` | JS | 2026-04-27 | Important | Not Started | Table: Mode → avg CPU% → encode time → storage/hr → estimated battery drain. |
| Estimate field battery life per mode (3-hour laptop battery as baseline) | JS | 2026-04-27 | Medium | Not Started | Formula: `battery_hours = 3h × (idle_CPU% / mode_CPU%)`. |

### 4.7 — Electron desktop app (stretch goal)

Cody: "Web app is number one, but if you can also bundle as Electron, that's great for field testing with no network." Geena agreed it's useful for bandwidth-constrained DoD environments. Cody was clear: "If it takes a day or days, skip it." Do this only if packaging is straightforward. No React — use vanilla HTML/JS (already compliant with DoD network restrictions).

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Research Electron packaging for Flask+Python app | KD | 2026-04-24 | Medium | Not Started | Option A: Electron shell that launches Flask subprocess, opens `localhost:5000`. Option B: PyInstaller bundle + Electron wrapper. Estimate time cost first. |
| Package app as Electron desktop app (if feasible) | KD | 2026-04-27 | Medium | Not Started | Only do this if research shows it takes under one day. No React — vanilla HTML/JS already compliant. |

### 4.8 — Compression method literature review

Cody asked: "Are there research papers for lossy compression that selectively drops data like ours?" Riley pointed out it's not apples-to-apples — traditional compression encodes everything, ours selectively discards. Cody said a literature review finding similar approaches would be valuable, especially if there's prior work on ROI-based or event-driven compression for surveillance.

| Task | Assigned To | Due | Priority | Status | Notes |
|---|---|---|---|---|---|
| Search for papers on background-subtraction-based selective video compression | KD | 2026-04-24 | Medium | Not Started | Search: IEEE Xplore, arXiv. Terms: "selective video compression", "ROI-based video compression surveillance", "event-driven video encoding static camera". |
| Write `docs/compression_comparison.md` — 1-page comparison summary | KD | 2026-04-26 | Medium | Not Started | Compare our approach to: naive H.264, HEVC, motion-JPEG, and any similar selective systems found. Note intentional asymmetry — we trade data for storage. |

---

## Team assignments

### Kheiven D'Haiti (KD) — kdhaiti2024@fau.edu

| Section | Area | Status |
|---|---|---|
| 1.1 | Background subtraction tuning | Done ✅ |
| 1.3 | CDnet foreground coverage benchmark | Done ✅ |
| 2.1 | Super-resolution enhancement module | Done ✅ |
| 2.4 | Data integrity validation | Done ✅ |
| 2.4 | CI integration for test_data_integrity.py | Open 🔲 |
| 2.6 | GUI dashboard — Flask app, SSE, all API endpoints | Done ✅ |
| 2.6 | GUI regression tests + API integration tests | Done ✅ |
| 3.1 | AES-256 encryption — initial CBC implementation | Done ✅ |
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
| 4.2 | AV1 codec GUI selector | Open 🔲 |
| 4.3 | Color search dropdown in GUI | Open 🔲 |
| 4.4 | Adaptive mode switching + GUI controls | Open 🔲 |
| 4.5 | uv migration + README/DEV.md updates | Done ✅ |
| 4.7 | Electron desktop app (if feasible) | Open 🔲 |
| 4.8 | Compression literature review | Open 🔲 |

### Riley Roberts (RR) — robertsr2022@fau.edu

| Section | Area | Status |
|---|---|---|
| 2.2 | ModeDecision dispatch + mode1 gating (modes.py) | Done ✅ |
| 2.2 | Mode 2 implementation | Open 🔲 |
| 2.2 | Mode 3 implementation | Open 🔲 |
| 2.6 | DemoMetadataWriter + renderer + split-screen | Done ✅ |
| 2.6 | Extend `test_pipeline.py` (enhance / encrypt / stop) | Open 🔲 |
| 2.6 | `run_demo.py` end-to-end on real footage | Open 🔲 |
| 4.1 | HLS end-to-end test | Open 🔲 |

### Victor Teixeira (VT) — vdesouzateix2023@fau.edu

| Section | Area | Status |
|---|---|---|
| 1.3 | PSNR, SSIM, compression ratio metrics | Done ✅ |
| 1.3 | `milestone1_benchmark.ipynb` | Done ✅ |
| 3.1 | Upgrade AES-256-CBC to AES-256-GCM | Open 🔲 |
| 3.1 | IV + salt storage in DB per segment | Open 🔲 |
| 3.1 | Password-protected incident clip export | Open 🔲 |
| 3.1 | Encrypt/decrypt round-trip unit tests | Open 🔲 |

### Ashleyn Montano (AM) — amontano2023@fau.edu

| Section | Area | Status |
|---|---|---|
| 1.4 | SQLite schema, WAL mode, `idx_cam_time` index | Done ✅ |
| 1.4 | `insert_segment()` + camera / time queries | Done ✅ |
| 1.4 | Unit tests: database (20 tests) | Done ✅ |
| 2.3 | Add `object_type` field + extend `insert_segment()` | Done ✅ |
| 2.3 | `query_by_type()` + daily storage summary + busiest CLI | Done ✅ |
| 2.3 | Unit tests for new queries and CLI tool | Done ✅ |
| 2.7 | Detection tuning — calibration research (w/ JS) | Done ✅ |
| 3.2 | Stable query API + full-text search + README docs | Open 🔲 |
| 4.3 | Color detection + DB column + updated object classifier | Open 🔲 |

### Jorge Sanchez (JS) — jorgesanchez2022@fau.edu

| Section | Area | Status |
|---|---|---|
| 1.2 | ROI encoding — FFmpeg stdin pipe, dual-CRF | Done ✅ |
| 1.2 | Integration tests for ROI encoder (18 tests) | Done ✅ |
| 2.5 | Algorithm comparison notebook + recommendation doc | Done ✅ |
| 2.5 | Stress test + memory bounds + storage extrapolation | Done ✅ |
| 2.7 | Detection tuning — calibration research (w/ AM) | Done ✅ |
| 3.3 | Watchfolder daemon / external footage ingestion | Open 🔲 |
| 4.2 | AV1 encoder check + `ROIEncoder` codec param | Open 🔲 |
| 4.2 | AV1 vs H.264 benchmark | Open 🔲 |
| 4.6 | CPU compute benchmarks per mode | Open 🔲 |

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
| Milestone 2 | Enhancement + stress test + algorithm comparison + GUI demo | Apr 18, 2026 | ✅ Complete |
| Milestone 3 | Final demo + report + repo polish + capstone | May 6, 2026 | 🔄 In progress |
| Milestone 4 | HLS streaming, AV1, color metadata, uv, benchmarks | May 6, 2026 | 🔄 In progress |

---

## Priority key

| Priority | Meaning |
|---|---|
| **Urgent** | Blocks demo, grading, or sponsor deliverable — do first |
| **Important** | Required for milestone completion, not immediately blocking |
| **Medium** | Quality improvement or nice-to-have — do after all Important tasks are done |

# Project Roadmap
## Open Source Selective Video Compression for Static Surveillance Cameras
**EGN 4950C Capstone | Florida Atlantic University | Spring 2026**
**Sponsor:** Defense Innovation Unit (DIU) — POC: Cody Hayashi (NIWC Pacific)
**Team:** Kheiven D'Haiti · Jorge Sanchez · Ashleyn Montano · Riley Roberts · Victor De Souza Teixeira
**Final Deadline:** May 6, 2026

---

## Initials Reference

| Initials | Name |
|---|---|
| KD | Kheiven D'Haiti |
| JS | Jorge Sanchez |
| AM | Ashleyn Montano |
| RR | Riley Roberts |
| VT | Victor De Souza Teixeira |

---

## Team Assignments at a Glance

> Detailed task breakdowns are in the milestone sections below.
> The Planner (Teams) tracks status per milestone section — use the section numbers (e.g., **2.1**, **3.1**) when referencing work.

### Kheiven D'Haiti (KD)
| Milestone | Section | Area | Status |
|---|---|---|---|
| M1 | 1.1 | Background Subtraction Tuning | ✅ Done |
| M1 | 1.3 | Metrics — foreground coverage benchmark | ✅ Done |
| M2 | 2.1 | Compression Mode System — `--mode` CLI arg | ✅ Done |
| M2 | 2.2 | Super-Resolution Enhancement Module | ✅ Done |
| M2 | 2.4 | Data Integrity Validation | ✅ Done |
| M2 | 2.6 | GUI Dashboard and Operator Controls | ✅ Done (SSE + endpoints) |
| M2 | 2.6 | GUI Regression Tests + API Integration Tests | 🔲 In Progress |
| M3 | 3.1 | AES-256 Encryption — initial implementation | ✅ Done |
| M3 | 3.5 | Live Demo — `demo.sh` | ✅ Done |
| M3 | 3.6 | Final Report | 🔲 Pending |
| M3 | 3.7 | Repository Polish and Documentation | 🔲 Pending |
| M3 | 3.8 | Capstone Presentation | 🔲 Pending (team) |

---

### Riley Roberts (RR)
| Milestone | Section | Area | Status |
|---|---|---|---|
| M2 | 2.1 | Compression Mode System — Mode 2 & Mode 3 impl | 🔲 Assigned |
| M2 | 2.1 | Mode dispatch unit tests (mode2, mode3, mode1 gating) | 🔲 Assigned |
| M2 | 2.1 | Demo/concat mode — stitch output segments | 🔲 Assigned |
| M2 | 2.1 | ModeDecision dataclass + dispatch (`modes.py`) | ✅ Done |
| M2 | 2.1 | `test_pipeline.py` — mode1 + EOF boundary tests | ✅ Done |
| M2 | 2.1 | Extend `test_pipeline.py` — enhance, encrypt, stop_event | 🔲 Assigned |
| M2 | 2.5 | Algorithm comparison notebook (MOG2 vs KNN) | 🔲 Assigned |
| M2 | 2.5 | Stress test (`test_pipeline_stress.py`) | 🔲 Assigned |
| M2 | 2.6 | `DemoMetadataWriter`, demo renderer, split-screen compositor | ✅ Done |
| M2 | 2.6 | `run_demo.py` end-to-end test on real footage | 🔲 Assigned |
| M3 | 3.5 | Live demo — confirm webcam/IP camera input works | 🔲 Assigned |
| M3 | 3.6 | Final benchmarks notebook (`final_results.ipynb`) | 🔲 Assigned |

**Riley's Focus (from team chat, April 8):** Mode 2 and Mode 3 implementation. Compile metrics and benchmarks the sponsor asked about (multiple video types, lighting conditions). Research and document detection tuning recommendations for Ashleyn and Jorge to execute.

---

### Victor De Souza Teixeira (VT)
| Milestone | Section | Area | Status |
|---|---|---|---|
| M1 | 1.3 | Metrics — PSNR, SSIM, compression ratio | ✅ Done |
| M1 | 1.3 | `milestone1_benchmark.ipynb` | ✅ Done |
| M2 | 2.4 | Data integrity CI integration (`tests/test_data_integrity.py`) | 🔲 Assigned |
| M3 | 3.1 | AES-256 Encryption — upgrade CBC → GCM (auth tag) | 🔲 Assigned |
| M3 | 3.1 | Store IV + salt in DB alongside segment record | 🔲 Assigned |
| M3 | 3.1 | Password-protected export for incident clips | 🔲 Assigned |
| M3 | 3.1 | Unit tests: encrypt/decrypt round-trip, IV uniqueness per segment | 🔲 Assigned |
| M3 | 3.4 | Deployment packaging research (Docker/PyInstaller/tarball) | 🔲 Assigned |

**Victor's Focus (Sponsor meeting + team chat):** Cybersecurity. Cody flagged AES-256 encryption as a requirement given Victor's security background. Current implementation uses AES-256-CBC — audit finding: CBC has no authentication tag and is vulnerable to padding oracle attacks. Victor owns the upgrade to AES-256-GCM, IV/salt persistence in the database, and the secure export workflow. Also owns deployment packaging research per sponsor requirement (Cody to follow up with Gina on approved format).

---

### Ashleyn Montano (AM)
| Milestone | Section | Area | Status |
|---|---|---|---|
| M1 | 1.4 | Metadata Database — SQLite schema, WAL, indexes | ✅ Done |
| M1 | 1.4 | `insert_segment()`, camera/time query | ✅ Done |
| M1 | 1.4 | Unit tests: schema, insertion, queries (20 tests) | ✅ Done |
| M2 | 2.3 | Metadata DB — add `object_type` field | 🔲 Assigned |
| M2 | 2.3 | Extend `insert_segment()` — tie `object_type` into detection | 🔲 Assigned |
| M2 | 2.3 | Queries: most targets, daily storage summary, `query_by_type()` | 🔲 Assigned |
| M2 | 2.3 | CLI query tool: `db_query.py --camera --last-hours --type` | 🔲 Assigned |
| M2 | 2.3 | Unit tests for `object_type`, new queries, CLI | 🔲 Assigned |
| M2 | 2.7 | Detection Tuning — research + calibrate MOG2/KNN on test footage | 🔲 Assigned |
| M3 | 3.2 | Searchable Metadata Index — `query_by_type()` as stable API | 🔲 Assigned |
| M3 | 3.2 | Full-text / tag-based search across metadata index | 🔲 Assigned |
| M3 | 3.2 | Document query interface in `README.md` | 🔲 Assigned |

**Ashleyn's Focus (from team chat, April 8):** Metadata database is her domain from M1. Extends that into M2 with `object_type` classification and query tools the sponsor explicitly asked for (searchable index, no manual video scrubbing). Also assigned detection tuning alongside Jorge — understanding when the background subtractor produces false positives/negatives and how to tune MOG2 parameters for the real base-camera footage types (entry points, walkways, varying lighting).

---

### Jorge Sanchez (JS)
| Milestone | Section | Area | Status |
|---|---|---|---|
| M1 | 1.2 | ROI Encoding Pipeline — FFmpeg, dual-CRF | ✅ Done |
| M1 | 1.2 | Integration tests for encoding | ✅ Done |
| M2 | 2.5 | Memory bounds stress test (1-hour simulated footage) | 🔲 Assigned |
| M2 | 2.5 | Storage extrapolation — 60-day / 100-camera estimate | 🔲 Assigned |
| M2 | 2.5 | `docs/stress_test_results.md` | 🔲 Assigned |
| M2 | 2.5 | `docs/algorithm_comparison.md` production recommendation | 🔲 Assigned |
| M2 | 2.7 | Detection Tuning — research + calibrate, compile recommendations | 🔲 Assigned |
| M3 | 3.3 | External footage ingestion / watchfolder daemon | 🔲 Assigned |
| M3 | 3.3 | Body camera / external system input support | 🔲 Assigned |

**Jorge's Focus (from team chat, April 8):** Benchmarking and stress testing. His M1 encoding work gives him the best context for measuring throughput and storage math. Also assigned detection tuning alongside Ashleyn — the sponsor's baseline was a YOLO walkway camera that got ~6x reduction; we need to understand how well our MOG2 setup compares and how to tune it for base-entry footage. Jorge also owns the external ingestion path (watchfolder) which connects to the sponsor use case of body cameras and other surveillance feeds being dropped into the system.

---

## Project Goals (Big Picture)

The end deliverable is a working, open-source software pipeline that:

1. **Ingests** a static camera feed (USB, IP camera, or pre-recorded test video)
2. **Separates** foreground objects (people, vehicles) from the static background using background subtraction
3. **Encodes** footage using one of four compression modes, trading off storage density against forensic quality
4. **Indexes** every video segment in a SQLite metadata database for fast retrieval by object type, camera, and time
5. **Stores** compressed footage locally (target: 60-day retention on 100+ camera systems)
6. **Encrypts** output files with AES-256 for secure storage and transmission
7. **Enhances** compressed footage post-offload using CPU-based super-resolution
8. **Demonstrates** measurable storage savings (target: 6x vs. naive full-frame H.264)

All components must be open source, royalty-free, and run on CPU-only hardware. No Chinese-origin software (NDAA compliance). No GPU required.

---

## Compression Mode Overview

| Mode | Name | What It Stores | Best For |
|---|---|---|---|
| Mode 0 | 24/7 Continuous | All frames at dual-CRF (FG: CRF 18, BG: CRF 45) | Baseline surveillance, no gaps |
| Mode 1 | Frame Gating | Only frames with detected foreground activity | Mostly-static scenes, max storage savings |
| Mode 2 | Background Keyframe + Patches | One BG keyframe per event + per-frame object-bbox crops | Low-traffic scenes, efficient forensic review |
| Mode 3 | Object-Only Forensic | Padded bbox crop only, no background | Facial recognition pipeline, maximum data density |

---

## Phase 0  —  Project Setup
**Target: Week of January 13, 2026 → COMPLETED**

- [x] Repository scaffolded with directory structure
- [x] `requirements.txt` populated with all Python dependencies
- [x] `.gitignore` configured for Python, video files, model weights, and outputs
- [x] `BackgroundSubtractor` class implemented (MOG2 / KNN / GMG)
- [x] `ROIEncoder` class skeleton implemented with FFmpeg integration
- [x] `Pipeline` orchestrator skeleton implemented
- [x] `metrics.py` utility (PSNR, SSIM, compression ratio) implemented
- [x] Unit test file scaffolded for background subtraction
- [x] Initial GitHub commit pushed to `main`

---

## Milestone 1  —  Core Pipeline Functional
**Target Completion: March 31, 2026 → COMPLETED ✅**
**Branch:** `dev` → merged to `main` at tag `v0.1.0`

### 1.1  —  Background Subtraction Tuning  *(Owner: KD)*

- [x] Tune MOG2 parameters (`history`, `varThreshold`, `detectShadows`) on sample footage  — KD
- [x] Tune KNN parameters on the same footage and compare mask quality  — KD
- [x] Implement morphological cleanup (erosion/dilation) to remove noise from foreground mask  — KD
- [x] Add minimum contour area filter to discard trivially small detections  — KD
- [x] Write unit tests: mask generation, edge cases, night mode  — KD

---

### 1.2  —  ROI Encoding Pipeline  *(Owner: JS)*

- [x] Complete `ROIEncoder.encode_segment()` — pipe numpy frames to FFmpeg via stdin  — JS
- [x] Implement dual-CRF encoding: foreground CRF 18, background CRF 45  — JS
- [x] Validate output is a valid playable MP4  — JS
- [x] Implement `ROIEncoder.get_file_size()` and log pre/post compression sizes  — JS
- [x] Integration tests: encode 10-second clip, verify output and compression ratio  — JS

---

### 1.3  —  Metrics and Benchmarking  *(Owner: VT; foreground coverage benchmark: KD)*

- [x] Implement `compute_psnr()` and `compute_ssim()` in `src/utils/metrics.py`  — VT
- [x] Implement `compute_compression_ratio()`  — VT
- [x] Create foreground coverage benchmark across all 46 CDnet categories  — KD
- [x] Create `notebooks/milestone1_benchmark.ipynb`  — VT
- [x] Document results in `docs/milestone1_results.md`  — VT

---

### 1.4  —  Metadata Database  *(Owner: AM)*

- [x] Create `src/utils/db.py` with SQLite schema (WAL mode, `idx_cam_time` index)  — AM
- [x] Integrate database writes into the pipeline (one row per encoded segment)  — AM
- [x] Implement query: segments from camera X with targets in last N hours  — AM
- [x] Unit tests: schema creation, insertion, query (20 tests)  — AM

---

## Milestone 2  —  Compression Modes + Enhancement + Stress Testing
**Target Completion: April 18, 2026**
**Branch:** `feature/*` → `dev` → merge to `main` when all M2 tests pass

### 2.1  —  Compression Mode System  *(Owner: RR)*

**Feature Branch:** `feature/compression-modes`

- [x] Add `--mode` argument to `pipeline.py` CLI (mode0 / mode1 / mode2 / mode3)  — KD
- [x] `ModeDecision` dataclass + `get_mode_decision()` dispatch in `src/pipeline/modes.py`  — RR
- [x] Mode 1 frame gating — buffer only active-frame events  — RR
- [x] Unit tests for mode1 frame gating (`test_pipeline.py`)  — RR
- [x] EOF boundary test — no extra partial encode when video ends on segment boundary  — RR
- [ ] Implement Mode 2: store one background keyframe + per-frame object-bbox patches  — RR
- [ ] Implement Mode 3: object-only forensic mode (padded bbox crop, no background)  — RR
- [ ] Write unit tests for Mode 2 output structure (keyframe + patches)  — RR
- [ ] Write unit tests for Mode 3 output (bbox crop, correct padding)  — RR
- [ ] Extend `test_pipeline.py` — add `--enhance`, `--encrypt`, `stop_event` coverage  — RR
- [ ] `run_demo.py` end-to-end test on a real test clip (all working modes)  — RR
- [ ] Demo/concat mode: stitch output segments into a single playback file  — RR

**Acceptance criteria:** All four modes produce valid output files. Mode 2 and Mode 3 show measurably higher compression ratios than Mode 0 on static-scene footage.

---

### 2.2  —  Super-Resolution Enhancement Module  *(Owner: KD)*

**Feature Branch:** `feature/enhancement-superresolution`

- [x] Research Real-ESRGAN CPU inference setup; document model download steps in `DEV.md`  — KD
- [x] Implement `Enhancer.upscale_frame(frame, scale)` with Real-ESRGAN + bicubic fallback  — KD
- [x] Implement `Enhancer.upscale_roi(frame, bbox)` — upscale only bounding region, paste back  — KD
- [x] Integrate enhancement into pipeline as optional post-offload pass (`--enhance` flag)  — KD
- [x] Bicubic built-in backend (`_BUILTIN_MODELS`) — always-available fallback, no weight files  — KD
- [x] Write unit tests for Enhancer: output dimensions, bbox validation, `is_available()`  — KD
- [x] Research AI-based compression alternative (NDAA-compliant YOLO variants, neural codecs); document tradeoffs vs current MOG2 pipeline  — KD
- [ ] Benchmark enhancement processing time per frame on CPU hardware (target: Raspberry Pi)  — *unassigned*

**Acceptance criteria:** `upscale_frame()` returns image at 2x or 4x target resolution. PSNR on enhanced output is measurably higher than non-enhanced compressed output. CPU benchmarks documented.

---

### 2.3  —  Metadata Database Extensions  *(Owner: AM)*

**Feature Branch:** `feature/metadata-database` (extend from M1)

- [ ] Add `object_type` field to DB schema (person, vehicle, cyclist, unknown)  — AM
- [ ] Extend `insert_segment()` to accept `object_type`; tie into `BackgroundSubtractor` region detection  — AM
- [ ] Implement query: segments sorted by most targets detected  — AM
- [ ] Implement query: daily storage summary by camera  — AM
- [ ] Implement query: `query_by_type(object_type, camera_id, start_time, end_time)` — returns matching segment file paths  — AM
- [ ] Add CLI query tool: `python src/utils/db_query.py --camera cam_01 --last-hours 24 --type person`  — AM
- [ ] Unit tests for `object_type` field, new queries, and CLI tool  — AM

**Acceptance criteria:** CLI query returns correct results. `object_type` filter works across all four compression modes. No SQL injection vulnerabilities.

---

### 2.4  —  Data Integrity Validation  *(Owner: KD; CI integration: VT)*

**Feature Branch:** `feature/data-integrity`

- [x] Build automated frame-level comparison test: decode compressed output and compare subject ROI pixel data against original  — KD
- [x] Document pass/fail criteria (government is risk-intolerant; even 5% foreground data loss is unacceptable)  — KD
- [ ] Integrate integrity check into CI test suite (`tests/test_data_integrity.py`)  — VT

**Acceptance criteria:** Test passes on all four modes with zero foreground pixel data loss above threshold.

---

### 2.5  —  Algorithm Comparison and Pipeline Stress Test  *(Owner: JS)*

**Feature Branch:** `feature/benchmarking-milestone2`

- [ ] Create `notebooks/algorithm_comparison.ipynb` with side-by-side MOG2 vs. KNN visualizations  *(data already in `cdnet_batch_results.log`)*  — JS
- [ ] Write `docs/algorithm_comparison.md` — production recommendation with tradeoff analysis  *(recommendation: MOG2 as primary)*  — JS
- [ ] Write `tests/test_pipeline_stress.py` — 1 hour simulated footage (loop a test clip)  — JS
- [ ] Verify memory does not grow unbounded over 1 hour (`tracemalloc` or `psutil`)  — JS
- [ ] Extrapolate 1-hour results to estimate storage for 60-day retention on 100 cameras  — JS
- [ ] Document stress test findings in `docs/stress_test_results.md`  — JS

**Acceptance criteria:** Pipeline runs 1 hour without crash or runaway memory growth. Storage extrapolation documented. Algorithm comparison notebook renders correctly.

---

### 2.6  —  GUI Dashboard and Operator Controls  *(Owner: KD)*

**Feature Branch:** `feature/gui-dashboard`

- [x] Create Flask dashboard backend (`src/gui/app.py`) and package scaffold (`src/gui/__init__.py`)  — KD
- [x] Create launcher (`run_gui.py`) with host/port/no-browser options for local and LAN use  — KD
- [x] Add API endpoints for start/stop/status/segments/storage/log stream (`/api/*`)  — KD
- [x] Add SSE live log streaming with monotonic event IDs — no duplicate lines on reconnect  — KD
- [x] Implement dashboard layout updates (stats panel, resizable panes, log/segments toggle)  — KD
- [x] Add one-click demo launcher (`demo.sh`) for repeatable demo startup  — KD
- [x] `DemoMetadataWriter` integration + `demo` parameter wired through GUI  — KD
- [ ] Add GUI regression tests for start/stop and status polling behavior  — KD
- [ ] Add API integration tests for `/api/start`, `/api/stop`, `/api/status`, `/api/segments`, `/api/storage`  — KD
- [ ] Add user guide section in `README.md` with dashboard screenshots and common troubleshooting  — KD

**Acceptance criteria:** Dashboard can start/stop pipeline, stream logs, and display live status/segment/storage data without terminal usage.

---

### 2.7  —  Detection Tuning and Calibration  *(Owner: AM + JS)*

**Feature Branch:** `feature/detection-tuning`

> New task area added April 9, 2026, based on team discussion. Sponsor baseline (YOLO walkway camera) achieved ~6x reduction. We need to understand and tune our MOG2/KNN setup to approach or exceed this on base-entry footage types.

- [ ] Research tuning parameters: MOG2 `history`, `varThreshold`, `detectShadows`; KNN `dist2Threshold`, `detectShadows`  — AM + JS
- [ ] Acquire or record test footage representative of base-entry scenes (vehicle gates, walkways, varying lighting)  — AM + JS
- [ ] Run both algorithms across lighting conditions; measure false positive / false negative rates  — AM + JS
- [ ] Document optimal parameter sets for daytime, night, and mixed-lighting conditions  — AM + JS
- [ ] Compile findings into `docs/detection_tuning.md` with recommended defaults  — AM + JS
- [ ] Update `BackgroundSubtractor` default parameters to match recommended values  — AM + JS
- [ ] Write unit tests validating detection accuracy on ground-truth clips  — AM + JS

**Acceptance criteria:** False positive rate on static scenes < 2%. Detection correctly triggers on a person walking through frame within 3 frames of entry. Recommended parameters documented.

---

### Milestone 2 Sign-Off Checklist

- [ ] `pytest tests/ -v` passes with zero failures  —  Verifier: ___
- [ ] All four compression modes produce valid output  —  Verifier: ___
- [ ] Enhancement module upscales a test image correctly  —  Verifier: ___
- [ ] Stress test completed without crash  —  Verifier: ___
- [ ] `object_type` DB field works end-to-end  —  Verifier: ___
- [ ] Detection tuning parameters updated in codebase  —  Verifier: ___
- [ ] PR reviewed by at least one other team member  —  Reviewer: ___

---

## Milestone 3  —  Final Demo + Deliverables
**Target Completion: May 6, 2026 (HARD DEADLINE)**
**Branch:** `feature/*` → `dev` → merge to `main` after final review and tag `v1.0.0`

### 3.1  —  AES-256 Encryption  *(Owner: KD initial impl; VT owns upgrade and DB integration)*

**Feature Branch:** `feature/encryption`

- [x] Implement AES-256-CBC encryption for compressed output video files (`--encrypt` flag)  — KD
- [x] PBKDF2-HMAC-SHA256 key derivation (600k iterations), fresh IV+salt per file  — KD
- [ ] **Upgrade AES-256-CBC → AES-256-GCM** (authentication tag; eliminates padding oracle vulnerability)  — VT
- [ ] Store IV and salt alongside segment record in DB (new `encryption_iv` + `encryption_salt` columns)  — VT
- [ ] Add password-protected export for incident clips (AES-GCM encrypted archive)  — VT
- [ ] Unit tests: encrypt/decrypt round-trip, IV uniqueness per segment, GCM tag verification  — VT

**Acceptance criteria:** Encrypted output cannot be played without decryption key. GCM authentication tag prevents silent tampering. Round-trip test passes. IV+salt stored in DB.

> **Note:** AES-256-GCM is the government-standard authenticated encryption mode. The current CBC implementation was flagged in the April 9 audit. Victor owns this upgrade.

---

### 3.2  —  Searchable Metadata Index  *(Owner: AM)*

**Feature Branch:** `feature/metadata-search` (extend from M2)

- [ ] Expose `query_by_type(object_type, camera_id, start_time, end_time)` as a stable API  — AM
- [ ] Add full-text or tag-based search across the metadata index  — AM
- [ ] Return ranked list of matching segment file paths sorted by target count  — AM
- [ ] Document query interface in `README.md`  — AM

**Acceptance criteria:** Sponsor can locate all segments containing "person" detections from a specific camera in a time range without manually scrubbing video.

---

### 3.3  —  External Footage Ingestion  *(Owner: JS)*

**Feature Branch:** `feature/drop-folder`

- [ ] Implement watchfolder daemon: auto-ingest new `.mp4` / `.avi` files dropped into a folder  — JS
- [ ] Support input from external sources (body cameras, other surveillance systems)  — JS
- [ ] Simple CLI or daemon that picks up new files and routes through pipeline automatically  — JS

**Acceptance criteria:** Dropping a video file into the watchfolder triggers automatic pipeline processing without manual CLI invocation.

---

### 3.4  —  Deployment Packaging  *(Owner: VT)*

**Feature Branch:** `feature/deployment`

- [ ] Research and document deployment packaging format for government COTS hardware (Docker, PyInstaller, OS package, or source tarball)  — VT
- [ ] Must be compatible with COTS x86 hardware (no GPU dependency)  — VT
- [ ] Document findings in `docs/deployment_guide.md`; decision to be confirmed with Cody (Gina follow-up)  — VT

**Acceptance criteria:** A non-developer government operator can install and run the pipeline using only the deployment package and the README.

---

### 3.5  —  Live Demo Preparation  *(Owner: KD + RR)*

**Feature Branch:** `feature/demo-prep`

- [ ] Confirm pipeline runs on USB or IP camera input in real time (`--input 0`)  — RR
- [ ] Verify `--preview` flag shows live foreground mask alongside original feed  — RR
- [x] Create `demo.sh` — one-click pipeline launch with sensible defaults, no args required  — KD
- [ ] Test demo on laptop with no GPU (simulate target hardware)  — RR
- [ ] Prepare 2-minute live demo segment: feed → mask → Mode 0 output → Mode 1 output → storage stats → metadata query  — KD + RR

**Acceptance criteria:** Demo runs on a stock CPU-only laptop. All four modes demonstrated. Compressed output produced within 30 seconds of launch.

---

### 3.6  —  Final Report and Quantitative Results  *(Owner: KD + RR)*

**Feature Branch:** `feature/final-report`

- [ ] Create `docs/final_report.md`: system architecture, mode descriptions, benchmark results, enhancement results, encryption design, limitations  — KD
- [ ] Populate final numbers table: compression ratio, PSNR, SSIM, storage per day per camera (Mode 0 vs. Mode 1 vs. Mode 2 vs. Mode 3)  — RR
- [ ] Create `notebooks/final_results.ipynb` — re-run all benchmarks from scratch on final codebase  — RR
- [ ] Include side-by-side figure: original vs. Mode 0 vs. Mode 1 compressed frame  — RR

**Acceptance criteria:** Report is complete, numbers are reproducible by running the notebook on a clean install.

---

### 3.7  —  Repository Polish and Documentation  *(Owner: KD)*

**Feature Branch:** `feature/docs-cleanup`

- [ ] Ensure all public-facing modules have docstrings (`pipeline.py`, `roi_encoder.py`, `db.py`, `frame_source.py`, `metrics.py`, `enhancer.py`)  — KD
- [ ] Update `README.md` to reflect final architecture, all four modes, and benchmark numbers  — KD
- [ ] Update `DEV.md` with setup steps for Real-ESRGAN model download, encryption deps, CDnet dataset  — KD
- [ ] Ensure `requirements.txt` is accurate (`pip freeze` cross-check)  — KD
- [ ] Tag final commit as `v1.0.0`  — KD
- [ ] Verify repo clones cleanly on a fresh machine and pipeline runs in under 15 minutes  — KD

**Acceptance criteria:** A new team member can clone, install, and run the pipeline in under 15 minutes using only `README.md` and `DEV.md`.

---

### 3.8  —  Capstone Presentation  *(Owner: All)*

- [ ] Create slide deck: problem statement, approach, four-mode system, benchmark results, demo footage  — All
- [ ] Prepare 2-minute live demo segment  — KD + RR
- [ ] Rehearse full presentation as a team  — All
- [ ] Submit final deliverable to course portal (hard deadline: May 6, 2026)  — All

---

### Milestone 3 Sign-Off Checklist

- [ ] `pytest tests/ -v` passes with zero failures on a clean install  —  Verifier: ___
- [ ] Final report is complete and numbers are reproducible  —  Verifier: ___
- [ ] AES-256-GCM round-trip test passes, IV stored in DB  —  Verifier: ___
- [ ] Live demo works on target hardware  —  Verifier: ___
- [ ] Repository tagged `v1.0.0`  —  Verifier: ___
- [ ] All team members have reviewed the final README  —  Reviewer: All

---

## Branch and PR Strategy

```
main          ← stable, always working, tagged at each milestone
  └── dev     ← integration branch (all features merge here first)
        ├── feature/compression-modes        (RR — Mode 2, Mode 3, concat, tests)
        ├── feature/enhancement-superresolution
        ├── feature/metadata-database        (AM — object_type, queries, CLI)
        ├── feature/metadata-search          (AM — stable API, full-text search)
        ├── feature/detection-tuning         (AM + JS — calibration, docs)
        ├── feature/data-integrity           (VT — CI integration)
        ├── feature/benchmarking-milestone2  (JS — stress test, algorithm comparison)
        ├── feature/encryption               (VT — GCM upgrade, DB integration)
        ├── feature/drop-folder              (JS — watchfolder daemon)
        ├── feature/deployment               (VT — packaging research)
        ├── feature/gui-dashboard            (KD — regression + API tests)
        ├── feature/demo-prep
        ├── feature/final-report
        └── feature/docs-cleanup
```

**Rules:**
- Never commit directly to `main`
- Always branch from `dev`, not from `main`
- Every PR into `dev` needs at least one reviewer approval
- `dev` is merged into `main` only at milestone completions
- Commit messages: `feat: add Mode 2 background keyframe encoder`, `fix: AES IV not persisted to DB`

---

## Timeline Summary

| Milestone | Description | Target Date |
|---|---|---|
| Phase 0 | Repo scaffold, initial code | ✅ Complete |
| **Milestone 1** | Core pipeline + metrics + database | ✅ March 31, 2026 |
| **Milestone 2** | Compression modes + enhancement + stress test + detection tuning | **April 18, 2026** |
| **Milestone 3** | Final demo + report + encryption upgrade + repo polish | **May 6, 2026** |

---

## Sponsor Requirements (from Meetings)

Logged here so all team members have context on constraints that informed scope decisions.

- **CPU-only, no GPU** — government hardware is low-spec COTS x86
- **NDAA compliance** — no Chinese-origin software (eliminates some YOLO variants)
- **60-day retention** — storage math must scale to 100+ cameras
- **Risk-intolerant on data loss** — even 5% foreground pixel loss is unacceptable (Cody's words)
- **AES-256 encryption** — required for footage stored and transmitted over network; GCM mode required for authenticated encryption
- **Searchable index** — eliminate manual video scrubbing; must query by object type, camera, and time range
- **Four compression modes** — different operational contexts need different storage/quality tradeoffs
- **Open source, royalty-free** — no commercial licensing (government acquisition rules)
- **Deployment packaging** — TBD; Cody to follow up with Gina on approved packaging format
- **Multiple lighting conditions** — sponsor wants benchmarking across video types (day, night, entry points)

---

## Stretch Goals (If Time Permits)

- GPU-accelerated encode path (NVENC) as an optional fast-path for non-government deployments
- RTSP stream support for IP cameras
- Automated model weight update pipeline for Real-ESRGAN
- YOLO-based object classifier to improve `object_type` accuracy beyond MOG2 contour heuristics

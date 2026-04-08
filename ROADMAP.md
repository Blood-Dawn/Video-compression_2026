# Project Roadmap
## Open Source Selective Video Compression for Static Surveillance Cameras
**EGN 4950C Capstone | Florida Atlantic University | Spring 2026**
**Sponsor:** Defense Innovation Unit (DIU) — POC: Cody Hayashi (NIWC Pacific)
**Team:** Kheiven D'Haiti · Jorge Sanchez · Ashleyn Montano · Riley Roberts · Victor De Souza Teixeira
**Final Deadline:** May 6, 2026

---

## How to Use This Roadmap

This roadmap lists every task that needs to be completed. **Task assignments are tracked in the team Planner (Microsoft Teams).** To claim a task in this document, add your initials next to it:

```
- [ ] Task description  —  KD
```

Initials: KD = Kheiven D'Haiti · JS = Jorge Sanchez · AM = Ashleyn Montano · RR = Riley Roberts · VT = Victor De Souza Teixeira

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

### 1.1  —  Background Subtraction Tuning

- [x] Tune MOG2 parameters (`history`, `varThreshold`, `detectShadows`) on sample footage  — KD
- [x] Tune KNN parameters on the same footage and compare mask quality  — KD
- [x] Implement morphological cleanup (erosion/dilation) to remove noise from foreground mask  — KD
- [x] Add minimum contour area filter to discard trivially small detections  — KD
- [x] Write unit tests: mask generation, edge cases, night mode  — KD

---

### 1.2  —  ROI Encoding Pipeline

- [x] Complete `ROIEncoder.encode_segment()` — pipe numpy frames to FFmpeg via stdin  — JS
- [x] Implement dual-CRF encoding: foreground CRF 18, background CRF 45  — JS
- [x] Validate output is a valid playable MP4  — JS
- [x] Implement `ROIEncoder.get_file_size()` and log pre/post compression sizes  — JS
- [x] Integration tests: encode 10-second clip, verify output and compression ratio  — JS

---

### 1.3  —  Metrics and Benchmarking

- [x] Implement `compute_psnr()` and `compute_ssim()` in `src/utils/metrics.py`  — VT
- [x] Implement `compute_compression_ratio()`  — VT
- [x] Create foreground coverage benchmark across all 46 CDnet categories  — KD
- [x] Create `notebooks/milestone1_benchmark.ipynb`  — VT
- [x] Document results in `docs/milestone1_results.md`  — VT

---

### 1.4  —  Metadata Database

- [x] Create `src/utils/db.py` with SQLite schema (WAL mode, `idx_cam_time` index)  — AM
- [x] Integrate database writes into the pipeline (one row per encoded segment)  — AM
- [x] Implement query: segments from camera X with targets in last N hours  — AM
- [x] Unit tests: schema creation, insertion, query (20 tests)  — AM

---

## Milestone 2  —  Compression Modes + Enhancement + Stress Testing
**Target Completion: April 18, 2026**
**Branch:** `feature/*` → `dev` → merge to `main` when all M2 tests pass

### 2.1  —  Compression Mode System

**Feature Branch:** `feature/compression-modes`

- [ ] Implement Mode 2: store one background keyframe + per-frame object-bbox patches
- [ ] Implement Mode 3: object-only forensic mode (padded bbox crop, no background)
- [x] Add `--mode` argument to pipeline.py CLI (mode0 / mode1 / mode2 / mode3)  *(mode0 and mode1 already done)*  — KD
- [ ] Add demo/concat mode: stitch output segments into a single playback file
- [ ] Write unit tests for Mode 2 output structure (keyframe + patches)
- [ ] Write unit tests for Mode 3 output (bbox crop, correct padding)
- [ ] Write unit tests for mode1 frame gating (active-only frames buffered)  *(see PR #4)*

**Acceptance criteria:** All four modes produce valid output files. Mode 2 and Mode 3 show measurably higher compression ratios than Mode 0 on static-scene footage.

---

### 2.2  —  Super-Resolution Enhancement Module

**Feature Branch:** `feature/enhancement-superresolution`

- [x] Research Real-ESRGAN CPU inference setup; document model download steps in `DEV.md`  — KD
- [x] Implement `Enhancer.upscale_frame(frame, scale)` using Real-ESRGAN in CPU mode  — KD
- [x] Implement `Enhancer.upscale_roi(frame, bbox)` — upscale only bounding region, paste back  — KD
- [x] Integrate enhancement into pipeline as optional post-offload pass (`--enhance` flag)  — KD
- [ ] Benchmark enhancement processing time per frame on CPU hardware (target: Raspberry Pi)
- [x] Write unit tests for Enhancer: output dimensions, bbox validation, `is_available()`  — KD
- [x] Research AI-based compression alternative (e.g. YOLOv8 detection, neural video codecs); document tradeoffs vs current MOG2 pipeline  — KD

**Acceptance criteria:** `upscale_frame()` returns image at 2x or 4x target resolution. PSNR on enhanced output is measurably higher than non-enhanced compressed output. CPU benchmarks documented.

---

### 2.3  —  Metadata Database Extensions

**Feature Branch:** `feature/metadata-database` (extend from M1)

- [ ] Add `object_type` field to DB schema (person, vehicle, cyclist, unknown)
- [ ] Extend `insert_segment()` to accept `object_type`; tie into `BackgroundSubtractor` region detection
- [ ] Implement query: segments sorted by most targets detected
- [ ] Implement query: daily storage summary by camera
- [ ] Implement query: `query_by_type(object_type, camera_id, start_time, end_time)` — returns matching segment file paths
- [ ] Add CLI query tool: `python src/utils/db_query.py --camera cam_01 --last-hours 24 --type person`
- [ ] Unit tests for `object_type` field, new queries, and CLI tool

**Acceptance criteria:** CLI query returns correct results. `object_type` filter works across all four compression modes. No SQL injection vulnerabilities.

---

### 2.4  —  Data Integrity Validation

**Feature Branch:** `feature/data-integrity`

- [x] Build automated frame-level comparison test: decode compressed output and compare subject ROI pixel data against original  — KD
- [x] Document pass/fail criteria (government is risk-intolerant; even 5% foreground data loss is unacceptable)  — KD
- [ ] Integrate integrity check into CI test suite (`tests/test_data_integrity.py`)

**Acceptance criteria:** Test passes on all four modes with zero foreground pixel data loss above threshold.

---

### 2.5  —  Algorithm Comparison and Pipeline Stress Test

**Feature Branch:** `feature/benchmarking-milestone2`

- [ ] Create `notebooks/algorithm_comparison.ipynb` with side-by-side MOG2 vs. KNN visualizations  *(data already in `cdnet_batch_results.log`)*
- [ ] Write `docs/algorithm_comparison.md` — production recommendation with tradeoff analysis  *(recommendation: MOG2 as primary)*
- [ ] Write `tests/test_pipeline_stress.py` — 1 hour simulated footage (loop a test clip)
- [ ] Verify memory does not grow unbounded over 1 hour (`tracemalloc` or `psutil`)
- [ ] Extrapolate 1-hour results to estimate storage for 60-day retention on 100 cameras
- [ ] Document stress test findings in `docs/stress_test_results.md`

**Acceptance criteria:** Pipeline runs 1 hour without crash or runaway memory growth. Storage extrapolation documented. Algorithm comparison notebook renders correctly.

---

### Milestone 2 Sign-Off Checklist

- [ ] `pytest tests/ -v` passes with zero failures  —  Verifier: ___
- [ ] All four compression modes produce valid output  —  Verifier: ___
- [ ] Enhancement module upscales a test image correctly  —  Verifier: ___
- [ ] Stress test completed without crash  —  Verifier: ___
- [ ] `object_type` DB field works end-to-end  —  Verifier: ___
- [ ] PR reviewed by at least one other team member  —  Reviewer: ___

---

## Milestone 3  —  Final Demo + Deliverables
**Target Completion: May 6, 2026 (HARD DEADLINE)**
**Branch:** `feature/*` → `dev` → merge to `main` after final review and tag `v1.0.0`

### 3.1  —  AES-256 Encryption

**Feature Branch:** `feature/encryption`

- [x] Implement AES-256 encryption for compressed output video files (`--encrypt` flag)  — KD
- [ ] Use Python `cryptography` library; store IV alongside segment record in DB
- [ ] Add password-protected export for incident clips (AES-encrypted zip or container)
- [ ] Write unit tests: encrypt/decrypt round-trip, IV uniqueness per segment

**Acceptance criteria:** Encrypted output cannot be played without decryption key. Round-trip test passes. IV stored correctly in DB.

---

### 3.2  —  Searchable Metadata Index

**Feature Branch:** `feature/metadata-search` (extend from M2)

- [ ] Expose `query_by_type(object_type, camera_id, start_time, end_time)` as a stable API
- [ ] Add full-text or tag-based search across the metadata index
- [ ] Return ranked list of matching segment file paths sorted by target count
- [ ] Document query interface in `README.md`

**Acceptance criteria:** Sponsor can locate all segments containing "person" detections from a specific camera in a time range without manually scrubbing video.

---

### 3.3  —  External Footage Ingestion

**Feature Branch:** `feature/drop-folder`

- [ ] Implement drag-and-drop / watchfolder approach: auto-ingest new video files dropped into a folder
- [ ] Support input from external sources (body cameras, other surveillance systems)
- [ ] Simple CLI or watchfolder daemon that picks up new `.mp4` / `.avi` files and routes through pipeline

**Acceptance criteria:** Dropping a video file into the watchfolder triggers automatic pipeline processing without manual CLI invocation.

---

### 3.4  —  Deployment Packaging

**Feature Branch:** `feature/deployment`

- [ ] Research and document deployment packaging format for government COTS hardware (Docker, PyInstaller, OS package, or source tarball)
- [ ] Must be compatible with COTS x86 hardware (no GPU dependency)
- [ ] Document findings in `docs/deployment_guide.md`; decision to be confirmed with Cody (Gina follow-up)

**Acceptance criteria:** A non-developer government operator can install and run the pipeline using only the deployment package and the README.

---

### 3.5  —  Live Demo Preparation

**Feature Branch:** `feature/demo-prep`

- [ ] Confirm pipeline runs on USB or IP camera input in real time (`--input 0`)
- [ ] Verify `--preview` flag shows live foreground mask alongside original feed
- [x] Create `demo.sh` — one-click pipeline launch with sensible defaults, no args required  — KD
- [ ] Test demo on laptop with no GPU (simulate target hardware)
- [ ] Prepare 2-minute live demo segment: feed → mask → Mode 0 output → Mode 1 output → storage stats → metadata query

**Acceptance criteria:** Demo runs on a stock CPU-only laptop. All four modes demonstrated. Compressed output produced within 30 seconds of launch.

---

### 3.6  —  Final Report and Quantitative Results

**Feature Branch:** `feature/final-report`

- [ ] Create `docs/final_report.md`: system architecture, mode descriptions, benchmark results, enhancement results, encryption design, limitations
- [ ] Populate final numbers table: compression ratio, PSNR, SSIM, storage per day per camera (Mode 0 vs. Mode 1)
- [ ] Create `notebooks/final_results.ipynb` — re-run all benchmarks from scratch on final codebase
- [ ] Include side-by-side figure: original vs. Mode 0 vs. Mode 1 compressed frame

**Acceptance criteria:** Report is complete, numbers are reproducible by running the notebook on a clean install.

---

### 3.7  —  Repository Polish and Documentation

**Feature Branch:** `feature/docs-cleanup`

- [ ] Ensure all public-facing modules have docstrings (`pipeline.py`, `roi_encoder.py`, `db.py`, `frame_source.py`, `metrics.py`, `enhancer.py`)
- [ ] Update `README.md` to reflect final architecture, all four modes, and benchmark numbers
- [ ] Update `DEV.md` with setup steps for Real-ESRGAN model download, encryption deps, CDnet dataset
- [ ] Ensure `requirements.txt` is accurate (`pip freeze` cross-check)
- [ ] Tag final commit as `v1.0.0`
- [ ] Verify repo clones cleanly on a fresh machine and pipeline runs in under 15 minutes

**Acceptance criteria:** A new team member can clone, install, and run the pipeline in under 15 minutes using only `README.md` and `DEV.md`.

---

### 3.8  —  Capstone Presentation

- [ ] Create slide deck: problem statement, approach, four-mode system, benchmark results, demo footage
- [ ] Prepare 2-minute live demo segment
- [ ] Rehearse full presentation as a team
- [ ] Submit final deliverable to course portal (hard deadline: May 6, 2026)

---

### Milestone 3 Sign-Off Checklist

- [ ] `pytest tests/ -v` passes with zero failures on a clean install  —  Verifier: ___
- [ ] Final report is complete and numbers are reproducible  —  Verifier: ___
- [ ] Encryption round-trip test passes  —  Verifier: ___
- [ ] Live demo works on target hardware  —  Verifier: ___
- [ ] Repository tagged `v1.0.0`  —  Verifier: ___
- [ ] All team members have reviewed the final README  —  Reviewer: All

---

## Branch and PR Strategy

```
main          ← stable, always working, tagged at each milestone
  └── dev     ← integration branch (all features merge here first)
        ├── feature/compression-modes        (Riley — Mode 2, Mode 3, concat)
        ├── feature/enhancement-superresolution
        ├── feature/metadata-database        (extended from M1)
        ├── feature/metadata-search
        ├── feature/data-integrity
        ├── feature/encryption
        ├── feature/drop-folder
        ├── feature/deployment
        ├── feature/benchmarking-milestone2
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
| **Milestone 2** | Compression modes + enhancement + encryption + stress test | **April 18, 2026** |
| **Milestone 3** | Final demo + report + encryption + repo polish | **May 6, 2026** |

---

## Sponsor Requirements (from Meetings)

Logged here so all team members have context on constraints that informed scope decisions.

- **CPU-only, no GPU** — government hardware is low-spec COTS x86
- **NDAA compliance** — no Chinese-origin software (eliminates some YOLO variants)
- **60-day retention** — storage math must scale to 100+ cameras
- **Risk-intolerant on data loss** — even 5% foreground pixel loss is unacceptable (Cody's words)
- **AES-256 encryption** — required for footage stored and transmitted over network
- **Searchable index** — eliminate manual video scrubbing; must query by object type, camera, and time range
- **Four compression modes** — different operational contexts need different storage/quality tradeoffs
- **Open source, royalty-free** — no commercial licensing (government acquisition rules)
- **Deployment packaging** — TBD; Cody to follow up with Gina on approved packaging format

---

## Stretch Goals (If Time Permits)

- GPU-accelerated encode path (NVENC) as an optional fast-path for non-government deployments
- RTSP stream support for IP cameras
- Web dashboard for metadata query and playback
- Automated model weight update pipeline for Real-ESRGAN

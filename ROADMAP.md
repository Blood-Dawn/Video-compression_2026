# Project Roadmap
## Open Source Selective Video Compression for Static Surveillance Cameras
**EGN 4950C Capstone | Florida Atlantic University | Spring 2026**
**Sponsor:** Defense Innovation Unit (DIU)
**Team:** Kheiven D'Haiti · Jorge Sanchez · Ashleyn Montano · Riley Roberts · Victor De Souza Teixeira
**Final Deadline:** May 6, 2026

---

## How to Use This Roadmap

Each milestone below lists the tasks that need to be completed. **Team members: write your name next to the task(s) you are owning.** If a task doesn't have a name next to it, it's unassigned. Every task should have exactly one owner by the end of the first team meeting each milestone.

Format for claiming a task:
```
- [ ] Task description  -  **Owner: Your Name**
```

---

## Project Goals (Big Picture)

The end deliverable is a working, open-source software pipeline that:

1. **Ingests** a static camera feed (USB, IP camera, or pre-recorded test video)
2. **Separates** foreground objects (people, vehicles) from the static background using background subtraction
3. **Encodes** foreground regions at high quality and background at heavy compression using FFmpeg + libx264
4. **Indexes** every video segment in a SQLite metadata database for fast retrieval
5. **Stores** compressed footage locally for approximately one week
6. **Enhances** compressed footage post-offload using CPU-based super-resolution
7. **Demonstrates** measurable storage savings (target: 6x vs. naive full-frame H.264)

All components must be open source, royalty-free, and run on CPU-only hardware.

---

## Phase 0  -  Project Setup
**Target: Week of January 13, 2026 → COMPLETED**

These tasks were completed before the semester sprint began.

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

## Milestone 1  -  Core Pipeline Functional
**Target Completion: March 31, 2026**
**Branch:** `dev` → merge to `main` when milestone passes all tests

### Goal
Get the end-to-end pipeline running on a real test video clip and producing measurable, verifiable compression results. All Milestone 1 deliverables should be demoed live with a test clip.

### 1.1  -  Background Subtraction Tuning
**Feature Branch:** `feature/background-subtraction-tuning`

- [x] Tune MOG2 parameters (`history`, `varThreshold`, `detectShadows`) on sample footage  -  **Owner: Bloodawn (KheivenD)** ✅ 2026-03-24 — night_mode flag adds CLAHE preprocessing + varThreshold=30 for low-light; VAR_THRESHOLD_DAY=16 / VAR_THRESHOLD_NIGHT=30 class constants set
- [x] Tune KNN parameters on the same footage and compare mask quality  -  **Owner: Bloodawn (KheivenD)** ✅ 2026-03-26 — full 46-scene CDnet sweep run with both MOG2 and KNN; results in outputs/cdnet_batch_results.log; MOG2 recommended as primary algorithm
- [ ] Implement morphological cleanup (erosion/dilation) to remove noise from the foreground mask  -  **Owner: ___________**
- [ ] Add minimum contour area filter to discard trivially small detections  -  **Owner: ___________**
- [ ] Write unit tests covering mask generation, empty frames, and all-foreground frames  -  **Owner: ___________**

**Acceptance criteria:** Foreground mask correctly isolates walking people and vehicles in the test clip with minimal noise. No false positives on a fully static frame.

---

### 1.2  -  ROI Encoding Pipeline
**Feature Branch:** `feature/roi-ffmpeg-encoding`

- [ ] Complete `ROIEncoder.encode_segment()` to produce a real compressed output file  -  **Owner: ___________**
- [ ] Implement dual-pass encoding: foreground ROIs at CRF 18-23, background at CRF 40-51  -  **Owner: ___________**
- [ ] Validate that the output file is a valid, playable video (not corrupted)  -  **Owner: ___________**
- [ ] Implement `ROIEncoder.get_file_size()` and log pre/post compression sizes  -  **Owner: ___________**
- [ ] Write integration test: encode a 10-second clip, verify output exists and is smaller than input  -  **Owner: ___________**

**Acceptance criteria:** Output file plays back correctly. Compressed size is measurably smaller than input. No FFmpeg subprocess errors.

---

### 1.3  -  Metrics and Benchmarking
**Feature Branch:** `feature/benchmarking-milestone1`

- [ ] Implement `compute_psnr()` and `compute_ssim()` in `src/utils/metrics.py` and verify against known reference values  -  **Owner: ___________**
- [ ] Implement `compute_compression_ratio()`  -  **Owner: ___________**
- [x] Create foreground coverage benchmark across all CDnet categories  -  **Owner: Bloodawn (KheivenD)** ✅ 2026-03-26 — scripts/run_all_cdnet.py runs all 46 scenes; per-category avg FG% documented in outputs/cdnet_batch_results.log and session_log_2026-03-26.md
- [ ] Create `notebooks/milestone1_benchmark.ipynb` that runs the pipeline on a test clip and reports PSNR, SSIM, and compression ratio  -  **Owner: ___________**
- [ ] Document results in `docs/milestone1_results.md`  -  **Owner: ___________**

**Acceptance criteria:** Notebook runs end-to-end without errors. Compression ratio is ≥ 3x on test footage. PSNR on foreground ROIs is ≥ 30 dB. SSIM on foreground ROIs is ≥ 0.85.

---

### 1.4  -  Metadata Database
**Feature Branch:** `feature/metadata-database`

- [x] Create `src/utils/db.py` with SQLite schema: `segments` table (timestamp, camera_id, target_detected, roi_count, file_size, duration, file_path)  -  **Owner: Ashleyn Montano___________**
- [x] Integrate database writes into the pipeline (write one row per encoded segment)  -  **Owner: Ashleyn Montano__________**
- [x] Implement query: "return all segments from camera X where targets were detected in the last N hours"  -  **Owner: Ashleyn Montano ___________**
- [x] Write unit tests for schema creation, insertion, and query  -  **Owner: Ashleyn Montano___________**

**Acceptance criteria:** After a pipeline run, `metadata.db` exists and contains correct rows. Query returns correct results.

---

### Milestone 1 Sign-Off Checklist
Before merging to `main`, every item below must be checked:

- [ ] `pytest tests/ -v` passes with zero failures  -  **Verifier: ___________**
- [ ] Pipeline runs on test clip and produces output without errors  -  **Verifier: ___________**
- [ ] Compression ratio documented in benchmark notebook  -  **Verifier: ___________**
- [ ] PSNR / SSIM documented in benchmark notebook  -  **Verifier: ___________**
- [ ] PR reviewed by at least one other team member  -  **Reviewer: ___________**

---

## Milestone 2  -  Enhancement + Stress Testing
**Target Completion: April 18, 2026**
**Branch:** `dev` → merge to `main` when milestone passes all tests

### Goal
Add post-offload super-resolution enhancement to foreground ROIs. Stress test the full pipeline on a simulated week of footage. Complete the algorithm comparison between MOG2 and KNN.

### 2.1  -  Super-Resolution Enhancement Module
**Feature Branch:** `feature/enhancement-superresolution`

- [ ] Research Real-ESRGAN CPU inference setup and document model download steps in DEV.md  -  **Owner: ___________**
- [ ] Create `src/enhancement/enhancer.py` with `Enhancer` class  -  **Owner: ___________**
- [ ] Implement `Enhancer.upscale_frame(frame: np.ndarray, scale: int) -> np.ndarray` using Real-ESRGAN in CPU mode  -  **Owner: ___________**
- [ ] Implement `Enhancer.upscale_roi(frame, bbox)` to upscale only a bounding region  -  **Owner: ___________**
- [ ] Integrate the enhancement step into the pipeline as an optional post-offload pass  -  **Owner: ___________**
- [ ] Benchmark enhancement processing time per frame on CPU hardware  -  **Owner: ___________**
- [ ] Write unit tests for enhancer with a small test image  -  **Owner: ___________**

**Acceptance criteria:** `Enhancer.upscale_frame()` returns an image with 2x or 4x larger dimensions. PSNR on enhanced output is measurably higher than non-enhanced compressed output.

---

### 2.2  -  Algorithm Comparison: MOG2 vs. KNN
**Feature Branch:** `feature/benchmarking-visdrone`

- [x] Curate a set of test clips representing different lighting conditions (day, night, shadow, thermal, weather)  -  **Owner: Bloodawn (KheivenD)** ✅ 2026-03-26 — CDnet 2014 used as benchmark dataset: 46 scenes across baseline, badWeather, shadow, dynamicBackground, intermittentObjectMotion, lowFramerate, cameraJitter, turbulence, nightVideos, thermal
- [x] Run both MOG2 and KNN on each clip, recording avg FG%, max FG%, and activity rate  -  **Owner: Bloodawn (KheivenD)** ✅ 2026-03-26 — full results in outputs/cdnet_batch_results.log; MOG2 outperforms KNN on false positive rate across all edge-case categories
- [ ] Create `notebooks/algorithm_comparison.ipynb` with side-by-side visualizations  -  **Owner: ___________**
- [ ] Write a short recommendation in `docs/algorithm_comparison.md`: which algorithm to use in production and why  -  **Owner: ___________** *(data collected — needs writeup; recommendation is MOG2 as primary; see session_log_2026-03-26.md for summary)*

**Acceptance criteria:** Notebook produces side-by-side visualizations. Recommendation doc explains the tradeoffs clearly.

---

### 2.3  -  Pipeline Stress Test
**Feature Branch:** `feature/stress-test`

- [ ] Write `tests/test_pipeline_stress.py` that simulates 1 hour of continuous footage (looping a test clip)  -  **Owner: ___________**
- [ ] Verify memory usage does not grow unbounded over 1 hour of operation  -  **Owner: ___________**
- [ ] Extrapolate 1-hour results to estimate storage for a full week  -  **Owner: ___________**
- [ ] Document findings in `docs/stress_test_results.md`  -  **Owner: ___________**

**Acceptance criteria:** Pipeline runs for 1 hour without crash or runaway memory growth. Storage extrapolation is documented.

---

### 2.4  -  Metadata Query Interface
**Feature Branch:** `feature/metadata-database` (extend from Milestone 1)

- [ ] Implement `db.py` query: "return segments sorted by most targets detected"  -  **Owner: ___________**
- [ ] Implement `db.py` query: "return daily storage summary by camera"  -  **Owner: ___________**
- [ ] Add a simple CLI query tool: `python src/utils/db_query.py --camera cam_01 --last-hours 24`  -  **Owner: ___________**

**Acceptance criteria:** CLI query tool returns correct results. No SQL injection vulnerabilities.

---

### Milestone 2 Sign-Off Checklist

- [ ] `pytest tests/ -v` passes with zero failures  -  **Verifier: ___________**
- [ ] Enhancement module upscales a test image correctly  -  **Verifier: ___________**
- [ ] Stress test completed without crash  -  **Verifier: ___________**
- [ ] Algorithm comparison notebook renders correctly  -  **Verifier: ___________**
- [ ] PR reviewed by at least one other team member  -  **Reviewer: ___________**

---

## Milestone 3  -  Final Demo + Deliverables
**Target Completion: May 6, 2026 (HARD DEADLINE)**
**Branch:** `dev` → merge to `main` after final review

### Goal
Polish the pipeline for a live demo, produce the final quantitative results report, and deliver a clean, installable open-source repository.

### 3.1  -  Live Demo Preparation
**Feature Branch:** `feature/demo-prep`

- [ ] Confirm the pipeline runs correctly on a USB or IP camera input in real time  -  **Owner: ___________**
- [ ] Add `--preview` flag to pipeline that shows live foreground mask alongside original feed  -  **Owner: ___________**
- [ ] Create a demo script `demo.sh` (or `demo.bat`) that launches the pipeline with sensible defaults  -  **Owner: ___________**
- [ ] Test the demo on a laptop with no GPU (simulate the target hardware)  -  **Owner: ___________**

**Acceptance criteria:** Demo runs on a stock laptop. Foreground mask is visible. Compressed output is produced.

---

### 3.2  -  Final Report and Quantitative Results
**Feature Branch:** `feature/final-report`

- [ ] Create `docs/final_report.md` summarizing: system architecture, algorithm choices, benchmark results, enhancement results, limitations  -  **Owner: ___________**
- [ ] Populate final numbers table: compression ratio, PSNR (foreground), SSIM (foreground), enhancement delta, storage savings per day per camera  -  **Owner: ___________**
- [ ] Create `notebooks/final_results.ipynb` that re-runs all benchmarks from scratch on the final codebase  -  **Owner: ___________**
- [ ] Include figure: side-by-side frame comparison (original vs. compressed vs. enhanced)  -  **Owner: ___________**

**Acceptance criteria:** Report is complete, numbers are reproducible by running the notebook.

---

### 3.3  -  Repository Polish and Documentation
**Feature Branch:** `feature/docs-cleanup`

- [ ] Ensure all public-facing modules have docstrings  -  **Owner: ___________**
- [ ] Update `README.md` to reflect final architecture and results  -  **Owner: ___________**
- [ ] Update `DEV.md` with any new setup steps discovered during development  -  **Owner: ___________**
- [ ] Ensure `requirements.txt` is accurate (run `pip freeze` and cross-check)  -  **Owner: ___________**
- [ ] Tag final commit as `v1.0.0`  -  **Owner: ___________**
- [ ] Verify repo clones cleanly on a fresh machine and pipeline runs  -  **Owner: ___________**

**Acceptance criteria:** A new team member can clone the repo, run `pip install -r requirements.txt`, and run the pipeline in under 15 minutes using only README.md and DEV.md as guides.

---

### 3.4  -  Capstone Presentation
**Feature Branch:** N/A (presentation materials)

- [ ] Create slide deck covering: problem, approach, architecture diagram, quantitative results, demo footage  -  **Owner: ___________**
- [ ] Prepare 2-minute live demo segment  -  **Owner: ___________**
- [ ] Rehearse full presentation as a team  -  **Owner: All**
- [ ] Submit final deliverable to course portal  -  **Owner: ___________**

**Acceptance criteria:** Presentation is polished and fits the allotted time. Demo works on presentation hardware.

---

### Milestone 3 Sign-Off Checklist

- [ ] `pytest tests/ -v` passes with zero failures on a clean install  -  **Verifier: ___________**
- [ ] Final report is complete and numbers are reproducible  -  **Verifier: ___________**
- [ ] Live demo works on target hardware  -  **Verifier: ___________**
- [ ] Repository tagged `v1.0.0`  -  **Verifier: ___________**
- [ ] All team members have reviewed the final README  -  **Reviewer: All**

---

## Branch and PR Strategy

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
        ├── feature/demo-prep
        ├── feature/final-report
        └── feature/docs-cleanup
```

**Rules:**
- Never commit directly to `main`
- Always branch from `dev`, not from `main`
- Every PR into `dev` needs at least one reviewer approval
- `dev` is merged into `main` only at milestone completions
- Commit messages should be descriptive: `feat: add MOG2 shadow suppression`, `fix: FFmpeg pipe closed before read`

---

## Timeline Summary

| Milestone | Description | Target Date |
|---|---|---|
| Phase 0 | Repo scaffold, initial code | ✅ Complete |
| **Milestone 1** | Core pipeline + metrics + database | **March 31, 2026** |
| **Milestone 2** | Enhancement module + stress test + algorithm comparison | **April 18, 2026** |
| **Milestone 3** | Final demo + report + repo polish | **May 6, 2026** |

---

## Stretch Goals (If Time Permits)

These are not required for the capstone but would strengthen the project:

- VMAF metric integration for perceptual quality scoring
- Lightweight YOLO-based object detection to verify people/vehicles are still detectable in compressed output
- Web dashboard for querying the metadata database
- Docker container for easy deployment on any hardware
- Automated weekly storage report email

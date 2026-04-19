# Test suite results
**EGN 4950C Group 16 — Open Source Selective Video Compression**
Last updated: Apr 19, 2026 · Branch: `dev`

---

## Summary

| File | Tests | Passing | Skipped | Failing |
|---|---|---|---|---|
| test_background_subtraction.py | 29 | 29 | 0 | 0 |
| test_metrics.py | 25 | 25 | 0 | 0 |
| test_gui_api.py | 24 | 24 | 0 | 0 |
| test_database.py | 20 | 20 | 0 | 0 |
| test_frame_source.py | 20 | 20 | 0 | 0 |
| test_roi_encoder.py | 19 | 19 | 0 | 0 |
| test_data_integrity.py | 14 | 14 | 0 | 0 |
| test_enhancer.py | 15 | 15 | 0 | 0 |
| test_detection_accuracy.py | 14 | 14 | 0 | 0 |
| test_object_type_queries.py | 5 | 5 | 0 | 0 |
| test_pipeline.py | 4 | 4 | 0 | 0 |
| test_pipeline_stress.py | — | — | — | — |
| **Total** | **189** | **189** | **0** | **0** |

`test_pipeline_stress.py` runs a 1-hour simulation and is excluded from the standard suite. Run it separately with `pytest tests/test_pipeline_stress.py`.

---

## What each file tests and why it matters

### test_background_subtraction.py — 29 tests

**What it covers:** MOG2 and KNN background subtraction — mask generation, night-mode CLAHE preprocessing, morphological cleanup, minimum contour area filtering, edge cases (empty frames, single-pixel motion, all-black input).

**Why it matters:** Background subtraction is the first stage of the pipeline. If the mask is wrong, every downstream decision — what to compress hard, what to save at high quality, what gets tagged as a target — is wrong. These 29 tests lock in the tuned defaults (`varThreshold=50`, `detectShadows=False`) that Jorge and Ashleyn validated against CDnet.

---

### test_metrics.py — 25 tests

**What it covers:** `compute_psnr()`, `compute_ssim()`, and `compute_compression_ratio()` in `src/utils/metrics.py`. Includes known-value verification (PSNR of identical frames = ∞, PSNR of random noise vs black frame ≈ known value), edge cases (zero-size input, negative values, division by zero in ratio).

**Why it matters:** These are the numbers in the final report — 16.6x compression, PSNR 41.2 dB, SSIM 0.9783. If the metric functions have a bug, every benchmark number is wrong. The known-value tests catch silent regressions.

---

### test_gui_api.py — 24 tests *(added Apr 19, 2026)*

**What it covers:** All 5 core API endpoints of the Flask dashboard:

- `GET /api/status` — HTTP 200, correct JSON keys, idle defaults (running=False, elapsed=None, fps=None)
- `POST /api/start` — HTTP 200 + `{"ok": true}`, config echo, default config values, 409 on double-start, state transition to running=True
- `POST /api/stop` — 409 when pipeline is idle, HTTP 200 + `{"ok": true}` when running, state transitions back to running=False, full start→stop cycle
- `GET /api/segments` — empty list when no DB exists, correct segment rows from a seeded DB, expected JSON shape per segment, newest-first ordering
- `GET /api/storage` — `available=False` when no DB, correct aggregate counts and byte totals from a seeded DB

**Why it matters:** The GUI is the primary interface for the sponsor demo. Regressions in any of these endpoints would break the live demo silently. The tests use a fake pipeline thread (no video file or FFmpeg needed) so they run in under 2 seconds on any machine.

**Design notes:**
- The `reset_pipeline_state` fixture runs before every test and points `output_dir` at a fresh `tmp_path` so tests are isolated from any real `outputs/metadata.db` on the developer's machine.
- The `fake_pipeline` fixture replaces `_run_pipeline_thread` with a function that sets `running=True`, blocks on `stop_event`, then sets `running=False`. This makes start/stop state transitions deterministic.

---

### test_database.py — 20 tests

**What it covers:** SQLite schema creation (`initialize_database()`), WAL mode, `idx_cam_time` index, `insert_segment()`, `query_recent_targets()`, multi-camera isolation, edge cases (zero file size, empty camera ID, duplicate timestamps).

**Why it matters:** Every compressed segment gets a row in this database. If inserts silently fail or queries return wrong results, the metadata search the sponsor specifically asked for becomes unreliable. The 20-test suite was expanded from the original 2-test stub after the M1 audit.

---

### test_frame_source.py — 20 tests

**What it covers:** `FrameSource` — opening video files and camera indices, `read()` return shape and type, EOF handling, `fps`/`width`/`height` attributes, `get_warmup_frames()` defaults, error handling on bad paths.

**Why it matters:** `FrameSource` is the entry point for every frame in the pipeline. A broken `read()` return type or wrong EOF signal would corrupt the entire frame loop silently. These tests confirmed the OpenCV wrapper is reliable before Mode 1/2/3 were built on top of it.

---

### test_roi_encoder.py — 19 tests

**What it covers:** `ROIEncoder.encode_segment()` — FFmpeg subprocess invocation, dual-CRF logic (foreground CRF 18 / background CRF 45), MP4 output validation (non-zero file, playable header), `get_file_size()`, DB row write per segment, error handling when FFmpeg exits non-zero.

**Why it matters:** The encoder is where the actual compression happens. The dual-CRF split (CRF 18 foreground, CRF 45 background) is the core mechanism behind our 16.6x compression ratio. These 19 tests ensure Jorge's pipe-based FFmpeg integration doesn't regress — a broken `communicate()` call would cause a deadlock with no error output.

---

### test_data_integrity.py — 14 tests

**What it covers:** Frame-level ROI pixel comparison through the full encode→decode cycle. Checks that foreground region pixels survive compression with acceptable loss (PSNR threshold), that background region pixels degrade as expected at CRF 45, and that no silent data corruption occurs in the pipe handoff.

**Why it matters:** The sponsor was explicit: "foreground data loss is unacceptable even at 5%." These tests are the automated proof that we meet that requirement. The CI integration task (2.4) will run this file on every PR to `dev`.

---

### test_enhancer.py — 15 tests

**What it covers:** `Enhancer.upscale_frame()` (x2 and x4 scale), `upscale_roi()` bbox paste, `enhance_batch()`, `is_available()` for all three backends (Real-ESRGAN, OpenCV DNN, bicubic), graceful fallback when model weights are missing.

**Why it matters:** The bicubic fallback is what runs on CPU-only government hardware. These tests confirm the fallback is always available even when `basicsr` is not installed — which is the expected state on a fresh DoD machine.

---

### test_object_type_queries.py — 5 tests

**What it covers:** `query_by_type()` filtering (person, vehicle, unknown), combined `camera_id` + `object_type` filtering, empty results for unknown types, `object_type` default value when not specified.

**Why it matters:** These queries back the "Query Archive" sidebar in the GUI. Geena (NIWC) specifically asked for the ability to search footage by object type. A broken query filter would return wrong results silently.

---

### test_pipeline.py — 4 tests

**What it covers:** Pipeline integration with dummy injected components — EOF behavior when video ends exactly on a full segment boundary, no extra partial-segment encode at EOF, Mode 1 frame-gating (only frames with foreground regions enter the buffer), stop_event graceful shutdown.

**Why it matters:** The EOF boundary and Mode 1 gating tests caught a real bug: an off-by-one in the segment flush was encoding one empty segment after EOF. The dummy component injection pattern (replace FrameSource + ROIEncoder with test doubles) keeps these tests fast and deterministic without needing real video.

**Note on dummy encoders:** The dummy encoders accept `object_type=None, **kwargs` so they stay compatible as the real `encode_segment()` signature evolves. Any new kwargs added to the real encoder should be mirrored in the dummy's `**kwargs` catch-all.

---

### test_detection_accuracy.py — 14 tests *(updated Apr 19, 2026)*

**What it covers:** MOG2 detection on the CDnet 2014 benchmark dataset (`data/samples/cdnet_mp4/`). No external clip or env var required — the 54 bundled videos activate all 14 tests automatically.

- `test_detection_not_empty` — at least one foreground region appears within 50 frames of `baseline_pedestrians.mp4`
- `test_false_positive_rate_on_static_scene` — FP rate stays under 2% on `baseline_office.mp4` after a 30-frame warmup
- `test_no_crash_on_cdnet_category` (parametrized × 11 categories) — BackgroundSubtractor processes 30 frames from one clip per category (PTZ, badWeather, baseline, cameraJitter, dynamicBackground, intermittentObjectMotion, lowFramerate, nightVideos, shadow, thermal, turbulence) without crashing or producing a corrupt mask
- `test_detection_on_nightVideos` — night-mode (CLAHE preprocessing) finds foreground in `nightVideos_bridgeEntry.mp4` within 80 frames

**Why it matters:** The 0% FP target on static scenes was a sponsor requirement. These tests verify the tuned defaults meet it on real surveillance footage across 11 scene categories — not just synthetic frames. The CDnet parametrized suite is a regression guard for anyone who changes MOG2 params.

**To run:**
```bash
# Standard — uses bundled CDnet clips automatically
uv run pytest tests/test_detection_accuracy.py -v

# Override with a specific clip
TEST_CLIP=path/to/clip.mp4 uv run pytest tests/test_detection_accuracy.py -v
```

---

### test_pipeline_stress.py — excluded from standard run

**What it covers:** 1-hour simulated continuous operation using a looped test clip. Tracks peak memory (`tracemalloc`), verifies memory does not grow unbounded, and reports projected storage at 60-day retention across 100 cameras.

**Results (Jorge, Apr 11, 2026):** No memory leak detected. Peak RSS growth under 5 MB over 1 hour. Full numbers in `docs/stress_test_results.md`.

**To run:**
```bash
pytest tests/test_pipeline_stress.py -v -s
# Takes ~1 hour. Set STRESS_DURATION_S=60 for a quick smoke test.
```

---

## How to run the suite

```bash
# Standard run (excludes stress test) — 189 tests, no setup required
uv run pytest tests/ --ignore=tests/test_pipeline_stress.py -v

# With coverage
uv run pytest tests/ --ignore=tests/test_pipeline_stress.py --cov=src --cov-report=term-missing

# Stress test (plan for 1 hour)
uv run pytest tests/test_pipeline_stress.py -v -s
```

---

## Known gaps

| Gap | Owner | Status |
|---|---|---|
| CI integration for `test_data_integrity.py` — run on every PR to `dev` | KD | Not Started (task 2.4) |
| `test_detection_accuracy.py` needs a shared test clip | AM, JS | ✅ Closed — uses CDnet clips from `data/samples/cdnet_mp4/` |
| `test_pipeline.py` needs tests for `--enhance` bicubic path and `--encrypt` round-trip | RR | Not Started (task 2.6) |
| No tests for Mode 2 or Mode 3 (not yet implemented) | RR | Blocked on mode implementation |
| No tests for HLS streaming routes | KD | Not Started (task 4.1) |
| No tests for adaptive mode controller | KD | Not Started (task 4.4) |

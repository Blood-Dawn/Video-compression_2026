# Session Log — 2026-04-26

**Author:** Kheiven D'Haiti (Bloodawn)
**Branch:** `dev`
**Milestone:** 3 — Detection hardening, multi-source ingestion, encryption upgrade

---

## Summary

This session closed five open threads: merged and hardened Riley Roberts' Mode 2/3 implementation (PR #11), merged Victor's AES-256-GCM encryption upgrade (PR #12), pulled Jorge's watchfolder daemon and multi-source RTSP manager (PR #13), merged the `m3-metadata-query-fix` branch from Ashleyn Montano, and landed a new YOLO classification gate (PR #31) that filters out false positives from background subtraction. The full test suite was repaired to match the streaming encoder API that was introduced in a prior session; all 274 tests pass at the end of the session.

---

## For Team Members — What to Expect After Pulling

Pull `dev` and run `uv sync` — one new optional dependency (`ultralytics`) was added for the YOLO filter gate. The gate is off by default; nothing changes unless you pass `--use-yolo` on the CLI or enable it in the GUI. If you do not have `ultralytics` installed, the pipeline falls back to unfiltered MOG2 detections automatically and logs a warning.

New CLI entry points are live:

```bash
# Query the metadata DB by object type, time range, and minimum ROI count
python -m src.utils.db_query --type vehicle person --last-hours 12 --min-roi 5

# Watch a drop folder and auto-ingest new video files
python src/utils/watchfolder.py --folder /mnt/drop --output outputs/ --camera-id cam_entrance
```

Encryption format changed from AES-256-CBC to AES-256-GCM. Existing `.enc` files from before this merge **cannot be decrypted** with the new code — re-encrypt any stored segments you need to keep.

---

## Changes by Area

### Mode system repair — PR #11 (Riley Roberts)

**What:** Riley's `fix/repair-dev-mode-system` branch was pulled into `dev`. The branch restored the mode dispatch that had been broken during the streaming encoder refactor. `modes.py` now exports `VALID_MODES`, `ModeDecision`, and `decide_frame_fate()` as the single source of truth for per-mode frame routing. `pipeline.py` was updated to use the streaming API throughout (`begin_segment` → `write_frame` × N → `finish_segment`), with separate `raw_regions` (pre-filter) and `regions` (post-filter) paths so Mode 2 background keyframe selection uses the pre-YOLO region list.

**Why:** The streaming encoder was landed mid-session in a prior week but `modes.py` still referenced the old `encode_segment(frames, bboxes_per_frame, ...)` call signature. That left Mode 2 and Mode 3 silently falling back to Mode 0 behavior.

**Where:** `src/pipeline/modes.py`, `src/pipeline/pipeline.py`, `src/compression/layer_encoder.py`

---

### Mode label and timer overlay — commit `5547564`

**What:** The pipeline now burns a text overlay into every output segment showing the active mode (`MODE 0 | 00:01:23`) in the top-left corner. The overlay is drawn by `cv2.putText` inside `write_frame()` before the frame is piped to FFmpeg, so it appears in the archived `.mp4` files and the HLS stream.

**Why:** During the April 22 sponsor test it was impossible to tell from a segment thumbnail which mode produced it. The overlay makes it unambiguous for review.

**Where:** `src/compression/roi_encoder.py`

---

### Double-compositing fix — commit `39fef25`

**What:** A bug in `encode_segment()` was applying the background composite twice per frame — once inside `write_frame()` and once in the outer loop in `pipeline.py`. This caused Mode 2 segments to show a double-blended artifact where the background appeared washed out. Removed the outer composite; `write_frame()` is now the sole compositing site.

**Why:** The outer composite was a leftover from before `write_frame()` was extracted. It went unnoticed because Mode 0 and Mode 1 don't use the background blend path.

**Where:** `src/compression/roi_encoder.py`, `src/pipeline/pipeline.py`

---

### AES-256-GCM encryption upgrade — PR #12 (Victor Teixeira)

**What:** The encryption module (`src/utils/encryption.py`) was upgraded from AES-256-CBC to AES-256-GCM. The new `.enc` file layout is:

```
Bytes  0 –  11  : Nonce        (12 bytes, random per file)
Bytes 12 –  27  : Salt         (16 bytes; zeros in raw-key mode)
Bytes 28 –  43  : Auth tag     (16 bytes, GCM)
Bytes 44 – end  : Ciphertext
```

`generate_key()`, `encrypt_file()`, and `decrypt_file()` all keep the same public API. A new `encrypt_bytes()` / `decrypt_bytes()` pair was added for in-memory use. The test suite (`tests/test_encryption.py`) was extended with round-trip tests at 1 KB, 1 MB, and multi-chunk sizes, plus a tamper detection test that verifies decryption raises `InvalidTag` when the ciphertext is modified.

**Why:** CBC does not authenticate the ciphertext — a bit-flip attack could corrupt stored footage without detection. GCM adds a 128-bit authentication tag that catches any modification before a single byte of plaintext is returned. This was a requirement from Cody Hayashi at NIWC Pacific.

**Where:** `src/utils/encryption.py`, `tests/test_encryption.py`

---

### Multi-type metadata query — branch `m3-metadata-query-fix` (Ashleyn Montano)

**What:** `query_by_type()` in `src/utils/db.py` was extended to accept either a single string or a list of strings as `object_type`. When a list is passed, the query uses parameterized `IN (?, ?, ...)` placeholders — not string interpolation, so SQL injection safety is preserved. A new `min_roi_count` parameter filters out low-confidence detections. The CLI tool `src/utils/db_query.py` was rewritten to expose `--type` (multi-value), `--min-roi`, `--start-time`, and `--end-time`, with `--last-hours` as a convenience shorthand.

**Why:** The original `query_by_type()` could only filter on a single object class. Operators reviewing footage routinely want `vehicle OR person` queries, and the CLI had no way to specify ROI count thresholds.

**Where:** `src/utils/db.py`, `src/utils/db_query.py`, `tests/test_object_type_queries.py`

---

### Watchfolder daemon + MultiFrameSource — PR #13 (Jorge Sanchez)

**What:** Two new modules were added:

**`src/utils/watchfolder.py`** — Polls a drop folder on a configurable interval (default 5 s). Detects new `.mp4 / .avi / .mov / .mkv / .ts / .mts / .m2ts` files, waits for them to stop growing (`_is_fully_written()`), and calls `run_pipeline()` on each. Uses a `.ingested` sentinel file beside each processed video to prevent double-processing on restart.

**`src/utils/multi_source.py`** — `MultiFrameSource` manages N parallel RTSP streams via `_StreamReader` daemon threads. Each reader maintains a 2-frame ring buffer and checks for stream stalls via `FRAME_TIMEOUT = 5.0` seconds. Public API: `open()`, `read_all()`, `any_alive()`, `active_count()`, `get_metadata()`, `release()`, context manager.

A racy test in `tests/test_multi_source.py::TestMultiFrameSource::test_any_alive_true_when_running` was fixed. The original mock used `frame_count=500` but the daemon thread could exhaust all 500 frames before the main thread reached the assertion. Fixed by replacing the mock with a `threading.Event` gate that blocks `read()` indefinitely until the test releases it.

**Why:** The sponsor demo required ingesting footage from an unattended SD card drop folder without manual intervention. `MultiFrameSource` lays the groundwork for future multi-camera synchronized capture.

**Where:** `src/utils/watchfolder.py`, `src/utils/multi_source.py`, `tests/test_watchfolder.py`, `tests/test_multi_source.py`

---

### YOLO object classification gate — PR #31

**What:** A new `ObjectFilter` class wraps YOLOv8-nano (via `ultralytics`) and runs on each bounding box crop produced by background subtraction before the frame is passed to the encoder. The filter:

- Classifies each crop at a configurable confidence threshold (default `conf=0.30`)
- Rejects crops whose top predicted class is not in an allowlist (e.g. `person`, `car`, `truck`, `bus`, `bicycle`, `motorcycle`, `dog`, `bird`)
- Maintains a 32-px static suppression grid (int16 counters) — cells that receive `threshold=30` consecutive false-positive-only frames are suppressed for the rest of the session, preventing persistent leaf/shadow hotspots from reaching the encoder

The gate is optional. When `ultralytics` is not installed the pipeline logs a warning and proceeds without filtering. Confidence tuning was validated on `nightVideos_busyBoulvard.mp4` across five runs:

| `conf` | Frames passed | Notes |
|--------|---------------|-------|
| 0.70   | 0             | Too aggressive for dim night scenes |
| 0.30   | 2             | Misses most distant vehicles at night |
| 0.10   | 184           | Practical sweet spot for low-light |

The default of `conf=0.30` is appropriate for daylight. Night / low-light scenes should use `conf=0.10` via `--yolo-conf 0.10`.

**Why:** Background subtraction on foliage-heavy or windy scenes produces hundreds of false-positive ROI crops per minute. At 30 fps this can inflate storage by 3-5× compared to a clean scene. The YOLO gate eliminates the majority of leaf/shadow false positives without requiring per-scene MOG2 threshold tuning.

**Where:** `src/detection/object_filter.py`, `src/pipeline/pipeline.py`, `tests/test_object_filter.py`

---

### GPU support for enhancer — task #23

**What:** `src/enhancement/enhancer.py` gained CUDA and MPS (Apple Silicon) acceleration. Device selection order: CUDA → MPS → CPU. A new `detect_gpu()` utility function returns a dict with `backend`, `device_name`, `cuda_available`, `mps_available`, `vram_mb`, and `will_work` fields. Exposed via `/api/gpu_info` so the dashboard can display what acceleration is available. Falls back silently to bicubic interpolation when the model weights are missing or the device fails to initialise.

**Why:** The Real-ESRGAN super-resolution step is the bottleneck on 4K clips. On an M2 MacBook Pro, MPS reduced per-frame enhancement time from ~420 ms (CPU) to ~95 ms.

**Where:** `src/enhancement/enhancer.py`

---

### Test suite repair — streaming encoder API

**What:** All test mocks in `tests/test_pipeline.py` were rewritten to implement the streaming encoder API introduced in a prior session. The old API was `encode_segment(frames, bboxes_per_frame, ...)` returning a file path string. The new API is `begin_segment()` → `write_frame()` × N → `finish_segment()` returning a `dict` with keys `file_path`, `avg_sharpness`, `sharpness_label`. Four test classes were updated:

- `DummyEncoder` — now implements the full streaming interface; `finish_segment()` returns the expected dict
- `RecordingEncoder` in `TestMode2Behavior` — captures `background_frame` and `object_only` from individual `write_frame()` calls instead of from a single `encode_segment()` kwargs dict
- `RecordingEncoder` in `TestMode1Behavior` and `TestMode3Behavior` — count frames via `write_frame()` call count

Also fixed in this pass:
- `tests/test_roi_encoder.py` — all `out.endswith(".mp4")` → `out["file_path"].endswith(".mp4")`
- `tests/test_data_integrity.py` — all result string usages → `result["file_path"]`
- `tests/test_object_type_queries.py` — replaced `results[0][-1]` with explicit `_OBJECT_TYPE_COL = 8` constant; the old index broke when `avg_sharpness`, `sharpness_label`, and `hidden` columns were added to the schema

**Final result: 274 passed, 0 failed.**

**Where:** `tests/test_pipeline.py`, `tests/test_roi_encoder.py`, `tests/test_data_integrity.py`, `tests/test_object_type_queries.py`

---

## Commits This Session

```
4a21a47  fix(tests): close PR #13 — fix racy any_alive assertion in test_multi_source
aa68c56  feat(detection): close PR #31 — YOLO object filter gate + full test suite repair
ba4f3db  feat(db): merge m3-metadata-query-fix — multi-type query + ROI count filter
39fef25  fix(encoder): remove double compositing in encode_segment frame loop
5547564  feat(encoder): burn mode label + elapsed timer overlay into pipeline output segments
8a10262  docs(roadmap): mark Mode 2, Mode 3, AES-256-GCM Done after Riley + Victor merges
4fdd0e5  feat(encryption): merge PR #12 — Victor AES-256-GCM upgrade with tamper detection and round-trip tests
fc2c9d6  chore(merge): pull Riley Mode 2 + Mode 3 from origin/dev
```

---

## Test Results

```
274 passed, 0 failed
```

Coverage spans: pipeline EOF/mode behavior, streaming encoder API, AES-256-GCM round-trips and tamper detection, YOLO object filter, metadata DB queries (single-type and multi-type), watchfolder daemon, MultiFrameSource stall detection, HLS streaming, ROI encoder, layer encoder, enhancer, metrics.

---

## Open Items / Next Session

- Night scene confidence (`--yolo-conf 0.10`) should be surfaced in the GUI as a "Night mode" toggle rather than a raw confidence input
- The `watchfolder.py` daemon needs a `--dry-run` flag wired into the GUI for operators to preview what files would be ingested before committing
- Consider adding a `/api/active_sources` endpoint that exposes `MultiFrameSource.get_metadata()` so the dashboard can list connected cameras in real time
- Investigate whether the static suppression grid should persist across restarts (serialize to SQLite `segments` DB or a separate grid file)

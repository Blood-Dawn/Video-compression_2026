# Progress Report 3
## EGN 4950C Senior Capstone — Group 16
**Florida Atlantic University · Spring 2026**
**Sponsor:** Defense Innovation Unit (DIU) / NIWC Pacific — Cody Hayashi
**Team:** Kheiven D'Haiti · Jorge Sanchez · Ashleyn Montano · Riley Roberts · Victor De Souza Teixeira
**Report period:** April 11 – April 26, 2026
**Hard deadline:** May 6, 2026

---

## Where we are

The pipeline works. Not "compiles and runs" works — end-to-end, on real surveillance footage, with compression numbers that hold up. Background-only segments compress at 16.6x over raw frames. Foreground ROI quality lands at 41.2 dB PSNR, 0.9783 SSIM. Storage projects to about 3–5 GB per camera per day at 1080p30, down from 12–15 GB with naive H.264. The sponsor's 60-day retention target across 100 cameras is achievable in roughly 18–30 TB — compared to 72–90 TB without our system.

This report covers the work from April 11 through today: four branches merged, two pull requests closed, a full test suite repaired and green at 274 tests, and several open Milestone 3 items landed ahead of schedule.

---

## What got done this period

### Encryption: AES-256-GCM (Victor Teixeira, PR #12 — merged)

Victor upgraded the encryption module from AES-256-CBC to AES-256-GCM. CBC has no authentication tag — a bit-flip attack can silently corrupt a stored video segment and the system never finds out. GCM adds a 128-bit auth tag, so any modification to the ciphertext, even a single bit, raises `InvalidTag` before any plaintext comes out.

The new file format:

```
Bytes  0–11   : Nonce (12 bytes, fresh random per file)
Bytes 12–27   : Salt  (16 bytes; zeros in raw-key mode)
Bytes 28–43   : Auth tag (GCM, 16 bytes)
Bytes 44–end  : Ciphertext
```

The public API didn't change — `encrypt_file()` and `decrypt_file()` work the same way for callers. Victor also added `encrypt_bytes()` / `decrypt_bytes()` for in-memory use, which the pipeline now uses for segment packaging without writing plaintext to disk first. The test suite covers 1 KB, 1 MB, and multi-chunk round-trips, plus a tamper detection test. 24 tests total, all passing.

One note for the team: existing `.enc` files encrypted under the old CBC scheme cannot be decrypted with this code. Re-encrypt any stored segments you need to keep.

---

### Mode system repair and Mode 2/3 completion (Riley Roberts, PR #11 — merged)

Riley's `fix/repair-dev-mode-system` branch restored the mode dispatch that had broken during the streaming encoder refactor. `modes.py` now owns the `ModeDecision` dataclass and `decide_frame_fate()` — the single function the pipeline calls per frame to decide whether to buffer it, what quality to apply, and whether to composite a background keyframe.

Mode 2 and Mode 3 are both live:

**Mode 2** captures one clean background frame during warmup (or falls back to the last warmup frame if no fully-static frame appeared), then composites per-frame object patches over it. The result is a segment that looks like a surveillance feed but only encodes the moving parts — the background is frozen from a single reference keyframe. Storage savings over Mode 0 are roughly 2–3x on active scenes.

**Mode 3** blacks out everything outside detected bounding boxes before piping to FFmpeg. What you get is a clip with faces, license plates, and moving objects at full quality — and nothing else. It's the most aggressive mode and produces the smallest files, at the cost of losing spatial context.

Both modes are selectable in the GUI.

---

### Multi-type metadata query (Ashleyn Montano, branch `m3-metadata-query-fix` — merged)

The original `query_by_type()` in `db.py` could only filter on a single object class. Operators reviewing footage routinely want compound queries — "show me all segments with vehicles or people in the last 12 hours." Riley extended the function to accept either a string or a list, using parameterized `IN (?, ?, ...)` placeholders (not string interpolation, so SQL injection safety is preserved). A new `min_roi_count` parameter lets callers filter out low-confidence detections.

The CLI tool `db_query.py` was rewritten at the same time:

```bash
python -m src.utils.db_query \
  --type vehicle person \
  --camera cam_01 \
  --last-hours 12 \
  --min-roi 5
```

---

### Watchfolder daemon and MultiFrameSource (Jorge Sanchez, PR #13 — merged)

Jorge delivered two modules that came directly from the sponsor's request to handle footage from body cameras and external drives — not just the live pipeline.

**`watchfolder.py`** polls a drop folder every 5 seconds. When it finds a new `.mp4`, `.avi`, `.mov`, `.mkv`, or `.ts` file, it waits for the file to stop growing (confirming the write is finished), then calls `run_pipeline()` on it. A `.ingested` sentinel file beside each processed video prevents double-processing after a restart.

```bash
python src/utils/watchfolder.py \
  --folder /mnt/drop \
  --output outputs/ \
  --camera-id cam_entrance
```

**`multi_source.py`** manages N parallel RTSP streams via daemon threads. Each `_StreamReader` keeps a 2-frame ring buffer and monitors the stream for stalls with a 5-second timeout. The public interface is straightforward: `open()`, `read_all()`, `any_alive()`, `get_metadata()`, `release()`, and a context manager. This is the foundation for future multi-camera synchronized capture.

One bug was fixed during integration: the original `test_any_alive_true_when_running` test was racy. The mock stream used 500 pre-generated frames, but the background thread could exhaust all 500 before the main thread reached the assertion. The fix blocks `read()` with a `threading.Event` gate until after the assertion completes, then releases for cleanup. 22 tests total across both modules, all passing.

---

### YOLO object classification gate (Kheiven D'Haiti, PR #31 — merged)

Background subtraction on foliage-heavy scenes generates hundreds of false-positive ROI crops per minute. Wind moves leaves; MOG2 sees motion; the encoder buffers the frame at CRF 18. On a busy outdoor scene this inflates storage 3–5x compared to a clean baseline — all from pixels that aren't people or vehicles.

The gate runs YOLOv8-nano on each bounding box crop produced by MOG2 before the frame reaches the encoder. If the top predicted class isn't in the allowlist (person, car, truck, bus, bicycle, motorcycle, dog, bird), the crop is rejected. A 32-pixel static suppression grid tracks cells that consistently produce false positives — once a cell accumulates 30 consecutive false-only frames, it's suppressed for the rest of the session, preventing persistent hotspots from reaching the encoder at all.

The gate is optional. If `ultralytics` isn't installed, the pipeline logs a warning and runs without filtering. If it is installed, it's off by default — enable it with `--use-yolo`.

Night scene calibration matters here. Testing on `nightVideos_busyBoulvard.mp4` showed the default threshold of `conf=0.30` is too aggressive for dim footage:

| `conf` | Frames passed | Notes |
|--------|---------------|-------|
| 0.70 | 0 | Rejects everything at night |
| 0.30 | 2 | Misses most distant vehicles |
| 0.10 | 184 | Catches distant/dim vehicles |

For night deployment, use `--yolo-conf 0.10`. The GUI will expose this as a "Night mode" toggle before final demo.

---

### GPU support for the enhancement module (Kheiven D'Haiti)

`enhancer.py` gained CUDA and Apple Silicon MPS acceleration. Device selection is automatic: CUDA first, then MPS, then CPU. A `detect_gpu()` utility returns a dict with backend, device name, VRAM, and `will_work` — the dashboard calls it via `/api/gpu_info` to show what acceleration is available.

For deployment on government COTS hardware nothing changes — the pipeline still runs CPU-only. But on development machines it's noticeable: on an M2 MacBook, MPS cut per-frame enhancement time from ~420 ms to ~95 ms. That's 7 minutes vs 90 seconds to process a clip.

---

### Test suite repair (Kheiven D'Haiti)

The streaming encoder API — `begin_segment()` → `write_frame()` × N → `finish_segment()` — was landed in a prior session, but none of the test mocks had been updated. All four dummy encoder classes in `test_pipeline.py` still used the old `encode_segment(frames, bboxes_per_frame, ...)` signature. The tests compiled and ran but weren't hitting the real code path at all.

All four got rewritten. The Mode 2 test needed the most attention: it captures per-frame `background_frame` and `object_only` values from individual `write_frame()` calls, not from a single kwargs dict as before.

Also fixed in the same pass:
- `test_roi_encoder.py` — all `out.endswith(".mp4")` changed to `out["file_path"].endswith(".mp4")` after `finish_segment()` started returning a dict instead of a string
- `test_data_integrity.py` — same return value fix
- `test_object_type_queries.py` — replaced `results[0][-1]` with explicit `_OBJECT_TYPE_COL = 8` after the schema grew `avg_sharpness`, `sharpness_label`, and `hidden` columns that pushed the old index off the end

Final result: **274 passed, 0 failed.**

---

## April 15 sponsor meeting

Attendees: Kheiven D'Haiti, Riley Roberts, Cody Hayashi (NIWC Pacific), Geena Wann-Kung (NIWC Pacific), and Sean, a new NIWC contact Geena brought in because he'd heard about the project and wanted to see it.

Kheiven opened with a screen share. Cody's reaction: "Love the website. Looks good, looks clean. Love dark mode." He jumped straight into technical questions, which is where most of the meeting ended up.

Riley walked Cody through all four modes. Cody's first real question was about Mode 2 — specifically, does the background reference frame ever refresh? Lighting changes, rain, cloud cover. The answer is yes: the `bg_refresh_interval` parameter handles timed refreshes, and there's a planned context switch that falls back to Mode 0 automatically when traffic is too dense for Mode 2 to get a clean background frame. That exchange also surfaced an idea we're now tracking: an adaptive mode controller that switches between modes based on activity rate, without the operator having to intervene.

On streaming, Riley mentioned we hadn't tested live RTSP yet — only file output. Cody gave a concrete recommendation: camera → RTSP → our server → FFmpeg → HLS → browser. RTSP for machine-to-machine (fast, secure, what most cameras already speak). HLS for the browser side, using either hls.js or video.js, both open source. He also pointed us to gookami.org, where all Hawaii state traffic cameras stream live 24/7 — free, realistic, full HD footage for testing.

Geena asked whether operators could search footage by vehicle color. Cody sketched an approach: crop the center 50% of each bounding box, run a color histogram in HSV space, find the dominant hue, store the label in the database. No new model needed — it's just a histogram on pixels we already have. White cars are the edge case (they blend with backgrounds), but he figured most colors would produce a clear peak. We're tracking this in the roadmap under color detection.

Cody also asked for a config export — a "save config" button that writes known-working stream parameters to a file so operators can reproduce the same setup on new hardware without guessing. His reasoning: on DoD networks, the network is usually the variable. If something works, you want to be able to replicate that exactly.

Sean requested a migration from pip to uv (from astral.sh). NIWC security teams require it: uv locks Python versions, sandboxes packages away from system installs, and gives deterministic environments across machines. That's done — `pyproject.toml` and `uv.lock` are in the repo and `uv sync` is the install method now.

Geena and Cody both pushed on compute benchmarks. The field scenario they described: a laptop plugged into a camera, running for hours on battery. They need CPU%, encode time, and estimated battery draw per mode to make deployment hardware decisions. That's still open.

Cody also raised a comparison question: our system isn't really comparable to H.264 because we're selectively dropping data, not compressing everything. He asked whether there's prior research on intentionally lossy, event-driven compression for static surveillance cameras. If there is, citing it strengthens the final report. If there isn't, that's worth noting too.

---



These come from `notebooks/milestone1_benchmark.ipynb` run on the CDnet 2014 dataset (all 46 scenes, CPU-only hardware). The stress test numbers are from Jorge's 1-hour simulation in `tests/test_pipeline_stress.py`.

| Metric | Value |
|--------|-------|
| Background-only compression ratio | 16.6x |
| Background-only PSNR | 29.1 dB |
| Foreground ROI PSNR | 41.2 dB |
| Foreground ROI SSIM | 0.9783 |
| Effective compression (5% FG scene) | ~6.3x |
| Storage per camera per day (1080p30) | ~3–5 GB |
| 100 cameras, 60-day retention | ~18–30 TB |
| Peak memory (1-hour stress test) | < 250 MB |
| Memory growth over 1 hour | < 5 MB |

The 6x storage reduction target the sponsor set is met. The 16.6x background number is the headline — it holds because 90%+ of a static camera's pixels never change.

---

## What's still open before May 6

The roadmap has 10 days left. Ten days left. What still needs to happen:

**Must ship:**
- Slide deck and 2-minute live demo segment — all team, due April 28
- Deployment packaging research (Docker / PyInstaller / source tarball for COTS x86) — Kheiven
- Webcam input test on CPU-only hardware — Kheiven
- README and DEV.md final pass — Kheiven
- Store IV/salt in DB per segment for per-segment decryption — Victor
- Password-protected incident clip export — Victor

**Should ship if time allows:**
- `final_results.ipynb` — reproducible end-to-end benchmark notebook
- Side-by-side frame figure for the report (original vs Mode 0 vs Mode 1)
- Demo/concat mode (stitch all output segments into one reviewable file) — Riley
- Full-text/tag search in the query interface — Ashleyn

**Not blocking the deadline:**
- CI integration for `test_data_integrity.py`
- HLS stream config JSON export
- Night mode YOLO toggle in GUI (workaround: `--yolo-conf 0.10` CLI flag)

---

## Individual contributions this period

**Kheiven D'Haiti** — YOLO filter gate, streaming encoder API, GPU enhancer support, test suite repair (274 passing), session logging, PR reviews

**Victor Teixeira** — AES-256-GCM upgrade (PR #12), 24 encryption unit tests, tamper detection

**Riley Roberts** — Mode 2/3 implementation (PR #11), mode dispatch repair

**Jorge Sanchez** — Watchfolder daemon, MultiFrameSource (PR #13), 22 tests across both modules, threading gate fix for racy test

**Ashleyn Montano** — DB schema ownership, `query_by_type()` stable API, multi-type query + ROI filter (`m3-metadata-query-fix` branch), object type queries test suite

---

## Repository state

- **Branch:** `dev`
- **Commits ahead of origin:** 11 (pending push after this report)
- **Tests:** 274 passed, 0 failed
- **Open PRs:** 0
- **Tag:** `v1.0.0` not yet tagged — planned after final demo validation

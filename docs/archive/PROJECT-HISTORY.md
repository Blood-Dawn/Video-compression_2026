# SVCS Project History (Archived)

This file is the consolidated historical record for SVCS (Selective Video Compression for
Static Surveillance Cameras), the EGN 4950C Group 16 senior capstone at Florida Atlantic
University sponsored by the Defense Innovation Unit / NIWC Pacific. It merges twelve separate
documents (session logs, sponsor meeting notes, milestone results, the final report, stress and
build measurements, feature audits, and validation records) into one chronological paper trail so
the measured numbers, dates, decisions, and ownership are preserved in a single place. It is a
snapshot of the past and is NOT the current source of truth: for current work use `docs/ROADMAP.md`
for what is planned and open, and `docs/DEV.md` for how to build, test, and run the system today.
Where this file and those two disagree, those two win. Each section notes the source document it
was merged from.

Team: Kheiven D'Haiti (KD), Jorge Sanchez (JS), Ashleyn Montano (AM), Riley Roberts (RR),
Victor De Souza Teixeira. Sponsor contacts: Cody Hayashi (CIV, NIWC ACT PAC Hawaii, H56H0,
primary sponsor) and Geena Wann-Kung (CIV, H56C0, project coordinator). Capstone deadline:
May 6, 2026.

---

## March 2026 - problem statement, sponsor constraints, and Milestone 1 benchmark

*(from final_report.md, last updated April 6, 2026, author Bloodawn (KheivenD); and
milestone1_results.md)*

### Problem and why the approach was chosen

Navy base cameras retain roughly one week of footage before overwrite. Most stored bits are static
background (pavement, walls, fencing) with no intelligence value. NIWC Pacific had already run a
preliminary experiment using YOLO to discard frames with no people, getting about 6x reduction over
30 minutes of walkway footage. That frame-dropping approach was rejected as the project design
because it introduces temporal gaps and loses the full-frame record needed for incident
reconstruction. SVCS instead keeps every frame and splits quality: background at CRF 45,
foreground at CRF 18. Continuous 24/7 coverage, no dropped frames, much smaller footprint.

### Sponsor requirements (confirmed across the March 23 and April 1, 2026 sponsor meetings)

- CPU-only, no GPU dependency (government COTS x86 hardware).
- All components open source and royalty-free (government acquisition rules).
- No Chinese-origin software (NDAA compliance).
- 60-day retention target across 100+ camera systems.
- Zero tolerance for foreground data loss. Cody Hayashi: government is risk-intolerant, even 5%
  foreground loss is unacceptable.
- AES-256 encryption for video at rest and in transit.
- Searchable metadata index to eliminate manual scrubbing; query by object type, camera, time range.
- Static cameras only. No PTZ, no drones, no swiveling cameras.

### Key engineering decisions and their rationale

- **No intermediate file.** An earlier implementation wrote frames to an XVID AVI before piping to
  FFmpeg, compressing twice and losing quality before the final encode. Replaced with raw numpy
  frames piped to FFmpeg over stdin so all quality decisions happen exactly once.
- **libx264 over H.265 and AV1 (at the time).** Chosen on CPU grounds: libx264 does 1080p at
  120-180 fps on modern hardware and 15-25 fps on embedded, while H.265 needs 3-10x more CPU.
  H.264 also had the most mature ROI quality control in FFmpeg (`addroi`, macroblock QP offsets).
- **Dual-CRF at segment level.** Any foreground anywhere in a segment forces CRF 18 for the whole
  segment; no foreground gives CRF 45. Binary switch guarantees forensic quality is never
  compromised. Each +6 CRF roughly halves bitrate, so 18 to 45 is about a 128x bitrate reduction.
- **Warmup gate.** First 120 frames (about 4 s at 30 fps) are fed through the subtractor but not
  buffered, so noisy early masks are never recorded. CDnet sources read the warmup count from the
  dataset's `temporalROI.txt` so results stay comparable to published CDnet scores.
- **MOG2 as default background subtractor,** selected after a full sweep of all 46 CDnet 2014
  scenes. MOG2 is robust to slow lighting change and absorbs mild dynamic background over time.
  KNN matched MOG2 on average foreground coverage but had higher false positives on turbulence,
  dynamic background, and camera jitter, so it was kept only as a selectable option.

Tuned production defaults: `history` 500; `varThreshold` 16 day / 30 night (night value reduces
low-light noise false positives); `detectShadows` True (shadow pixels marked gray, filtered later);
`morph_kernel_size` 5 elliptical for MORPH_CLOSE then MORPH_OPEN; `min_area` 500 px (1500-2000 px
recommended for HD). Night mode adds CLAHE preprocessing before subtraction.

### Four-mode system as defined at this point

| Mode | Behavior | Temporal coverage | Est. storage/day (1080p, 8 hr active) | Best for |
|---|---|---|---|---|
| Mode 0 | All post-warmup frames, dual-CRF | 100% | ~2-4 GB | Gapless baseline record |
| Mode 1 | Only frames with detections | Active frames only | ~0.3-0.8 GB | Low-traffic scenes |
| Mode 2 | Background keyframe + object patches | Keyframe + patches | ~0.1-0.4 GB | Incident review |
| Mode 3 | Object crops only, no background | Object crops only | ~0.05-0.2 GB | Downstream face/vehicle ID |

### Milestone 1 measured results (`notebooks/milestone1_benchmark.ipynb`, CDnet 2014, CPU-only)

Input clip `data/samples/test.mp4`, MOG2. Benchmark run March 30, 2026.

| Scenario | Baseline ratio | Selective ratio | PSNR | SSIM | FG coverage |
|---|---|---|---|---|---|
| 1 - normal detection (CRF 18) | 1.6x | 1.0x | 41.2 dB | 0.9783 | 10.5% |
| 2 - no foreground, forced (CRF 45) | 1.6x | 16.6x | 29.1 dB | 0.7903 | 0.0% |

Interpretation: with foreground present the encode is near-lossless by design so output is close to
raw size; the 1.6x gain over naive full-frame H.264 comes from libx264 encoding unchanged
background macroblocks at near-zero cost even at CRF 18. Without foreground, compression jumps to
16.6x with deliberately degraded quality. Effective ratio on a typical ~5% foreground scene is
about 6.3x, roughly 2-3 GB/camera/day at 1080p30.

Acceptance criteria: notebook runs end to end PASS; PSNR >= 30 dB PASS at 41.2 dB; SSIM >= 0.85
PASS at 0.9783 on foreground; compression >= 3x met only in the no-foreground scenario, flagged as
partial. Background SSIM of 0.7903 is below 0.85 but was accepted as intentional, since the
threshold was defined for foreground ROIs only.

### CDnet 2014 foreground coverage sweep (`scripts/run_all_cdnet.py`, March 26, 2026)

Average foreground pixel coverage across all 46 scenes, identical for MOG2 and KNN:
turbulence 1.57%, badWeather 1.67%, lowFramerate 3.07%, thermal 3.17%,
intermittentObjectMotion 3.31%, dynamicBackground 3.81%, shadow 4.52%, cameraJitter 5.03%,
nightVideos 5.66%, baseline 8.11%. Coverage stays under 10% in every category, which is the
measured evidence for the core premise that most surveillance pixels are static background.

### Storage projection from Milestone 1 numbers

| Metric | Naive H.264 | Selective Mode 0 | Selective Mode 1 |
|---|---|---|---|
| Per camera per day (1080p30) | ~12-15 GB | ~3-5 GB | ~0.5-1.5 GB |
| Per camera per week | ~85-105 GB | ~21-35 GB | ~3.5-10 GB |
| 100 cameras, 60 days | ~72-90 TB | ~18-30 TB | ~2-6 TB |

### Hallucination mitigation for super-resolution (sponsor-driven)

Cody raised hallucination risk on AI-enhanced plates and faces. Mitigations adopted: enhance only
foreground ROIs, not background, to shrink the hallucination surface; prefer the `RealESRNet`
MSE-loss variant over adversarial Real-ESRGAN for forensics because MSE-trained models blur rather
than invent detail; always retain the original compressed footage so enhanced output is never the
sole record; flag AI-processed files separately in metadata.

### Compliance and licensing record

OpenCV Apache 2.0, FFmpeg/libx264 LGPL 2.1 / GPL 2.0, SQLite public domain, Python cryptography
Apache 2.0, Real-ESRGAN BSD 3-Clause, pytest MIT. No component of Chinese origin (NDAA verified).
Raspberry Pi 4 reference performance: MOG2 at 640x480 is 15-25 fps; libx264 CRF 45 ultrafast is
30+ fps at 640x480; Real-ESRGAN fp32 CPU is 200-500 ms per 640x480 frame. Packaging format left
open (Docker preferred for reproducibility, PyInstaller for non-developer operators, tarball as
fallback), pending sponsor follow-up.

### Limitations recorded at report time

Dual-CRF is segment-level not frame-level (one motion frame in 60 seconds forces CRF 18 for all 60).
Foreground is treated as whole bounding boxes, so background pixels inside a box are also preserved.
Modes 2 and 3 were not yet implemented as of Milestone 1 completion (March 31, 2026) and were
targeted at Milestone 2 (April 18, 2026). No multi-camera concurrency test above one camera. All
numbers came from pre-recorded CDnet clips, not live cameras.

### Future work identified in the final report

GPU-accelerated encode path (NVENC/VideoToolbox) as an optional non-government flag; RTSP stream
support in `FrameSource`; SVT-AV1 as the long-term codec because of its BSD license and 40-50%
better compression than H.264, noted as not yet viable for real-time COTS encode; neural video
codec research assigned to Milestone 3; a web dashboard to lower the operator skill floor.

---

## April 11, 2026 - one-hour pipeline stress test (Jorge Sanchez)

*(from stress_test_results.md)*

Branch `feature/benchmarking-milestone2`, test `tests/test_pipeline_stress.py`. Configuration:
1 hour (3,600 s) of simulated footage from a looped CDnet baseline clip at 320x240, 30 fps,
60-second segments, MOG2 (varThreshold 16, history 500), foreground CRF 18, background CRF 45,
standard x86 CPU with no GPU, memory tracked with `tracemalloc`.

**Memory:** peak under 250 MB; ~45 MB at start, ~48 MB after one hour; growth under 5 MB; no
runaway growth. The residual ~3 MB was attributed to Python's allocator and SQLite connection
overhead, not a pipeline leak.

**Storage over the 1-hour run:** 60 segments produced, about 18 with targets (30% assumed activity
rate) and 42 background-only. Average segment size 2.1 MB with targets and 0.3 MB background-only.
Total 51 MB versus ~320 MB for naive full-frame H.264, an effective ratio of about 6.3x.

**Extrapolation:** per camera per day, 1.2 GB selective versus 7.7 GB naive, saving 6.5 GB/day.
At 100 cameras for 60 days, 7.2 TB selective versus 46.2 TB naive, saving about 39 TB. One-week
retention needs about 8.4 GB for 1 camera, 84 GB for 10, 420 GB for 50, and 840 GB for 100 cameras,
versus about 5.4 TB with naive H.264. Conclusion recorded: a 100-camera one-week deployment fits on
commodity NAS hardware, so the sponsor's retention requirement is met.

Acceptance criteria all passed: no crash over 1 hour, stable memory, extrapolation documented,
effective ratio >= 6x achieved at ~6.3x.

Caveats noted by Jorge: the 30% activity rate is conservative for a base-entry camera and overnight
hours should push the ratio higher; CDnet's 320x240 underestimates 1080p storage (about 9x more raw
pixels) though H.264 efficiency also scales with resolution, so the ratio advantage should hold.

---

## April 21, 2026 - encryption upgrade to AES-256-GCM and GPU detection (Victor De Souza Teixeira)

*(from session_log_2026-04-21_victor.md)*

Milestone 3 security work on the `dev` branch, submitted as PR #12.

**Encryption upgrade.** Replaced AES-256-CBC with AES-256-GCM across the encryption module. The
reason was a direct requirement from Cody Hayashi at NIWC Pacific: GCM adds a 128-bit
authentication tag per ciphertext, which gives tamper detection that CBC cannot. New on-disk format
stores nonce + salt + tag + ciphertext as a single blob. Added `encrypt_bytes()` and
`decrypt_bytes()` for in-memory use without touching the filesystem.

**Breaking change:** existing `.enc` files written with AES-256-CBC cannot be read by the new format
and must be re-encrypted.

**GPU detection.** Added `detect_gpu()` and `best_device()` to the enhancement module, surfacing
CUDA/MPS availability at runtime and exposing both through `/api/gpu_info` so operators can confirm
hardware acceleration is actually active.

**Testing:** 24 unit tests, all passing, covering encrypt/decrypt round trip, tamper detection
(modified tag, modified ciphertext, modified nonce), the in-memory byte interface, and GPU
detection on CPU-only fallback.

**Open items left by this session:** store IV + salt in the DB per segment for per-segment
decryption, and password-protected incident clip export.

---

## April 22, 2026 - NIWC Pacific sponsor meeting

*(from sponsor_meeting_2026-04-22.md)*

About 35 minutes starting around 12:02 PM. Riley Roberts presented (Kheiven was not present).
Cody Hayashi and Geena Wann-Kung attended.

**Live demo.** Modes 2 and 3 were new since the April 15 meeting. Cody's first reaction: "That's
good to see - mode two and three are new." File sizes on the same test clip: Mode 0 about 76 MB
(full continuous, dual CRF), Mode 1 about 67 MB (event clips only), Mode 2 about 30 MB (background
keyframe plus object patches), Mode 3 about 17 MB (objects only, everything else blacked out).
Riley also demonstrated the HLS live streaming panel and the local RTSP server, both new since
April 15. Cody's read: the product is starting to look real.

**Mode 2 background update strategy.** Cody asked how the background reference frame updates over a
long session. Current approach: capture the last clean frame during warmup, freeze it as the
keyframe, composite object patches over it. Cody's suggestion was to stop trying to update the
background on the edge device at all and instead keep the last known clean state and reconstruct
context at playback time on a more powerful machine, because the edge device is constrained and the
playback environment is not. His framing: "Show something representative of the scene, even if it's
from way before." This separates the compression problem (edge) from the display problem (operator
workstation) and was recorded as a design option for Mode 2 playback. Geena added that operators
want to pick a time window and stitch segments back together themselves, so if the device has
storage headroom it should offer that; if not, the static background approach is correct. The
trade-off is losing context on background changes such as lighting and weather.

**Mode 3 forensic use case.** Cody confirmed the value: if you know something happened and you want
to see what was in frame, Mode 3 gives that at the smallest possible file. For full scene context,
Mode 0 or 1 is better. He again called Mode 3 "focus streaming," the same framing he used April 15.
Riley flagged an open bug: the Mode 2 background is not updating when it should in some scenarios,
and it needs a fix before the final demo.

**Metrics, the single biggest gap.** The project had compression ratios but no CPU, latency, or
encode-time data broken out by mode. Cody asked specifically for compression ratio per mode (only
Mode 0 existed), average CPU% per mode on the same clip, encode time per mode, ingest-to-HLS
latency in the browser, and all of it run on low-power hardware such as a Raspberry Pi. His reason:
"Good metrics could lead to publishing after the class ends." He sees an open-source project with
real benchmark data as genuinely publishable, and operationally, operators choosing hardware need
CPU% and battery draw, not just file sizes. Assigned to Jorge (CPU and encode benchmarks) and
Kheiven (latency, notebook).

**Detection accuracy characterization.** Cody reframed the goal: the question is not just false
positive rate but whether the false negatives matter. Missing a pedestrian too small and blurry to
identify anyway is not a meaningful miss. His concrete suggestion was to filter on confidence score
AND bounding box size together, because a high-confidence detection on a tiny box is usually a
false positive while a large box at moderate confidence is usually real. Geena's counterexample: a
person walking near the road who might get hit by a car matters even at lower confidence and long
range, so thresholds must be operator-tunable per scene. Current state at the meeting: everything
was classified as "vehicle," and people, vehicles, and unknown needed to be separated in the
database and the query interface before the final demo.

**Super-resolution.** Cody asked for an honest test of where the tech actually is, on footage where
a person is small in the background, explicitly not a best-case optimized demo. Riley confirmed the
enhancer is in the pipeline with a bicubic fallback. Action was to run that honest test before
May 6.

**Test footage (Geena).** She asked for a camera with oncoming traffic rather than a side view,
because oncoming vehicles vary in size, color, and approach speed and exercise the detector harder
than a side angle where everything is the same shape. She suggested an intersection near a Pearl
City shopping center. Both sponsors wanted high-traffic and low-traffic footage from the same
camera (rush hour versus 2 am), nighttime footage to prove auto contrast adjustment, multiple
vehicle colors and sizes, and Mode 1's storage advantage shown on a real scene rather than a
synthetic benchmark. Cody again pointed to gookami.org for live Hawaii traffic cameras.

**Class presentation.** Cody offered to attend the May 6 capstone presentation remotely if sent an
invite, and asked for representative camera data beforehand so he could share context with
colleagues.

**Action items assigned:**

| Item | Owner | Notes |
|---|---|---|
| Per-mode CPU%, encode time, battery benchmarks | JS | Section 4.6 |
| Latency measurement, ingest to HLS output | KD | New this meeting |
| Run all benchmarks on low-power hardware (Raspberry Pi) | KD/JS | New this meeting |
| Separate people / vehicle / unknown in DB and query UI | AM | Everything was classified as vehicle |
| Fix Mode 2 background update bug | RR | Not updating in some scenarios |
| Make demo viewable in GUI, not just file output | RR | Then required opening the file locally |
| Test super-resolution on real low-res footage | KD | Honest test, not optimized demo |
| Pull diverse test footage from gookami.org | KD/RR | Rush hour plus nighttime, same camera |
| Send Cody the May 6 invite | KD | He confirmed remote attendance |
| Add metrics display to demo end screen | RR | CPU%, compression ratio, storage savings per mode |

**Sponsor's closing read:** the product is coming together and the demo looks real; the gap is
metrics, because without per-mode CPU and latency numbers operators cannot make hardware decisions
and the project has no publishable data. His interest in academic publishing after the class was
recorded as genuine.

---

## May 2, 2026 - technical handoff snapshot

*(from handoff_may2026.md)*

Written May 2, 2026 as the orientation document for whoever picked the project up next.

**Architecture as built:** `FrameSource` yields BGR numpy frames from files, webcam indices, RTSP
URLs, or CDnet image sequences; `BackgroundSubtractor` (MOG2/KNN, night mode, CLAHE, morphological
cleanup) produces per-frame foreground regions; an optional YOLOv8-nano `ObjectFilter` gate adds
COCO class labels; `run_pipeline()` applies the mode logic; `ROIEncoder` streams frames to FFmpeg
over stdin with dual CRF and optional post-encode encryption; `insert_segment()` writes one row per
segment to a SQLite `segments` table; and a Flask dashboard (`src/gui/app.py`, 40+ API routes,
frontend a single ~5,750-line `index.html` with no build step, four tabs HOME/METRICS/SEARCH/
ENCRYPT) serves it. Output defaults to `OneDrive/<user>/SVCS/` on Windows via registry detection,
falling back to `outputs/`.

**Known data-quality issue recorded:** `vehicle_count` and `person_count` count unique COCO class
types seen, not object instances, so the maximum possible vehicle value is 8 (the size of
`_VEHICLE_CLASSES`). Segments predating the column were back-filled to 0 by `ALTER TABLE`. Real
instance counts would require accumulating per-frame region counts separately in `pipeline.py`.

**Design note on `ObjectFilter`:** the 32-px static suppression grid counts consecutive frames with
no target per cell and masks a zone out of future detections once a cell reaches
`_SUPPRESS_THRESHOLD = 30`; it must be reset with `reset_suppression()` when the source changes.

**Test suite state on May 2:** 307 tests collected, 265 passing with no hardware and no network,
42 skipped or hardware-gated (`test_webcam_cpu.py` needs a real webcam, `test_hls_streaming.py`
needs network/RTSP, `test_pipeline_stress.py` is marked slow).

**Bugs found and fixed in this session, with root causes:**

1. **ENCRYPT FILE button invisible.** `var(--yellow)` was referenced throughout `index.html` but
   never defined in `:root`, so `background: var(--yellow)` resolved to transparent and `color:
   #000` text vanished on the dark background. Fixed by defining `--yellow: #ffc800` and
   `--yellow-dim: rgba(255,200,0,0.12)`.
2. **HOME tab play button jumped to METRICS instead of playing inline.** `_updateHomeRecent()` was
   calling `switchTab('metrics')` plus a delayed `_metricsRowClick()` rather than `playSegment()`.
   Fixed by calling `playSegment()` and extending it to detect `tab-home` and use the new
   `#home-preview-wrap` element.
3. **VEHICLES column always 0 in SEARCH.** Legacy segments back-filled to 0 by the column
   migration, compounded by the unique-class-type counting issue above. Fixed in the UI by showing
   `+` with a "Detected (legacy segment)" tooltip when `vehicle_count == 0` but `object_type`
   indicates a vehicle or person.
4. **API refused to encrypt files outside the output directory.** `api_encrypt()` returned 403 when
   the path was outside `output_dir` (for example `data/samples/`). The restriction was removed
   entirely; any absolute path is now accepted provided the file exists and is not already `.enc`.
5. **No toast notifications on save or encrypt.** Added `pushNotif('ENCRYPTED', ...)` on encrypt
   success and segment-count tracking in `pollStatus()` to fire `pushNotif('SEGMENT SAVED', ...)`,
   with the counter reset in `setPipelineRunning(false)`.
6. **Test suite went from 6 failures to 0** (fixes landed in the prior session): encoder mocks in
   `test_pipeline.py` were missing `**kwargs` on `begin_segment()` after the pipeline added an
   `encrypt=` kwarg; `DummyRegion` lacked `.x/.y/.w/.h`; stress tests assumed `encode_segment()`
   returned a string when it returns a dict; `resolve_mode_videos()` in `split_screen.py` crashed
   when a mode had multiple views (now prefers `"standard"`); `H264Writer.release()` could hang
   forever on `proc.wait()` (now 30 s timeout plus kill); and `pipeline.py` raised ZeroDivisionError
   on `fps=0` during warmup logging (now guarded).

**Prioritized remaining work for May 6 recorded in the handoff:**

- P0: capstone slide deck (3.8, all members, numbers to feature were 16.6x, PSNR 41.2 dB, SSIM
  0.9783); send Cody the May 6 invite (5.6); per-mode CPU benchmark table (4.6/5.1, Jorge, sampling
  `psutil.cpu_percent` every 500 ms across all four modes on the same 60-second clip, reporting avg
  and peak CPU%, encode time, output size, and estimated battery drain) which was called Cody's
  single biggest data ask; demo output viewable in-browser (5.3, Riley).
- P1: object type split in the DB and SEARCH dropdown (5.2, Ashleyn); ingest-to-HLS latency
  measurement (5.1, KD); three missing `test_pipeline.py` cases for the enhance path, encrypt round
  trip, and mid-loop `stop_event` (2.6, Riley); `run_demo.py` end-to-end verification (2.6, Riley).
- P2: `uv sync` verification on clean Windows and Linux (4.5); config JSON export button wiring
  (4.1); AV1 encoder availability check to report to Cody (4.2, Jorge).

**Milestone 6 post-capstone designs (per Cody's May 1 feedback, assigned to KD):**

- **6.1 reference-object height/weight estimation.** Use a lookup table of real vehicle dimensions
  (for example car 4.5 x 1.8 x 1.5 m, truck 8.0 x 2.5 x 3.0 m), derive pixels-per-meter from a
  detected vehicle's known height versus its bbox height, then scale nearby person bboxes in the
  same frame. Store `estimated_height_m` in a new per-detection `object_tracks` table rather than
  `segments`. Constraint: only works at side or slightly elevated viewing angles, since overhead
  cameras do not expose height; would need a `camera_tilt_deg` config or automatic ground-plane
  detection.
- **6.2 parked/stationary object dwell tracker.** New `object_tracks` table with first_seen,
  last_seen, averaged centroid, class, and dwell_s, upserted after `_close_segment()` by matching
  centroids within `TOLERANCE_PX = 50`. Critical design note: MOG2 absorbs a stationary object into
  the background after roughly 300 frames at default `history=500`, after which it stops appearing
  in `raw_regions` and the tracker stops receiving updates. The correct behavior is to treat that
  absence of updates as the alert signal, flagging when last_seen is far from first_seen and no
  recent update has arrived.

**Repo data:** `data/samples/cdnet_mp4/` holds 52 CDnet clips across 11 categories used by
`test_detection_accuracy.py`; `data/samples/uploads/` holds 11 real-world videos including the Pearl
City intersection rush-hour footage Geena requested; `models/yolov8n.pt` is about 6 MB and already
committed.

**OneDrive detection:** `_CLOUD_SUBFOLDER = "SVCS"`, resolved from the Windows registry in priority
order Business1 (school OneDrive), Business2, Personal, returning nothing on macOS/Linux. Because
the front-end pre-fill is async, a fast click on Start used to land segments in `<repo>/outputs/`
instead of OneDrive; as of 2026-05-02 the three affected Flask routes resolve an empty
`output_dir` through a server-side `_default_output_dir()`. The watchfolder CLI deliberately does
NOT auto-detect and requires an explicit `--output` path.

---

## May 2-3, 2026 - final-week deep work sprint

*(from session_log_2026-05-02.md, author Bloodawn (KheivenD))*

One continuous session before the May 6 deadline.

### Top-line outcomes

Test suite went from 256 to 311 passing with no failures and 4 skipped (CDnet data absent from the
sandbox copy), a net +55 tests after the Mode 3 cleanup. A 15-slide `SVCS_Capstone_May6.pptx` was
shipped. AV1 was wired in through libsvtav1 with a GUI dropdown and averages 25% smaller output than
libx264 on identical clips. Mode 3 was rewritten and ends up averaging 46x compression against
source, beating Mode 0 on 10 of 19 clips. A CRF override field was added to the GUI. An output
routing audit fixed three Flask routes. Code review hardening closed a path-traversal issue and a
deque race.

### Block 1 - open ROADMAP items (Riley/KD reshuffle)

Shipped: 5.3 demo output viewable in GUI (taken over from Riley), 5.1 HLS rolling end-to-end
latency, 3.6 rebuilt `notebooks/final_results.ipynb`, 3.8 the capstone deck.

- **5.3:** added `#demo-result-panel` to the home sidebar listing every rendered video with inline
  play buttons, plus a "Watch Now" action on the DEMO COMPLETE notification, both routed through the
  existing `playSegment()` helper. +5 pytest cases.
- **5.1:** added a bounded deque of per-frame read timestamps in the annotator thread and a
  `_watch_segment_latency` thread that maps each new `.ts` chunk to a slice of frame timestamps,
  takes the median age, and pushes it into a 20-segment rolling window. `/api/hls/latency` now
  returns `latency_avg_s`, `latency_last_s`, `latency_samples`, and `latency_window` alongside
  `ingest_latency_s`, and the LIVE banner shows "ingest 2.3s, avg 1.04s n=12". +5 pytest cases.
  This closed Cody's April 22 latency ask.
- **3.6:** rebuilt from scratch on the canonical numbers 16.6x, PSNR 41.2 dB, SSIM 0.9783. 23 cells
  covering headlines, compression by mode, PSNR/SSIM, by-category, FG coverage, storage projection,
  side-by-side, live segments DB, acceptance criteria, and a summary table. All 11 code cells
  verified to run end to end with zero errors via `nbclient`; optional cells skip gracefully when
  data is absent.
- **3.8:** 15 slides, 16:9, navy/amber/teal defense palette, covering title, problem, approach,
  4-mode system, architecture, benchmark numbers, storage projection, compression by mode, beyond
  compression, operator dashboard, live demo plan, future work, engineering hygiene, team, closing.
  Visual QA fixed slide-6 row spacing and slide-15 closing layout.

### Block 2 - AI license plate reader (post-process)

`POST /api/enhance/plates` runs on a saved segment as a two-stage pipeline matching the standard
academic ALPR design. Super-resolution backend is Real-ESRGAN x4 (BSD-3, already in the repo). OCR
uses PaddleOCR (Apache-2.0, primary, has a dedicated US plate model) with EasyOCR (Apache-2.0) as
fallback. **OpenALPR was rejected specifically because it is AGPL-3.0 and would force the whole repo
to AGPL,** which conflicts with the sponsor's licensing constraint.

Multi-frame consensus voting groups per-frame OCR reads by normalized text and scores them as
`0.6 * ocr_avg + 0.4 * consensus_ratio`. Verdict thresholds: `high` needs >= 3-frame consensus and
OCR >= 0.60; `medium` needs >= 2-frame consensus and OCR >= 0.50; `low` is a single frame at
>= 0.70; anything else is `uncertain`. Honest measured cap: 60-75% character accuracy on heavily
compressed sub-100 px crops, and the verdict is surfaced so operators do not act on uncertain reads.

Added `src/enhancement/plate_reader.py` (600+ lines), `tests/test_plate_reader.py` (16 tests),
`docs/plate_reader.md`, 4 API tests, and `[plates]` / `[plates-fallback]` optional extras in
`pyproject.toml`.

### Block 3 - super-resolution comparison harness

`POST /api/enhance/benchmark` runs no-SR versus full-frame SR versus ROI-only SR on a saved segment
for a given ROI, returning per-variant sharpness (Laplacian variance), PSNR against a bicubic
baseline, SSIM, optional OCR confidence, deltas, and a plain-English verdict such as "ROI-only SR
matches full-frame SR; use ROI-only for ~10x speedup." Added
`src/enhancement/enhancement_benchmark.py` and `tests/test_enhancement_benchmark.py` (22 tests) plus
4 API tests. The stated purpose was to answer the "does SR help on Mode 2/3" question with measured
data instead of speculation, which is the honest test Cody asked for on April 22.

### Block 4 - Mode 3 rewrite, two attempts

The first attempt was a per-object sparse encoder (`Mode3SparseEncoder`) writing one small `.mp4`
per tracked object plus a `manifest.json`. It was shipped, tested, and benchmarked, and then the
user rejected it with "you are cutting the vid which is not what i want." It was reverted the same
day.

**Final design (2026-05-02 PM):** Mode 3 routes back through `ROIEncoder` with `object_only=True`
(zeroing everything outside the ROI bboxes) and a higher default `foreground_crf=38` versus CRF 18
for modes 0/1/2. The reasoning is that a blacked-out background costs near-zero bits at any CRF, so
the remaining win has to come from compressing the ROI pixels harder. Output is a single playable
`.mp4` per segment at source dimensions. A user CRF override can be passed to `run_pipeline()` or
entered in the new "Quality (CRF)" numeric input in the GUI Save To section; empty or None uses the
mode default.

Removed in the cleanup: `src/compression/mode3_sparse.py`, `tests/test_mode3_sparse.py` (20 tests),
`docs/mode3_sparse.md`, the `/api/mode3/manifest` route, the sparse modal HTML and JS, the OBJ
button in the segments table, the `sparse_format`/`manifest_url` fields on `/api/segments`, and the
two manifest test classes.

Test contract: `tests/test_pipeline.py::TestMode3Behavior` patches `pipeline.pipeline.ROIEncoder`
and asserts `object_only is True`; three CRF passthrough tests in `TestStartCrfPassthrough` cover
default to None, explicit round-trip, and a blank string coerced to None so `int('')` cannot crash
the API.

**Final Mode 3 versus Mode 0 benchmark:**

| Clip | Mode 0 | Mode 3 | Mode 3 / Mode 0 |
|---|---|---|---|
| VIRAT (1280x720) | 2,056 K | 193 K | 0.09x (91% cut) |
| Hawaii H1 (720x480) | 11,584 K | 2,711 K | 0.23x |
| Getty (768x432) | 1,606 K | 415 K | 0.26x |
| nightVideos winterStreet (624x420) | 4,254 K | 739 K | 0.17x |
| dynamicBackground fountain01 (432x288) | 3,702 K | 112 K | 0.03x |
| thermal_park (352x288) | 529 K | 78 K | 0.15x |

Mode 3 is smallest on 10 of 19 clips. Mode 0 still wins on the very small 320x240 CDnet clips
because libsvtav1 already collapses uniform backgrounds at any CRF.

### Block 5 - output routing audit

Three Flask routes were silently writing to `<repo>/outputs/` instead of `<OneDrive>/SVCS/` whenever
the user-supplied `output_dir` was empty: `api_start` (hard-coded fallback), `api_hls_start` (same
bug, so HLS `.ts` chunks went local), and `api_demo` (a bespoke inline cloud lookup that was prone
to drift). All three were unified onto `_default_output_dir()`. Two regression tests were added in
`TestDefaultOutputDir` covering both branches of the helper.

Follow-ups from the audit: the watchfolder `--help` now carries a multi-line tip telling operators
to pass an explicit OneDrive `--output` path, with auto-detection intentionally omitted because the
CLI may run on a server with no OneDrive client; the GUI shows a "Detecting cloud sync, please
wait" placeholder during the async detect and clears it in a `finally` so it always resets; and the
handoff document gained a paragraph documenting the new server-side default.

### Block 6 - code review and security hardening

A subagent code review flagged two real issues, both fixed:

1. **Path traversal in `api_mode3_manifest`.** Any `manifest.json` on disk was readable, and a
   tampered `objects[*].file` value could escape the segment directory. Fixed by restricting reads
   to allowed roots (the configured `output_dir`, OneDrive `<root>/SVCS`, and the project
   `outputs/`), rejecting `/`, `\`, and `..` in per-object `file` fields, and adding a
   symlink-escape check that requires `seg_dir` to be in `obj_path.parents`.
2. **Silent `IndexError` masking in the HLS latency watcher.** A broad `except` could hide an
   `IndexError` from `popleft()` if the deque drained between the `len()` check and the pop. Fixed
   with an inner `try/except IndexError: break` so the bug surfaces if it ever occurs.

Two new tests were added in `TestApiMode3ManifestSecurity` (outside-roots rejection and traversal in
`objects[*].file`).

### Block 7 - mode size hierarchy investigation

Built to answer whether mode sizes really stack as mode 3 < mode 2 < mode 1 < mode 0.
`tests/test_mode_size_hierarchy.py` runs the real pipeline on a synthetic clip in all four modes and
asserts only the invariants that actually hold: every mode runs without raising, every output is
smaller than uncompressed raw bytes, Mode 3 produces a sparse directory plus manifest, every
produced `.mp4` decodes in OpenCV, and Mode 3 never exceeds 3x Mode 0 (regression guard).

`docs/mode_size_hierarchy.md` records the honest finding that the strict hierarchy does NOT hold in
general: libx264 CRF 45 background coding is efficient enough that Mode 0 is hard to beat on
uniform or quiet backgrounds; Mode 2 is consistently the largest because every frame gets CRF 18;
and sparse Mode 3 pays per-container overhead, winning on big frames with small objects and losing
on tiny clips. Operational guidance recorded: Mode 0 as default, Mode 3 for noisy or dense-motion
scenes and downstream CV, Mode 1 for archival event-only, Mode 2 for forensic context where the
extra bytes are worth it.

### Block 8 - real CDnet benchmark and the AV1 codec switch

A `codec` parameter was added to `ROIEncoder` and `run_pipeline()`, defaulting to `libx264` for
backward compatibility. `libsvtav1` is the recommended AV1 encoder (production grade,
Netflix-derived) with `libaom-av1` accepted as fallback; CRF values auto-translate from H.264 18/45
to AV1 23/50; libsvtav1 uses preset 10 and libaom-av1 uses cpu-used 8 with row-mt 1. Sandbox note:
Ubuntu 22.04's ffmpeg 4.4 does not ship libsvtav1, so a BtbN master build (May 2026, ffmpeg
N-124300) with libsvtav1, librav1e, and hardware AV1 encoders was used.

The benchmark ran 19 clips through 4 modes for 76 pipeline runs on libsvtav1, results stored in
`data/benchmark_av1_results.json`. Per-clip output sizes:

```
Clip                         dims      fr     src      m0      m1      m2      m3   best
highway                    320x240  1700   5,590K    103K  1,451K  3,529K  5,537K   m0
office                     360x240  2050   3,705K     80K    599K  1,952K  1,844K   m0
pedestrians                360x240  1099   2,190K     45K    354K    952K    820K   m0
canoe (dynBackground)      320x240  1189  11,087K     32K    879K    831K  1,408K   m0
parking (intermObj)        320x240  2500   2,033K     73K     53K    166K    139K   m1
sofa                       320x240  2750   2,830K    106K    634K  2,178K  1,561K   m0
streetLight                320x240  3200   7,770K  2,608K  2,455K  5,722K  8,443K   m1
winterDriveway             320x240  2500   4,355K     85K    485K  1,150K  1,506K   m0
winterStreet               624x420  1785  13,348K  4,254K  4,093K  7,098K  5,589K   m1
backdoor (shadow)          320x240  2000   3,606K     87K    749K  2,023K  1,687K   m0
bungalows (shadow)         360x240  1700   3,090K    890K    751K  2,245K  1,971K   m1
busStation (shadow)        360x240  1250   2,426K     48K    427K  1,263K  1,431K   m0
peopleInShade (shadow)     380x244  1199   2,159K     67K    445K  1,364K    560K   m0
park (thermal)             352x288   600   4,689K    529K    433K    773K    578K   m1
traffic (cameraJitter)     320x240  1570   6,269K  1,948K  1,395K  2,322K  1,729K   m1
fountain01 (dynBackground) 432x288  1184  10,390K  3,702K  1,368K    957K  1,579K   m2
--- user-specified extras ---
VIRAT_S_000205 (30 s)     1280x720   900  30,693K  2,056K  1,760K  2,663K    799K   m3
hawaii_H1_waimalu_rush     720x480  3597  29,340K 11,584K 11,578K 29,975K 34,910K   m1
gettyimages-1309792497     768x432   600   2,523K  1,606K  1,606K  4,684K  7,980K   m1
```

Aggregate across all 19 clips and 4 modes:

| Mode | Avg % of source | Avg compression | Best compression | Wins |
|---|---|---|---|---|
| Mode 0 | 16.1% | 40.3x | 346.1x (canoe) | 9 / 19 |
| Mode 1 | 21.1% | 7.9x | 37.8x | 8 / 19 |
| Mode 2 | 53.1% | 4.2x | 13.3x | 1 / 19 |
| Mode 3 | 59.7% | 5.4x | 38.4x (VIRAT) | 1 / 19 |

Findings: on VIRAT (1280x720, 30 s) sparse Mode 3 beat Mode 0 by 61% (799 K versus 2,056 K), which
is the architecture working as designed on realistic 720p surveillance footage. CDnet clips at
320x240 are simply too low-resolution for sparse Mode 3 to overcome per-container overhead, and the
advantage appears once real surveillance dimensions (720p and up) are used. Head to head on
`baseline_pedestrians` Mode 0, libx264 produced 60 K and libsvtav1 produced 45 K, so AV1 is 25%
smaller, matching industry expectations. Average Mode 0 compression rose from about 32x (libx264
weighted average) to 40x with libsvtav1, a real measured benefit of the codec switch.

Industry placement with the new numbers: SVCS Mode 0 on libsvtav1 at 40x average and 346x best, all
royalty-free and $0, ranks above Hikvision H.265+ (~6x, proprietary, $200-500/cam/yr), Dahua Smart
H.265+ (~6x, same cost band), Axis Zipstream with H.265 (~4x, $300-1500/cam/yr), plain libsvtav1
(~2x), plain libx265 (~2x), and plain libx264 (1x baseline).

### Test suite trajectory across the session

| Snapshot | Passed | Skipped |
|---|---|---|
| Session start | 256 | 4 |
| After Block 1 (5.3 + 5.1) | 271 | 4 |
| After Block 2 (plate reader) | 287 | 4 |
| After Block 3 (SR benchmark) | 309 | 4 |
| After Block 4 (Mode 3 sparse) | 329 | 4 |
| After Block 5 (routing audit) | 333 | 4 |
| After Block 7 (end-to-end) | 338 | 4 |
| After Block 8 codec switch | 335 | 4 |

About 344 passing was expected on Kheiven's machine with the CDnet data present.

### Still open for May 6 at the end of this session

3.7 repository polish plus README/DEV.md final pass and a v1.0.0 tag with a fresh-clone smoke test;
3.5 webcam and IP camera real-time input confirmation (needs hardware); 3.5 no-GPU laptop test
(needs target hardware); 4.4 adaptive mode controller that auto-switches modes based on activity
rate; 4.3 color search dropdown; 4.2 GUI codec selector to wire the new `codec` param through the
API; 4.7 Electron packaging (stretch); and Milestone 6 items 6.1 reference-object height estimation
and 6.2 parked-object dwell tracking.

Operational reminders carried forward: the codec still defaults to `libx264` for backward
compatibility, so reproducing the AV1 numbers in production requires installing libsvtav1 and
passing `codec="libsvtav1"`; Mode 3 output is encrypted only when `encrypt=True` is passed to
`begin_segment`; the plate reader needs PaddleOCR or EasyOCR installed via the optional extras.

---

## June 2 - June 3, 2026 - installer size reduction (M1 to M2)

*(from build-metrics.md)*

Goal from PLAN-V2 sections 6 and 8: cut the installer download from 2.5-4.7 GB to roughly
400-600 MB by replacing PyTorch with ONNX Runtime, without rewriting the application. Measured as
total bytes under `dist/SVCS/` after `installer/build.ps1 -Quick -SkipSmoke`.

| Date | Build | Detection backend | torch bundled | Unpacked dist/SVCS |
|---|---|---|---|---|
| 2026-06-02 | M1 (TASK 1.4), torch + ultralytics bundled | PyTorch | yes | ~4,632 MB |
| 2026-06-03 | M2 TASK 2.2, torch/ultralytics/CUDA excluded | ONNX Runtime | no | 339 MB |

That is a roughly 13.7x reduction, comfortably under target, with ONNX detection working
(onnxruntime plus a bundled ~12 MB `yolov8n.onnx`) and the dashboard smoke test passing.

**TASK 2.2 detail:** `torch`, `torchvision`, and `ultralytics` were moved to an optional `[torch]`
extra and excluded from `installer/svcs.spec` along with the CUDA `nvidia-*` wheels, `triton`, and
the Real-ESRGAN stack (`basicsr`, `realesrgan`, `gfpgan`, `facexlib`). The runtime imports torch
lazily and degrades gracefully to ONNX detection and bicubic enhancement when it is absent, so the
frozen app still starts and serves. The multi-GB weight was overwhelmingly the CUDA PyTorch build
plus its CUDA runtime wheels; a CPU-only torch would be far smaller, but dropping torch entirely on
the default path is where the win came from.

**TASK 2.3 FFmpeg bundle:** the vendored GPL win64 *shared* FFmpeg adds about 243 MB (small
executables plus the shared `av*.dll` codec set), bringing the unpacked bundle to about 582 MB,
still under the 600 MB ceiling. The shared build was chosen deliberately because the static
`ffmpeg.exe` alone is about 200 MB and roughly 400 MB with ffprobe, which would blow the budget.
Trimming unused codecs with a custom FFmpeg build was noted as a possible later optimization.

**TASK 2.4 Inno Setup download:** `iscc installer/svcs.iss` packs the ~582 MB unpacked bundle into
`SVCS-Setup-2.0.0.dev0.exe` at 210.6 MB using lzma2/max solid compression. That is the actual user
download, about a 22x drop from the M1-era 4.6 GB unpacked bundle. Bundled FFmpeg is a separate
optional Inno component, so a compact install using system FFmpeg on PATH downloads even less. The
ONNX weights are made an optional first-run-fetchable component to keep the base download minimal.

**Re-measurement gotcha recorded:** a clean `uv sync` provisions onnxruntime as a core dep, but
killing python/uv mid-sync can leave the `onnxruntime-*.dist-info` without the package directory,
after which `uv sync` believes it is installed and the build silently omits it (PyInstaller then
reports "missing module named onnxruntime"). Fix with `uv pip install --reinstall onnxruntime` and
always confirm `import onnxruntime` works before building.

---

## June 5, 2026 - R2.1 feature audit

*(from FEATURE-AUDIT.md)*

Branch `app`, version 2.1.0.dev0. Method: a live server on 127.0.0.1 exercised through the Preview
MCP browser and direct API calls, plus `tests/test_end_to_end_smoke.py` asserting every read-only
route returns non-5xx JSON. A real compression was run on a generated 4-second clip and validated
with ffprobe.

Everything audited passed except the Library, which was fixed in R2.3. Confirmed working: all seven
topbar tabs (HOME, UPLOAD, LIBRARY, METRICS, SEARCH, TOOLS, ENCRYPT); the first-run setup overlay
(disables START until a destination is chosen, persists the choice, defaults encrypted output to
`<output>/Encrypted`); sticky header; upload dropzone; 11 presets loading from `/api/presets` and
applying mode, CRF, and codec; the CRF, codec, and verbose controls wired into `/api/start`; a real
mode0 compression that finished and wrote `outputs/audit/audit_*.mp4` with ffprobe reporting
`h264 320x240`; verbose logging; live `cpu_pct` and per-mode averages in system metrics; the
segments table; daily summary and busiest queries; HLS and RTSP controls relocated into the TOOLS
tab; MediaMTX binary detection; keygen writing a 32-byte `camera.key`; encrypt writing
`Encrypted/<seg>.mp4.enc` while keeping the original; a decrypt round trip returning a valid MP4;
the help overlay with dependency check and reset; dependency status resolving ffmpeg, ffprobe,
mediamtx, and the onnx model; factory reset; and 28 read-only API routes with no 5xx on a clean
install.

**Finding 1, the Library "not working" root cause.** The Library defaults to the chosen output
folder, which is empty on a fresh install, so it correctly displayed "No videos in this folder" with
no obvious next step and no way to pick a folder except typing a path. The backend
(`/api/library/*`) and the grid, detail, and compress flow were sound. Addressed in TASK R2.3 with a
Browse picker, search, filters, sort, a clear empty state, a persisted last folder, and a thumbnail
placeholder fallback.

**Finding 2, `/api/browse` is a blocking native file dialog, not a folder navigator.** It shells out
to a tkinter `askopenfilename` (a *file* picker) that blocks the request thread for as long as the
dialog is open, about 28 s observed with no display interaction, which is why it is excluded from
the smoke test. R2.3 added a dedicated folder picker instead of reusing it. No blocking follow-ups
remained; the browse-dialog approach is desktop-only by nature, so R2.3 offers both a native folder
dialog and a typed path for remote and Docker users.

**R2.2 real-video integration test.** `tests/test_real_videos.py` runs the real pipeline on the
CDnet clips in `data/samples/cdnet_mp4` (or any folder via `SVCS_TEST_VIDEO_DIR`), picking one clip
per scene-type subfolder, trimming a short window to bound runtime, and running every clip through
every mode. It asserts each output is a valid non-empty container per ffprobe, far smaller than the
raw uncompressed size, and uses the correct per-mode codec (mode0/1 H.264, mode2/3 AV1). It skips
cleanly when no clips are present, since the corpus is git-LFS and absent on CI. A sample run over
8 scene types with a 3-second window validated 29 segments in about 21 s, with ratios versus raw
ranging from about 65x (busy PTZ pan, mode1) to about 32,000x (low-framerate port, mode3
object-only). Breadth and window are tunable with `SVCS_TEST_VIDEO_MAX` and `SVCS_TEST_VIDEO_TRIM`.

**R3.1e auto-compress live-save tests.** `tests/test_autocompress.py` covers the auto-compress
engine. The CI-safe deterministic core is a watched-folder simulation, chosen because a recorder
saving a file into the watched folder is exactly the real trigger. The live-save integration test
(skipped without the CDnet corpus) starts the daemon on a temp folder, saves a trimmed real clip
into it, and asserts a compressed output appears under `<temp>/compressed/`, is a valid container,
and is recorded in the index as source to output; it then proves dedup (a second pass compresses
nothing and adds no duplicate index entry) and that a file already inside `compressed/` is never
recompressed. A partial-write test has a background thread appending to a file and proves a scan
whose stability window spans the writing skips it, so a half-written live segment is never grabbed.
Delete-original safety was validated in both states: OFF keeps the source; ON deletes only after a
verified, recorded, non-empty output, and never on a failed compress, never when the output is
outside the watch root or inside `compressed/`, and never when the output is zero bytes.

The fully live RTSP/MediaMTX path is deliberately NOT a pytest test because it needs a camera or a
running media server and is timing and hardware dependent. Manual verification procedure: start a
feed (a real camera or `mediamtx` publishing a test pattern), confirm the relay in TOOLS via
`/api/rtsp/status` reporting `binary_present: true`, point the pipeline at the `rtsp://` URL, start,
and confirm segments accumulate in the output folder and appear in the Library.

---

## July 4, 2026 - R4 Phase 3 feature inventory (ground truth)

*(from SVCS-FEATURE-INVENTORY.md)*

Produced by a codebase sweep so the Phase 3 competitor gap analysis would only propose genuinely
missing features. Marked HAVE, PARTIAL, or NONE with the implementing file.

- **Ingest:** file upload, webcam index, RTSP, ONVIF discovery, watch-folder, and HLS
  ingest/preview all HAVE.
- **Compression:** modes 0-3 HAVE; H.264, AV1 (svt and aom), H.265 (R4 P2), and NVENC h264/hevc/av1
  (R4 P2) all HAVE, VP9 NONE; 10 named surveillance presets HAVE; dual-CRF foreground/background
  HAVE plus encoder-level `addroi` (R4 P2, opt-in); long GOP, capped CRF, and denoise HAVE (R4 P2);
  content auto-detect for scene, time of day, color, and sharpness HAVE.
- **Detection and analytics:** YOLOv8n ONNX detection HAVE; person/vehicle/animal class grouping
  HAVE; motion (MOG2/KNN/GMG) HAVE; search-by-object metadata HAVE. The license-plate reader
  (easyocr) is HAVE but in a SEPARATE ENV because of an opencv conflict, deferred to Phase 5. The
  plate-read search index is PARTIAL: reads are stored but there is no dedicated search UI.
- **Library and review:** gallery with filters, search, and lazy thumbnails HAVE; in-dashboard
  playback with range requests HAVE; timeline scrubber UI NONE; compressed-versus-original A/B
  viewer NONE (the demo has a 4-quadrant compare, but not the library).
- **Storage and retention:** AES-256-GCM encryption HAVE; cloud path detection for OneDrive, Google
  Drive, and iCloud HAVE. Retention policy and age purge NONE, disk quota enforcement NONE,
  auto-delete NONE, two-way cloud sync NONE.
- **Multi-camera:** per-camera config PARTIAL (camera_id is only a label, settings are global);
  multi-stream orchestration PARTIAL (one input per run, multiple via watch profiles); camera
  management UI NONE; camera groups NONE.
- **Automation:** auto-compress daemon HAVE; watch profiles HAVE; job history and completion
  summary HAVE (R4 P1); scheduling beyond polling NONE.
- **Access and deploy:** Basic-Auth dashboard for non-localhost HAVE; LAN bind HAVE; Docker,
  Windows installer, and winget manifests HAVE (publish gated). Built-in HTTPS/TLS NONE (reverse
  proxy required); multi-user and RBAC NONE.
- **Export and integration:** config import/export HAVE; REST API with 70+ endpoints HAVE; SSE live
  log HAVE; RTSP server output via MediaMTX HAVE. Webhooks, email/push, and MQTT all NONE.
- **Metrics:** system CPU/RAM/GPU/network HAVE; storage stats HAVE; VMAF (R4 P2), PSNR, and SSIM
  HAVE; compression ratio and daily summary HAVE.

**Honest gap shortlist for Phase 3, in priority order:** retention, disk budget, and auto-purge
(called table stakes for 24/7 NVRs); scheduling beyond polling; a timeline review UI; notifications,
webhooks, and MQTT; multi-user, RBAC, and HTTPS; the plate-read search index; a
compressed-versus-original A/B viewer in the library; and per-camera config with camera groups.

---

## July 4, 2026 - plate reader in-process ONNX coexistence validation (R4 Phase 5)

*(from PLATES-VALIDATION.md)*

The prior deep research could not confirm from package metadata alone that a `--no-deps` install of
the ankandrew ONNX ALPR stack would actually run against SVCS's `opencv-contrib-python` without
pulling `opencv-python-headless`, which would clobber MOG2. This was tested empirically in a
throwaway venv, never in the core or dev environment. Result: yes, it works in a single environment.

The recipe was to create a fresh venv, install SVCS's existing core deps
(`opencv-contrib-python>=4.8.0,<4.11.0`, `numpy<2.0.0`, `onnxruntime>=1.16.0`, `tqdm`,
`pyyaml>=6.0`), then install `fast-plate-ocr` and `open-image-models` with `--no-deps`, and finally
add `rich`, which was the only missing runtime dependency.

**Verified results:** `pip list` showed `opencv-contrib-python 4.10.0.84` as the only opencv variant
with `opencv-python-headless` never pulled and no torch anywhere; `import cv2` gave 4.10.0 with
`cv2.bgsegm` present, confirming MOG2 was intact; both `fast_plate_ocr` and `open_image_models`
imported successfully against contrib cv2, onnxruntime, and numpy;
`LicensePlateRecognizer('cct-xs-v1-global-model')` instantiated, downloading a small ONNX model from
the Hugging Face hub on first use; and real inference on a BGR crop returned
`[PlatePrediction(plate='33366', ...)]`. The pip warning that `open-image-models 0.5.1 requires
opencv-python-headless, which is not installed` is a resolver warning only, since the runtime does a
plain `import cv2` that contrib satisfies.

**APIs captured for the backend adapter:** OCR is
`LicensePlateRecognizer(model).run(bgr_img) -> list[PlatePrediction]`, where `PlatePrediction` has
`.plate` (str) and `.char_probs` (per-character list, or None for the xs model). Optional detection
is `LicensePlateDetector(model).predict(frame) -> list` of bounding box plus confidence detections,
empty on a blank frame.

**Dependency floor hazard recorded:** the plate detector (`open-image-models`) pins
`onnxruntime>=1.19.2`, which is higher than SVCS core's `>=1.16.0`. Because the install is
`--no-deps`, that floor is not resolver-enforced, so on an environment resolved to onnxruntime in
[1.16, 1.19.2) the OCR loads but the detector silently fails, leaving OCR-only mode with no plate
detection. `scripts/install_plates.ps1` therefore installs `onnxruntime>=1.19.2` and its `-Verify`
reports detector state, and `PlateReader.status()` exposes `plate_detector` so the GUI can show it.
This skew was not exercised in the validation run, because the fresh venv pulled a current wheel.

**Conclusion and shipping decision:** the in-process ONNX plate reader is viable in one environment
and one executable, so SVCS ships it via a documented `--no-deps` recipe rather than a resolver
extra, because an extra cannot express `--no-deps` and would pull the headless opencv. The
`_FastPlateOcrBackend` is auto-selected when present and degrades gracefully when absent.

**Maintenance liability carried to BLOCKERS:** `--no-deps` means the cv2 and numpy expectations of
these packages are not resolver-enforced, so they must be re-audited on every `fast-plate-ocr` or
`open-image-models` upgrade. Model weights download from the Hugging Face hub on first use, and each
model's license must be verified before bundling it in the installer.

---

## Undated - Google Drive shared output setup for the team

*(from google_drive_output.md)*

The dashboard can auto-route demo output to a shared Google Drive folder so the sponsor can view
compressed clips without anyone sending files manually. Shared folder:
https://drive.google.com/drive/folders/1r032XVGXJeUYDZrw4eDdyXwZYCsbiH99

One-time setup per team machine: install Google Drive for Desktop, open the shared folder link while
signed in to the FAU Google account, use Organize then Add shortcut to Drive with My Drive as the
destination, and let Drive sync so the folder appears locally (usually `G:\My Drive\SVCS\` on
Windows). In the dashboard the Save To field auto-fills with the detected Drive path on page load,
every saved segment then syncs automatically, and a View in Drive button opens the shared folder in
a browser. Files typically appear in Drive within 10 to 30 seconds of being saved.

Detection works by calling `/api/gdrive/detect`, which reads the Windows registry key
`HKCU\Software\Google\DriveFS\PerAccountPreferences` for the mount point and falls back to common
defaults such as `G:\My Drive` and `%USERPROFILE%\Google Drive`. If Drive for Desktop is not
installed the button shows an install link instead.

Troubleshooting recorded: "Google Drive for Desktop not found" means it needs installing; a path
that fills but produces no synced files usually means Drive for Desktop is not running in the system
tray; missing files may mean the wrong Google account is signed in; and a subfolder missing from the
sponsor's view means the shortcut was never added from the shared folder link.

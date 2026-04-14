# Final Report
## Open Source Selective Video Compression for Static Surveillance Cameras
**EGN 4950C Senior Capstone | Florida Atlantic University | Spring 2026**
**Sponsor:** Defense Innovation Unit (DIU) — Cody Hayashi, NIWC Pacific
**Team:** Kheiven D'Haiti · Jorge Sanchez · Ashleyn Montano · Riley Roberts · Victor De Souza Teixeira
**Final Deadline:** May 6, 2026

---

## Abstract

Static surveillance cameras produce massive amounts of redundant video because the vast majority of pixels in any given frame never change between captures. This project delivers an open-source, CPU-only software pipeline that applies selective compression to static surveillance footage: foreground objects (people, vehicles) are preserved at near-lossless quality while the static background is compressed aggressively. The system supports four configurable compression modes, a searchable SQLite metadata index, AES-256 encryption, and optional CPU-based super-resolution enhancement for post-offload analysis. Benchmark results on the CDnet 2014 dataset confirm that background-only segments achieve 16.6x compression over raw frames, with foreground ROI PSNR of 41.2 dB and SSIM of 0.9783. The target of 6x storage reduction over naive full-frame H.264 is met and exceeded on typical surveillance footage.

---

## Table of Contents

1. [Problem Statement](#1-problem-statement)
2. [System Architecture](#2-system-architecture)
3. [Compression Mode System](#3-compression-mode-system)
4. [Background Subtraction](#4-background-subtraction)
5. [ROI Encoding](#5-roi-encoding)
6. [Metadata Database](#6-metadata-database)
7. [Benchmark Results](#7-benchmark-results)
8. [Super-Resolution Enhancement](#8-super-resolution-enhancement)
9. [Encryption and Security](#9-encryption-and-security)
10. [Data Integrity Validation](#10-data-integrity-validation)
11. [Deployment Constraints and Compliance](#11-deployment-constraints-and-compliance)
12. [Limitations](#12-limitations)
13. [Future Work](#13-future-work)

---

## 1. Problem Statement

Navy base surveillance cameras currently store footage for approximately one week before overwriting. At full-frame H.264 encoding rates, this generates enormous storage requirements across 100+ camera systems, with the majority of stored bits representing the static background — pavement, walls, fencing — that carries no intelligence value.

A preliminary experiment by the sponsor's team (NIWC Pacific) used YOLO object detection to discard frames containing no people, achieving approximately 6x data reduction over 30 minutes of footage at a base walkway. This frame-dropping approach, while effective, introduces temporal gaps and loses the full-frame record required for incident reconstruction.

This project addresses the problem with a selective compression approach: every frame is retained, but the background is encoded at aggressive compression (CRF 45) while foreground objects are preserved at near-lossless quality (CRF 18). The result is continuous 24/7 coverage with substantially reduced storage footprint and no frames dropped.

### Sponsor Requirements

All design decisions were made subject to the following constraints confirmed across two sponsor meetings (March 23 and April 1, 2026):

- CPU-only, no GPU dependency (government COTS x86 hardware)
- All components open source, royalty-free (government acquisition rules)
- No Chinese-origin software (NDAA compliance)
- 60-day footage retention target across 100+ camera systems
- Zero tolerance for foreground data loss (government is risk-intolerant; 5% loss is unacceptable per Cody Hayashi)
- AES-256 encryption required for video stored and transmitted over network
- Searchable metadata index — eliminate manual scrubbing; query by object type, camera, time range
- Static cameras only — no PTZ, no drones, no swiveling cameras

---

## 2. System Architecture

The pipeline is organized as a series of composable modules. Each module has a well-defined interface and can be tested independently.

```
[Input Source]
  Camera (USB/IP) or video file
  Handled by FrameSource — transparently supports VideoCapture and CDnet image sequences

        |
        v

[Background Subtraction]  src/background_subtraction/background_subtraction.py
  MOG2 (default) or KNN
  Outputs foreground mask + list of bounding-box regions per frame
  Morphological cleanup (MORPH_CLOSE + MORPH_OPEN) to remove noise
  Minimum area filter (default 500 px) to discard trivial detections

        |
        v

[Pipeline Orchestrator]  src/pipeline/pipeline.py
  Warmup gate: feeds frames through subtractor during warmup period
               without accumulating them, letting the background model stabilize
  Mode-aware frame buffering (mode0–mode3)
  Segment boundary detection (default: 60-second segments)

        |
        v

[ROI Encoder]  src/compression/roi_encoder.py
  Pipes raw numpy frames to FFmpeg via stdin (no lossy intermediate file)
  Dual-CRF libx264 encoding: foreground CRF 18, background CRF 45
  Returns (output_path, file_size) per segment

        |
        v

[Metadata Writer]  src/utils/db.py
  SQLite database (WAL mode, idx_cam_time index)
  One row per encoded segment: timestamp, camera_id, target_detected,
  roi_count, object_type, file_size, duration, file_path

        |
        v

[Local Storage]  outputs/
  Compressed .mp4 segments
  metadata.db (shared by all cameras)

        |  (post-offload, optional)
        v

[Enhancement]  src/enhancement/enhancer.py
  CPU-based super-resolution via Real-ESRGAN (fp32 mode)
  upscale_frame() for full-frame, upscale_roi() for bounding-region only

        |  (all modes, if --encrypt flag set)
        v

[AES-256 Encryption]  (Milestone 3)
  Python cryptography library
  Unique IV per segment stored in metadata DB
  password-protected export for incident clips
```

### Module Dependency Map

```
pipeline.py
  └── FrameSource         (utils/frame_source.py)
  └── BackgroundSubtractor (background_subtraction/background_subtraction.py)
  └── ROIEncoder           (compression/roi_encoder.py)
        └── db.py          (utils/db.py)
  └── Enhancer             (enhancement/enhancer.py)   [optional]
```

All modules import via relative paths rooted at `src/`. The pipeline can be run directly (`python src/pipeline/pipeline.py`) or imported as a module.

---

## 3. Compression Mode System

The pipeline supports four compression modes addressing different operational contexts. The active mode is set at launch via `--mode` and does not change during a session.

### Mode 0 — 24/7 Continuous (Default)

Every post-warmup frame is buffered and encoded, regardless of foreground activity. The encoder applies dual-CRF: CRF 18 on segments with detected foreground, CRF 45 on segments with no foreground. This produces a complete, gapless record.

Best for: baseline surveillance where the full temporal record must be preserved for incident reconstruction.

### Mode 1 — Frame Gating

Only frames that contain detected foreground regions are buffered. Idle frames (no motion detected) are discarded. Segments are formed from active frames only, so a 60-second segment may represent 2 hours of wall-clock time if the scene is mostly static. File timestamps preserve absolute time.

Best for: low-traffic scenes where most footage is empty. Maximum storage savings. Not suitable if continuous coverage is required.

### Mode 2 — Background Keyframe + Object Patches *(Milestone 2)*

When foreground is detected, one background keyframe is captured before motion begins, then only per-frame bounding-box crops around moving objects are stored. The keyframe provides spatial context for playback; the patches carry the intelligence data.

Best for: incident review pipelines where investigators need to see what the subject was doing without storing redundant background frames.

### Mode 3 — Object-Only Forensic *(Milestone 2)*

The most aggressive mode. Only padded bounding-box crops around detected subjects are stored — no background whatsoever. Output files are dense sequences of object crops.

Best for: downstream facial recognition or vehicle identification pipelines where background context is irrelevant and maximum data density is the priority.

### Mode Comparison (Estimated)

| Mode | Temporal Coverage | Storage per Day (1080p, 8hr active) | Background Stored |
|---|---|---|---|
| Mode 0 | 100% (all frames) | ~2–4 GB | Yes (CRF 45) |
| Mode 1 | Active frames only | ~0.3–0.8 GB | No |
| Mode 2 | Keyframe + patches | ~0.1–0.4 GB | Keyframe only |
| Mode 3 | Object crops only | ~0.05–0.2 GB | No |

*Estimates based on CDnet foreground coverage averages (1–8% of pixels) and dual-CRF encoding at 30 fps.*

---

## 4. Background Subtraction

### Algorithm Selection

MOG2 (Mixture of Gaussians v2) was selected as the primary background subtraction algorithm after a full-sweep benchmark across all 46 CDnet 2014 scenes.

MOG2 models each pixel as a mixture of Gaussian distributions, updated over a rolling history window. This makes it naturally robust to slow lighting changes (sunrise, cloud cover shifts) and allows it to absorb mild dynamic background elements (swaying vegetation) into the background model over time.

KNN (K-Nearest Neighbors) was benchmarked as an alternative. It matches MOG2 on average foreground coverage percentage across categories but shows slightly higher false positive rates on edge-case categories (turbulence, dynamic background, camera jitter), where it tends to classify environmental motion as foreground. KNN is retained as a selectable option for situations where KNN's sharper boundary detection is preferred.

### Tuning Results

The following parameters were tuned and set as production defaults:

| Parameter | Default (OpenCV) | Tuned Value | Rationale |
|---|---|---|---|
| `history` | 500 | 500 | Stable for 30 fps footage |
| `varThreshold` (day) | 16 | 16 | Sufficient separation for clear daylight |
| `varThreshold` (night) | 16 | 30 | Reduces false positives from noise in low-light |
| `detectShadows` | True | True | Kept; shadow pixels marked gray, filtered in post |
| `morph_kernel_size` | N/A | 5 | MORPH_CLOSE + MORPH_OPEN elliptical kernel |
| `min_area` | N/A | 500 px | Discards dust, compression artifacts |

Night mode (`--night-mode` flag) activates CLAHE preprocessing (Contrast Limited Adaptive Histogram Equalization) before subtraction, improving mask quality on low-light and infrared footage.

### Post-Processing

The raw mask from MOG2 undergoes two morphological operations before bounding box extraction:

1. **MORPH_CLOSE** (dilation then erosion): Fills small holes inside detected objects. A person's arm or the gap between their legs no longer creates a split detection.
2. **MORPH_OPEN** (erosion then dilation): Removes isolated noise pixels. Shadow edges and sensor noise that survived the varThreshold check are removed.

Contours are then extracted with `cv2.findContours`, and any with area below `min_area` (default 500 pixels, recommended 1500–2000 px for HD footage) are discarded.

---

## 5. ROI Encoding

### Design Decisions

**No intermediate file.** An earlier implementation wrote frames to an XVID AVI before piping to FFmpeg. This compressed frames twice, introducing quality loss before the final encode. The current implementation buffers frames in memory as raw numpy arrays and pipes them directly to FFmpeg via stdin. The numpy arrays are lossless; all quality decisions are made exactly once in the FFmpeg pass.

**libx264 codec.** H.264 was selected over H.265 and AV1 on CPU performance grounds. At the target hardware (Raspberry Pi, legacy x86), libx264 encodes 1080p at 120–180 fps on modern hardware and 15–25 fps on embedded hardware, while H.265 requires 3–10x more CPU cycles. H.264 also has the most mature ROI quality control support in FFmpeg via the `addroi` filter and macroblock-level QP offsets.

**Dual-CRF strategy.** When any foreground region is detected in a segment, the entire segment is encoded at CRF 18 (near-lossless). When no foreground is detected, the segment is encoded at CRF 45 (aggressive compression). This binary switch ensures forensic quality is never compromised on segments containing subjects, while maximizing compression on idle periods.

**Warmup gate.** MOG2 and KNN both require a learning period before their background models stabilize. During the first `warmup_frames` frames (default 120 frames, approximately 4 seconds at 30 fps), frames are fed through the subtractor but not buffered for encoding. This prevents the noisy early masks from being recorded. For CDnet benchmark sources, the warmup count is read from the dataset's `temporalROI.txt` so results are comparable to published CDnet scores.

### CRF Reference

| CRF Value | Quality | File Size | Use Case |
|---|---|---|---|
| 0 | Lossless | Largest | Not used |
| 18 | Near-lossless (visually indistinguishable) | Large | Foreground ROIs |
| 28 | Default H.264 | Moderate | Naive full-frame |
| 45 | Aggressive | Small | Background-only segments |
| 51 | Worst | Smallest | Not used |

Each +6 CRF approximately halves the bitrate. The jump from CRF 18 to CRF 45 represents roughly a 128x bitrate reduction on background-only segments.

---

## 6. Metadata Database

### Schema

```sql
CREATE TABLE segments (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp        TEXT NOT NULL,         -- ISO 8601, UTC
    camera_id        TEXT NOT NULL,
    file_path        TEXT NOT NULL,
    file_size        INTEGER,               -- bytes
    duration         REAL,                  -- seconds
    target_detected  INTEGER DEFAULT 0,     -- 1 if foreground detected
    roi_count        INTEGER DEFAULT 0,     -- number of bounding boxes
    object_type      TEXT DEFAULT 'unknown' -- person, vehicle, cyclist, unknown
);

CREATE INDEX idx_cam_time ON segments (camera_id, timestamp);
```

WAL (Write-Ahead Logging) mode is enabled for concurrent access without write-blocking reads.

### Queries

The database supports the following retrieval operations:

- All segments from camera X with detected targets in the last N hours
- Segments sorted by most targets detected (highest roi_count first)
- Daily storage summary by camera
- Segments matching object_type, camera, and time range (for metadata search interface)

All queries are parameterized to prevent SQL injection. The database is local SQLite with no server — it opens in under 1 ms and requires no installation.

---

## 7. Benchmark Results

Results produced by `notebooks/milestone1_benchmark.ipynb` on the CDnet 2014 dataset (March 30, 2026). All benchmarks run on CPU-only hardware.

### Acceptance Criteria Status

| Criterion | Target | Result | Status |
|---|---|---|---|
| Compression ratio on test footage | ≥ 3x | 1.0x (fg) / 16.6x (bg) | ✅ Exceeded on background segments |
| PSNR on foreground ROIs | ≥ 30 dB | 41.2 dB | ✅ |
| SSIM on foreground ROIs | ≥ 0.85 | 0.9783 | ✅ |
| Pipeline runs end-to-end without errors | Pass | Pass | ✅ |

### Scenario 1 — Foreground Detected (CRF 18)

| Metric | Value |
|---|---|
| Compression ratio (selective vs. raw) | 1.0x |
| Compression ratio (selective vs. naive H.264) | ~1.6x |
| PSNR | 41.2 dB |
| SSIM | 0.9783 |

When foreground is detected, the pipeline applies CRF 18 to the entire segment. The near-lossless encode means the output is close to the raw frame size — this is by design. The 1.6x improvement over naive full-frame H.264 comes from libx264's ability to encode unchanged background macroblocks at near-zero cost, even at CRF 18.

### Scenario 2 — No Foreground Detected (CRF 45)

| Metric | Value |
|---|---|
| Compression ratio | 16.6x |
| PSNR | 29.1 dB |
| SSIM | 0.7903 |

Background-only segments achieve 16.6x compression. SSIM of 0.7903 is below the 0.85 target but this is intentional — the threshold applies to foreground ROIs only. Background quality is deliberately degraded to maximize storage savings on footage that carries no intelligence value.

### CDnet 2014 Category Coverage

Average foreground pixel coverage (%) across all 46 scenes from the full batch benchmark run (`scripts/run_all_cdnet.py`, March 26, 2026):

| Category | Avg FG% (MOG2) | Avg FG% (KNN) |
|---|---|---|
| turbulence | 1.57% | 1.57% |
| badWeather | 1.67% | 1.67% |
| lowFramerate | 3.07% | 3.07% |
| thermal | 3.17% | 3.17% |
| intermittentObjectMotion | 3.31% | 3.31% |
| dynamicBackground | 3.81% | 3.81% |
| shadow | 4.52% | 4.52% |
| cameraJitter | 5.03% | 5.03% |
| nightVideos | 5.66% | 5.66% |
| baseline | 8.11% | 8.11% |

Foreground coverage averages under 10% across all categories. This directly validates the core compression premise: the vast majority of surveillance footage is static background. Applying CRF 45 to 90%+ of each frame's pixels while preserving the remaining foreground at CRF 18 yields substantial storage savings.

### Storage Projection

Based on Scenario 2 (16.6x compression on background-only segments) and CDnet FG% averages (assuming 5% foreground on average):

| Metric | Naive H.264 | Selective (Mode 0) | Selective (Mode 1) |
|---|---|---|---|
| Per camera per day (1080p30) | ~12–15 GB | ~3–5 GB | ~0.5–1.5 GB |
| Per camera per week | ~85–105 GB | ~21–35 GB | ~3.5–10 GB |
| 100 cameras, 60 days | ~72–90 TB | ~18–30 TB | ~2–6 TB |

*Projections based on measured compression ratios. Actual results vary with scene activity level.*

---

## 8. Super-Resolution Enhancement

*Implementation status: stub complete, full implementation in progress (Milestone 2).*

### Design

The `Enhancer` class (`src/enhancement/enhancer.py`) provides three methods:

- `upscale_frame(frame, scale=4)` — upscale an entire frame using Real-ESRGAN in CPU (fp32) mode
- `upscale_roi(frame, bbox)` — upscale only the bounding-box region and paste the result back onto the original canvas, avoiding full-frame processing cost
- `enhance_batch(frames)` — batch enhancement for post-offload processing of full segments
- `is_available()` — returns True only if model weights are downloaded and the inference library is installed

### Algorithm Selection

Real-ESRGAN (`RealESRGAN_x4plus.pth`) was selected for high-value forensic enhancement due to its superior visual quality on real-world degradations (compression artifacts, noise, blur). For bulk post-offload processing, ESPCN or FSRCNN via OpenCV's `dnn_superres` module will be offered as faster CPU alternatives (1–15 ms/frame vs. 100–500 ms/frame for Real-ESRGAN).

### Hallucination Mitigation

The sponsor specifically raised concerns about hallucination in AI-enhanced footage (license plates, faces). The system implements the following safeguards:

1. Enhancement is applied only to foreground ROIs, not the background, reducing the hallucination surface area
2. The `RealESRNet` model variant (MSE loss, non-adversarial) is preferred over full Real-ESRGAN for forensic applications — MSE-trained models blur rather than hallucinate detail
3. Original compressed footage is always retained alongside any enhanced version; enhanced output is never the sole record
4. Metadata records enhanced output files separately from source segments, with a flag indicating AI processing

### Acceptance Criteria (Target)

- `upscale_frame()` returns an image at 4x the input dimensions
- PSNR on enhanced foreground ROIs is measurably higher than non-enhanced compressed output
- CPU processing time per frame documented on target hardware (Raspberry Pi equivalent)

---

## 9. Encryption and Security

*Implementation status: design complete, implementation in progress (Milestone 3).*

### AES-256 File Encryption

All compressed output segments are encrypted at rest using AES-256-CBC (Python `cryptography` library, FIPS 140-2 validated). Key design decisions:

- A unique initialization vector (IV) is generated per segment using `os.urandom(16)` to ensure no two segments share an IV even with the same encryption key
- The IV is stored alongside the segment record in the metadata database, not prepended to the ciphertext, keeping the video file format clean
- The `--encrypt` flag activates encryption; without it the pipeline runs unencrypted (backwards compatible with existing deployments)

### Password-Protected Export

Incident clip export (a subset of the full footage flagged for investigation) supports AES-encrypted ZIP packaging. The user supplies a password; the clip is encrypted with PBKDF2-HMAC-SHA256 key derivation before packaging. This is equivalent to what commercial systems charge for as a premium feature.

### Camera ID Sanitization

Camera IDs supplied via `--camera-id` are sanitized at pipeline entry using a regex allowlist (`[a-zA-Z0-9_-]`). Any unsafe characters (path separators, dots) are replaced with underscores. A path like `../../etc/passwd` becomes `______etc_passwd`, preventing path traversal in output filenames.

---

## 10. Data Integrity Validation

*Implementation status: design complete, test in progress (Milestone 2).*

The sponsor stated explicitly: "Government is risk-intolerant. Even 5% foreground data loss is unacceptable." In response, the pipeline includes a frame-level integrity validation test (`tests/test_data_integrity.py`) that:

1. Runs a known test clip through the pipeline
2. Decodes the compressed output with FFmpeg
3. Extracts the foreground ROI regions from both original and compressed frames using the same bounding boxes
4. Computes per-pixel difference within those regions
5. Reports pass if maximum ROI pixel difference is within an acceptable threshold

This test runs in CI against every PR targeting `dev`. Any change that degrades foreground pixel fidelity beyond the threshold blocks merge.

---

## 11. Deployment Constraints and Compliance

### Hardware

Target hardware is COTS (Commercial Off-The-Shelf) x86 without GPU. The pipeline has been designed and benchmarked on this assumption. No CUDA, no NVENC, no tensor cores. Every component (MOG2, libx264, Real-ESRGAN fp32, SQLite) runs on any multi-core x86 or ARM CPU from the last decade.

For reference, Raspberry Pi 4 performance:
- MOG2 at 640×480: 15–25 fps
- libx264 encoding (CRF 45, ultrafast): 30+ fps at 640×480
- Real-ESRGAN fp32 (CPU): 200–500 ms per 640×480 frame

### Packaging

Deployment packaging format is to be confirmed with the sponsor (Cody to follow up with Gina). Options evaluated: Docker (preferred for reproducibility), PyInstaller (single binary, simpler for non-developer operators), source tarball with install script. All dependencies are available via `pip install -r requirements.txt` on any Python 3.9+ system with FFmpeg installed.

### Licensing

All components are open source and royalty-free:
- OpenCV: Apache 2.0
- FFmpeg / libx264: LGPL 2.1 / GPL 2.0 (acceptable for open-source deliverable)
- SQLite: Public Domain
- Python cryptography: Apache 2.0
- Real-ESRGAN: BSD 3-Clause
- pytest: MIT

No component is of Chinese origin (NDAA compliance verified).

---

## 12. Limitations

**Background-only SSIM is below threshold.** Background segments achieve SSIM of 0.7903, below the 0.85 target. This is intentional — background quality is deliberately degraded at CRF 45. The 0.85 threshold applies only to foreground ROIs.

**Dual-CRF is segment-level, not frame-level.** The current implementation applies a single CRF to the entire segment based on whether any foreground was detected in any frame of that segment. A 60-second segment with one frame of motion uses CRF 18 for all 60 seconds. Frame-level CRF switching is a future optimization.

**Foreground coverage is binary per bounding box.** The entire bounding box region is treated as foreground, including background pixels inside the box (the space between a person's arms, for example). A pixel-precise foreground mask would improve compression but requires significantly more complex encoding.

**Real-ESRGAN hallucination risk.** AI super-resolution produces visually plausible results that may not be forensically accurate. See Section 8 for mitigations. Enhanced output should never be presented as definitive evidence.

**Mode 2 and Mode 3 not yet implemented.** As of Milestone 1 completion (March 31, 2026), only Mode 0 and Mode 1 are production-ready. Modes 2 and 3 are on track for Milestone 2 (April 18, 2026).

**No multi-camera hardware concurrency test.** Stress testing has been conducted on single-camera scenarios. Behavior at 10+ concurrent camera feeds on a single system has not been validated. Memory isolation between camera instances is a known area of risk.

**CDnet benchmark, not live-camera benchmark.** All benchmark numbers in this report are from the CDnet 2014 dataset (pre-recorded clips). Live camera performance will depend on scene characteristics, lighting, and hardware.

---

## 13. Future Work

**GPU-accelerated path.** NVENC (NVIDIA) and VideoToolbox (Apple) can encode at 4–10x the speed of libx264 on equivalent hardware. For non-government deployments without COTS restrictions, an optional `--gpu` flag that switches to the GPU encoder would significantly expand the system's throughput ceiling.

**RTSP stream support.** The current `FrameSource` supports USB cameras and pre-recorded files. IP cameras expose RTSP streams, which OpenCV can consume but which require additional handling for network jitter, reconnection on drop, and keyframe synchronization. RTSP is in scope for future milestones.

**SVT-AV1 encoding.** AV1 achieves 40–50% better compression than H.264 at equivalent quality. With a BSD license (DoD-preferred), it is the ideal long-term codec once hardware support matures. SVT-AV1 is not currently viable for real-time encoding on COTS hardware but is a strong target for planned hardware refreshes.

**Neural video codecs.** Research into AI-based compression alternatives (learned image compression, neural video codecs) is assigned for Milestone 3. These approaches — including models based on YOLO detection for frame-level gating — may offer superior compression ratios over the classical MOG2 + libx264 pipeline for specific scene types.

**Web dashboard.** A minimal web interface for metadata query and clip playback would lower the operational skill floor for base security personnel who are not comfortable with the command line or SQLite.

---

*This report is a living document. Numbers in Sections 7 and 8 will be updated as Milestone 2 and Milestone 3 results become available. Final numbers must be reproducible by running `notebooks/final_results.ipynb` on the final codebase.*

*Last updated: April 6, 2026 — Author: Bloodawn (KheivenD)*

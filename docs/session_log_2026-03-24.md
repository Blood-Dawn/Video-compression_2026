# Session Log - 2026-03-24
**Author:** Bloodawn (KheivenD)
**Session duration:** ~4 hours
**Branch:** main
**Status:** Complete - all work committed and pushed to GitHub

---

## Summary

This was the first full working session after project setup. The goal was to lay down
the core detection pipeline, write the tooling needed for the March 30 progress report,
acquire real benchmark data, and run the first successful demo on the CDnet 2014 dataset.
All objectives were completed.

---

## Files Created or Modified

### `src/utils/frame_source.py` (NEW)
**Purpose:** Unified video reader that transparently handles two input formats.

CDnet 2014 (the benchmark dataset we downloaded) stores each scene as thousands of
individual JPEG frames in an `input/` subfolder rather than as a single video file.
Standard OpenCV `VideoCapture` cannot handle this format without special setup. This
module provides a `FrameSource` class that wraps both cases - you give it any path
(video file or CDnet scene folder) and the calling code never has to know the difference.

Key behaviors:
- Auto-detects whether input is a video file or CDnet image sequence
- If given a CDnet scene folder, finds the `input/` subfolder automatically
- Reads `temporalROI.txt` from CDnet scenes - this file specifies the frame range
  that has valid ground truth annotations. Frames before the start are warmup frames.
- `get_warmup_frames()` returns the correct warmup duration per scene from temporalROI,
  so background model initialization is consistent with the CDnet benchmark spec
- Exposes `fps`, `width`, `height`, `total_frames`, and `get_scene_name()` identically
  whether reading a video or image sequence
- Supports Python context manager (`with FrameSource(...) as src:`)

**Why this matters:** Without this, `demo_detection.py` and `run_benchmark.py` would
only work on video files. Now they work directly on the CDnet dataset without any
preprocessing step.

---

### `demo_detection.py` (NEW, then updated for CDnet support)
**Purpose:** Visual demonstration script that generates side-by-side comparison images
for each sampled frame, plus a foreground coverage report.

Output per frame: three-panel JPEG image saved to `outputs/demo_frames/`:
- Panel 1: Original camera frame
- Panel 2: Foreground mask (green pixels = foreground, black = background)
- Panel 3: Original frame with bounding boxes drawn around detected objects

Coverage report printed to stdout shows:
- Average % of pixels that are foreground across the full clip
- Peak foreground % (the busiest single frame)
- How many frames had any detectable activity

**Why this matters:** This is the primary deliverable for the March 30 sponsor report.
The coverage number (e.g., "8.76% foreground") is the single most important data point
in the whole project - it proves that the overwhelming majority of surveillance footage
is static background that can be compressed aggressively.

Key functions:
- `FrameSource` (imported from utils) - handles CDnet and video input
- `build_comparison_grid()` - assembles the three-panel image for one frame
- `mask_to_bgr()` - converts single-channel binary mask to green-on-black BGR image
- `add_label()` - burns a text label into the bottom of each panel
- `analyze_video()` - main loop: reads frames, runs subtractor, saves images, accumulates stats
- `compare_all_methods()` - runs MOG2 and KNN sequentially on the same input
- `print_coverage_report()` - formats and prints the final stats table

CLI flags: `--input`, `--method`, `--all-methods`, `--sample-rate`, `--warmup`, `--output`

---

### `scripts/run_benchmark.py` (NEW, then updated for CDnet support)
**Purpose:** Quantitative compression benchmark. Compares our selective pipeline against
naive full-frame H.264 encoding and reports compression ratios, PSNR, and SSIM.

Target metric: beat the sponsor's 6x compression baseline (from Cody's YOLO experiment).

How it works:
1. For CDnet scenes: assembles individual JPEG frames into a temporary AVI video using
   `sequence_to_video()` so FFmpeg has a single-file input
2. Encodes a baseline copy at uniform CRF 23 (standard H.264, no intelligence)
3. Runs background subtraction on the clip; if foreground detected, encodes at CRF 20;
   if no activity, encodes at CRF 40
4. Measures PSNR and SSIM between original and each compressed version
5. Reports compression ratio for both; flags rows that beat 6x with "YES"

Key functions:
- `sequence_to_video()` - assembles CDnet frames into temp AVI for FFmpeg
- `resolve_input_scenes()` - resolves a path to a list of scenes (handles single scene
  folders, category folders like `baseline/`, and plain video files)
- `encode_baseline()` - naive full-frame FFmpeg H.264 encode at CRF 23
- `encode_selective()` - our pipeline: detect then choose CRF
- `measure_quality()` - samples N evenly-spaced frames, computes PSNR and SSIM
- `benchmark_one()` - runs full pipeline for one (scene, method) pair
- `print_benchmark_table()` - formatted results table
- `save_csv()` - exports results to CSV for report charts

CLI flags: `--input`, `--all-methods`, `--warmup`, `--csv`

---

### `src/pipeline/pipeline.py` (MODIFIED - warmup fix)
**What changed:** Added `warmup_frames` parameter (default 120) to `run_pipeline()`.

**Why:** MOG2 and KNN both build their background model incrementally. During the first
N frames (typically 100-200), the model has not converged and produces noisy masks where
most of the frame looks like foreground. If encoding starts from frame 0, the first few
seconds of every output segment are miscompressed because the detector is unreliable.

The fix adds a warmup gate: the subtractor still processes every frame (it needs them to
build its model), but frames during the warmup period are not written to the output
segment buffer and their region lists are discarded. Encoding only begins after the model
stabilizes.

Also added `--warmup` CLI argument so the warmup length can be tuned per deployment.

**Important for the team:** If you run the pipeline on a short test clip (< 150 frames),
you may see zero output because the entire clip falls inside the warmup window. Use
`--warmup 30` for very short test clips.

---

### `docs/design_note_object_memory.md` (NEW)
**Purpose:** Design note for the object memory / reference registry feature.

**The idea (proposed by Bloodawn - KheivenD):** The current pipeline treats every
detection as a new unknown event. A base entry camera sees the same 50 authorized
vehicles daily - every pass generates a new high-quality clip of an already-known plate.

Proposed solution: maintain a registry of known objects (vehicles, people). When an
object is first seen, store one high-quality reference screenshot and a short clip.
On subsequent sightings of the same object in the expected context, log only a row in
the database (timestamp, camera, confidence) - no new video file. If the same object
appears in an unexpected location (wrong gate, wrong time), flag it as an anomaly and
store a full clip.

This replaces video clips with single JPEGs for known objects, which the design note
estimates eliminates ~89 clip files per vehicle per month.

Also addresses the sponsor's hallucination concern: for objects IN the registry, do not
apply AI super-resolution. Return the original clean reference screenshot instead. Only
apply SR to unknown objects, with a forensic watermark.

**Assigned to:** Victor De Souza Teixeira (lead), Riley Roberts (ORB feature matching).
Target milestone: Milestone 2.

Schema additions to `metadata.db`:
- `object_registry` table - one row per unique known object
- `object_sightings` table - one row per re-sighting of a known object

---

### `docs/design_note_night_video_quality.md` (NEW)
**Purpose:** Documents the night video glare problem observed during today's demo run.

The `bridgeEntry` nightVideos scene showed noisy masks where streetlamp and headlight
glare was being detected as foreground. The key finding: MOG2 and KNN behave oppositely
at night compared to daytime. MOG2 reported 2.10% FG at night vs 8.76% during the day.
KNN reported 4.42% FG at night vs 7.10% during the day.

Root cause: MOG2's Gaussian model absorbs stable light sources into the background over
time. KNN stores raw pixel samples and stays sensitive to flickering light. At night,
KNN picks up more false positives from light variation than MOG2.

Proposed fixes in priority order:
1. CLAHE preprocessing - adaptive histogram equalization to reduce point light bloat
2. Higher `varThreshold` for night-mode subtractor config
3. Run on CDnet thermal category (IR footage, no glare)
4. SuBSENSE/LOBSTER algorithm (Milestone 2 stretch)

Assigned to Riley (CLAHE implementation), Bloodawn (pipeline --night-mode flag).

---

### `README.md` (MODIFIED)
**What changed:** Added "Test Datasets and Attribution" section with proper academic
citations for both CDnet 2014 and the VIRAT Video Dataset.

CDnet 2014 citations:
- Wang et al., IEEE CVPR Workshops, 2014 (CDnet 2014)
- Goyette et al., IEEE CVPR Workshops, 2012 (original CDnet)

VIRAT citation:
- Oh et al., IEEE CVPR, 2011
- IARPA DIVA annotations via Kitware (diva-te@kitware.com)

**Why this matters:** Both datasets require attribution per their terms of use.
This must be included in any publication, report, or submission that uses the data.
This is standard academic practice and the sponsor will expect it in the final repo.

---

### `.gitignore` (MODIFIED)
**What changed:** Added explicit exclusions for `data/dataset/` and
`data/viratannotations-master/`.

**Why:** The CDnet dataset contains 319,196 individual image files. Committing these
to GitHub would create an enormous repository that would be nearly impossible to clone
and would violate CDnet's redistribution terms. The dataset must be downloaded locally
by each team member using the links in the README attribution section.

Reminder for new team members: after cloning, you must download the CDnet dataset
from www.changedetection.net and extract it to `data/dataset/`.

---

## Demo Results - 2026-03-24

### Run 1: `data/dataset/baseline/highway/` (daytime, static overhead highway camera)

| Algorithm | Avg FG Coverage | Max FG Coverage | Background % |
|---|---|---|---|
| MOG2 | 8.76% | 39.57% | 91.2% |
| KNN | 7.10% | 18.63% | 92.9% |

1,580 frames analyzed (120 warmup). Both algorithms detected activity in >99% of frames
(highway is a busy scene). 53 comparison images saved to `outputs/demo_frames/`.

**Interpretation:** On average, only 8.76% of each highway frame needs high-quality
encoding. The other 91.2% is static road, guard rails, and sky that can be compressed
at CRF 40+ with negligible visual impact. KNN produced tighter masks (smaller bounding
boxes, lower peak FG%) which would result in better compression ratios in the full
pipeline.

### Run 2: `data/dataset/nightVideos/bridgeEntry/` (night, bridge pedestrian/vehicle entry)

| Algorithm | Avg FG Coverage | Max FG Coverage | Background % |
|---|---|---|---|
| MOG2 | 2.10% | 6.53% | 97.9% |
| KNN | 4.42% | 9.61% | 95.6% |

2,380 frames analyzed (120 warmup). Activity detected in 100% of frames, but the masks
are noisy due to light glare from bridge streetlamps. 80 comparison images saved.

**Notable finding:** The algorithm behavior reversed at night. KNN showed MORE foreground
than MOG2 in the night scene (opposite of daytime). MOG2 showed even better compression
potential at night (97.9% background) but the mask quality is lower due to glare. See
`docs/design_note_night_video_quality.md` for the full analysis and proposed fixes.

**Interpretation:** Night scenes have more compression potential in raw numbers (lower
foreground %) but the detection quality is degraded. This is a known tradeoff and will
need algorithmic work before the night pipeline is reliable for forensic use.

---

## Commits Made Today

1. `feat: add demo, benchmark, warmup fix, dataset attribution` - main code commit
2. `feat: CDnet image sequence support + successful demo run` - frame_source + CDnet support

Both pushed to `origin main`.

---

## Open Items / Next Session

- Run the benchmark (`scripts/run_benchmark.py`) to get compression ratio numbers for
  the March 30 report - need FFmpeg on the VS Code terminal PATH
- Run demo on `data/dataset/thermal/corridor/` to establish IR baseline (no glare)
- Riley: implement CLAHE preprocessing option in BackgroundSubtractor
- Victor: review `docs/design_note_object_memory.md` and confirm Milestone 2 scope
- All team members: clone repo, follow DEV.md setup, download CDnet dataset, run
  `bash check_deps.sh` to verify environment
- March 30 report: use highway coverage numbers (91.2% compressible background) as
  the headline stat. Include 2-3 comparison images from `outputs/demo_frames/`.

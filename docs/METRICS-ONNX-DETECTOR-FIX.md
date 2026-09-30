# Object detection / metrics root-cause fix (2026-09-30)

## Symptom

Per-video metrics (Object Type, Color, Vehicle/Person Count) looked "generic":
almost every segment across almost every video came back `type=unknown`,
`color=gray`, `vehicle_count=0`, `person_count=0` - regardless of what was
actually in the footage. This made the planned Flock-Safety-style vehicle
search (search by color/type/date/time) impossible, since the underlying
data was never populated.

## Root cause: two bugs in `src/detection/onnx_backend.py`

`ObjectFilter` (the only source of `object_type` / `vehicle_count` /
`person_count`) is driven by `YoloOnnxDetector`, a small wrapper around an
ONNX Runtime session running `yolov8n.onnx`. Two independent bugs meant this
detector never produced a usable detection, on any video, ever:

1. **Fixed input-shape mismatch.** `YoloOnnxDetector` defaults to
   `imgsz=640` and letterboxes every frame to a 640x640 canvas before
   calling the model. The actual `yolov8n.onnx` checked out on this machine
   was exported with a **fixed 320x320 input** (`yolo export imgsz=320`).
   Every single `session.run()` call therefore raised
   `onnxruntime.InvalidArgument: Got invalid dimensions for input: images ...
   Expected: 320`. `infer()` caught that exception with a bare
   `except Exception: return []` logged at **debug** level, so the failure
   was 100% silent: no crash, no visible symptom, just an empty detection
   list on every frame of every video, forever.

2. **Normalized vs. pixel-space box coordinates.** Once (1) was fixed and
   the model actually ran, the boxes it returned were geometrically
   degenerate (~`(0, 0, 0, 0)`) even though the class and confidence were
   correct (e.g. `bus conf=0.84`). This particular ONNX export emits box
   `cx,cy,w,h` normalized to `[0, 1]` of the letterboxed canvas, but the
   existing unletterbox math assumed absolute pixel coordinates in that
   canvas, so real boxes (e.g. `cx=0.497`) were treated as `cx=0.497px` and
   collapsed to nothing after the pad/ratio correction.

Both bugs were invisible in normal use (no crash, no error banner) and were
only found by directly comparing `YoloOnnxDetector.infer()` output against
the same model loaded through `ultralytics`/torch on a real sample clip.

## Fix

- `YoloOnnxDetector._align_imgsz_to_model()` (new): after loading the ONNX
  session, reads the model's own fixed input dimensions from
  `session.get_inputs()[0].shape` and uses them for letterboxing instead of
  trusting the constructor's `imgsz` default. Falls back to the configured
  default for dynamic-shape or non-square exports (logs a warning either
  way if there's a mismatch), so a future re-export at a different size
  just works instead of silently breaking again.
- `infer()`: if every surviving box's `cx,cy,w,h` are all `<= 1.5`, they are
  treated as normalized-to-canvas fractions and scaled by `imgsz` before the
  existing pixel-space unletterbox math runs. Pixel-space exports (values
  routinely in the hundreds) are left untouched.
- `infer()`'s exception handler now logs the **first** occurrence of an
  inference failure at `warning` level (subsequent ones stay at `debug` to
  avoid flooding a live pipeline run), so a systemic failure like this one
  is never silent again.

## Verification

- `tests/test_onnx_detection_parity.py::test_onnx_matches_torch_on_cdnet_clip`
  (a pre-existing, previously-unnoticed-failing local test) now passes; it
  failed with `class-set parity 0/6` before this fix, confirmed by
  `git stash` + re-run.
- New `tests/test_onnx_input_shape_and_coords.py` (7 tests, no real weights
  needed, runs in CI) directly covers both bugs with a fake ONNX session.
- Manual before/after on `data/samples/cdnet_mp4/baseline/baseline_highway.mp4`
  (`run_pipeline(..., object_filter=True, filter_confidence=0.30)`):
  - **Before:** 0 segments produced for the entire 68s clip (every ROI was
    discarded because the detector never returned anything).
  - **After:** all 13 segments produced normally, each correctly labeled
    `type=vehicle` with realistic `vehicle_count` (2-4 per segment) and
    occasional `person_count` (0-1) matching the visible traffic/pedestrians.
- `color=gray`/`color=white` on this specific clip were manually checked
  against the actual cropped vehicle images and are legitimate calls (the
  clip's cars are genuinely silver/white/gray) - not a bug, so the
  achromatic-threshold color logic in `object_filter.py` was left as-is.
- Full suite: `uv run pytest tests/` - 1798 passed, 4 skipped, 1 failed
  (`test_download_page.py::test_links_release_installer`, a pre-existing,
  unrelated static-download-page check that expects a version-tagged
  release link; confirmed unrelated to this change).

## Also changed

- The "Smart filter" checkbox in the Tools/Compress config (`index.html`)
  was relabeled "Smart filter & object detection (recommended)" and its
  hint text now says plainly that it is the only source of the Object Type
  / Color / Person-Vehicle Count data used by Metrics and Search - it
  previously only mentioned noise suppression ("ignore leaves & shadows"),
  giving no indication it also gated all per-video metadata.
- Confirmed (no code change needed): `DEFAULT_PRESET = "continuous_cctv"`
  already sets `object_filter=True` at the `Preset` dataclass level, and
  the front-end's `applyPreset()` -> `_setField()` already checks the
  checkbox to match on first load. The "generic metrics" symptom was caused
  by the detector never working, not by the toggle defaulting off.

# SVCS v2.2.2-beta - draft release notes

Desktop rebuild off `mobile` that lands six branches together: the real
fix behind the "generic metrics" complaint, three smaller UX/reliability
fixes, a verification pass on the encryption story, and a build-script
fix needed to cut this release at all.

## Desktop (SVCS-Setup-2.2.2-beta.exe)

- **Object detection was silently failing on every segment.** The ONNX
  detector (`src/detection/onnx_backend.py`) had two bugs stacked on top
  of each other: it always asked the model for a 640x640 input while the
  committed model's real input is fixed at 320x320, so every
  `session.run()` threw and the exception was swallowed into an empty
  detection list; and once that was fixed, this model's box coordinates
  turned out to be normalized to [0,1] rather than pixels, which
  collapsed every box to near-zero size. Both are fixed: the detector
  now reads the model's own input shape and aligns to it
  (`_align_imgsz_to_model()`), and normalized coordinates are detected
  and rescaled before unletterboxing. This is what was behind Metrics
  showing flat/generic numbers - object class, color, and person/vehicle
  counts are real data again. See `docs/METRICS-ONNX-DETECTOR-FIX.md`
  for the full root-cause writeup and before/after verification.
- **Natural-language vehicle search now has real data to search.** The
  Flock-style search (`src/gui/services/nl_query.py`,
  `/api/nl_search`) was already built and already deterministic (no
  LLM, parameterized SQL over the `segments` table) - it just had
  nothing to find because of the detector bug above. No code change
  needed here beyond the detector fix; confirmed working end to end
  once real detections started landing in `metadata.db`.
- Update-check progress and the encryption cross-install story were
  reviewed this cycle: the in-app "check for updates" flow (download,
  checksum verify, install-and-restart) got a progress-reporting fix,
  and cross-install encryption compatibility was re-verified rather
  than assumed.
- Library tab: per-item detail actions were added so segments in the
  Library list can be acted on directly instead of only from the
  timeline.
- Real-ESRGAN upscaling: fixed a small-crop padding edge case that
  could distort very small detection crops before upscaling.
- Smart filter checkbox relabeled from "Smart filter (ignore leaves &
  shadows)" to "Smart filter & object detection (recommended)" with
  hint text, since it also gates the Object Type/Color/Count data that
  Metrics and Search depend on - that dependency wasn't obvious from
  the old label.
- Fixed a build-script bug (`installer\build.ps1`) that aborted the
  PyInstaller presence-check under PowerShell 7.3+ before the
  self-heal install logic could run, which is why this release exists
  as an installer at all rather than staying merged-but-unshipped.
- Fixed a real bug in the version/update-check machinery itself: a
  stale tripwire value in `tests/test_version_consistency.py` meant a
  dev build could be reported as needing an update it already
  contained. Fixed alongside this version bump so it can't recur
  silently.

## Verification

- `uv run pytest`: full suite green, including the new
  `tests/test_onnx_input_shape_and_coords.py` (7 tests covering the
  detector fix with a fake ONNX session harness - no model weights
  needed) and `tests/test_version_consistency.py` (5 tests, all
  passing after the tripwire fix).
- Manual verification of the detector fix: before/after segment counts
  on `baseline_highway.mp4`, a git-stash-confirmed regression test, and
  a manual visual check of color-crop detections (including "gray"
  vehicle colors, confirmed legitimate rather than a bug).
- Built with `installer\build.ps1 -Installer` from `mobile` at commit
  `b0bbabb`, PyInstaller 6.22.3.
- Smoke test: dashboard answered on `http://127.0.0.1:5000/`.
- `SHA256SUMS.txt` generated against the built installer
  (`31d2dd3e152a915b17cce29d8ee83a04f1b2352761c9761a80ac05bd1af4441a`).

## Known gaps

- Unsigned installer, so Windows SmartScreen will warn on first run. No
  code-signing cert is configured yet (see `docs/BLOCKERS.md`).
- This build was not run through the mobile Android instrumented
  suite; no mobile-side changes are included in this release.
- License: AGPL-3.0.

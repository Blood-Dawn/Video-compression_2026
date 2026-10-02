# SVCS v2.2.3-beta - draft release notes

Desktop rebuild off `mobile` that fixes a real behavior bug in Mode 0,
closes a UI leak in the preset cards, makes live-camera auto-compress
sensible out of the box, and adds a timelapse feature that was the one
real gap found in a competitive pass against Reolink/Synology/Frigate-
style NVR tools.

## Desktop (SVCS-Setup-2.2.3-beta.exe)

- **Mode 0 (plain compression) no longer blurs or reprocesses the
  background.** Mode 0 is meant to be a visually-unchanged CRF/codec
  encode - just smaller files, same footage. It was instead running the
  same background-blur pass as the detection modes
  (`compress_background` was tied to `mode == "mode0"`) and deriving a
  whole segment's CRF from only its first post-warmup frame. Both are
  fixed in `src/pipeline/pipeline.py`: `compress_background` is now
  `False` unconditionally for every mode, and Mode 0 always treats the
  segment as having targets (`has_targets=True`) instead of depending on
  region detection. Compressed output from Mode 0 now looks the same as
  the source, only smaller.
- **Preset cards were leaking stale settings.** Clicking a mode/preset
  card didn't actually reset CRF, codec, background method, object
  filter, or segment length - it left whatever the page's initial
  preset had set, so switching presets could silently keep settings
  from the previous one. Fixed in `pipeline.js`/`presets.js` so
  selecting a card resets all of those fields to that mode's real
  defaults.
- **Live-camera auto-compress now defaults to a sane interval.** A live
  camera or stream input (webcam index, `rtsp://`, `rtmp://`, `http(s)://`)
  defaulted to the same 60-second segment length as a file input, which
  is far too aggressive for continuous surveillance. It now defaults to
  600 seconds (10 minutes) for live sources while files keep the 60s
  default; an operator's explicit value always wins over the default
  (`src/gui/routes/pipeline_bp.py`, `pipeline.js`). Verified end-to-end
  against a real connected webcam (EMEET SmartCam S600): correct
  defaults on input-source change, pre-start mode switching honored,
  and a clean mid-run stop with no orphaned camera lock.
- **New timelapse feature.** A "Make timelapse" button on each segment's
  detail card speeds up an already-encoded clip via ffmpeg
  (`setpts`-based, 2x-60x, default 8x) and saves the result as a new
  library entry (`src/utils/timelapse.py`, `POST /api/timelapse` in
  `src/gui/routes/timelapse_bp.py`, `timelapse.js`). This is a standalone
  post-process over a finished file - it never touches the live encode
  loop - and closes the one real feature gap identified in a
  competitive review against Reolink/Synology/Frigate-style NVR
  products; the rest of the researched feature set (zones, event
  logging, webhooks, retention, ROI encoding, HLS streaming) already
  existed in SVCS.
- Added a "server activity" dashboard drawer surfacing live
  pipeline/server status at a glance (`global_status.js`, `status.js`).
- 4 new free, commercially-licensed test clips (Mixkit) covering
  pedestrians, a night crosswalk, a park path, and a government building
  exterior, for pipeline coverage beyond highway traffic
  (`data/samples/test_footage/`).
- `docs/releases/SVCS-Mode-Benchmark-Report.pdf`: before/after frames and
  per-mode size/ratio numbers for all 4 modes on the Hawaii H-1 Waimalu
  highway clip.

## Verification

- `uv run pytest`: full suite green - 1826 passed, 5 skipped, 0 failed,
  including 14 new tests in `tests/test_timelapse.py` and updated
  route-count/blueprint-registration guard tests for the new
  `/api/timelapse` route.
- Live-camera default verified against real hardware (EMEET SmartCam
  S600), not just mocked - direct `/api/start`/`/api/status`/`/api/stop`
  calls against a running server confirmed the 600s default and a clean
  shutdown.
- Built with `installer\build.ps1 -Installer` from `mobile`, PyInstaller
  bundling FFmpeg and all detection dependencies.
- Smoke test: dashboard answered on `http://127.0.0.1:5000/`.
- `SHA256SUMS.txt` generated against the built installer
  (`dc774ce92f2dcb8a9c4bd6b994840514cfbb0352aaf333ebbde90b3fab6da238`).

## Known gaps

- Unsigned installer, so Windows SmartScreen will warn on first run - no
  code-signing cert is configured yet (see `docs/BLOCKERS.md`). Click
  "More info" then "Run anyway" to proceed.
- Not run on a separate clean Windows VM with no Python/FFmpeg
  preinstalled; smoke-tested on the build machine only.
- This build was not run through the mobile Android instrumented suite;
  no mobile-side changes are included in this release.
- License: AGPL-3.0.
